"""采集端版本化 release 的幂等安装与升级（Issue #57）。

部署布局（root 由调用方给定，例如 /opt/ai-usage）::

    root/releases/<version>/src/...     每个版本一份代码快照
    root/releases/<version>/release.json 版本清单（doctor 靠它判定运行目录有无版本）
    root/current  -> releases/<version>  当前生效版本
    root/previous -> releases/<version>  上一个版本，回滚用
    root/config/device.json              **用户配置，已存在就绝不覆盖**
    <unit_dir>/<basename>.timer|.service 由 deploy_units 渲染，不手工维护

幂等约束：同一个 version+revision 连续安装两次，目录树、符号链接、单元文件
内容与 mtime 全部不变，也不会多出第二个 timer 或第二个来源。
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from dataclasses import asdict, dataclass
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .deploy_doctor import TIMER_SCOPES, TIMER_SCOPE_USER
from .deploy_units import CollectorUnitSpec, render_service_unit, render_timer_unit


CommandRunner = Callable[[Sequence[str]], int]

MANIFEST_NAME = "release.json"
CURRENT_LINK = "current"
PREVIOUS_LINK = "previous"
RELEASES_DIR = "releases"

#: 放 ingest token env 文件的目录只允许 owner 进入。
SECRET_DIR_MODE = 0o700
#: 设备配置含来源身份与 token 环境变量名，只允许 owner 读写。
CONFIG_FILE_MODE = 0o600


class ReleaseError(RuntimeError):
    """安装或回滚过程中的可恢复失败。"""


@dataclass(frozen=True)
class ReleasePlan:
    root: Path
    unit_dir: Path
    source_dir: Path
    version: str
    revision: str
    unit_spec: CollectorUnitSpec
    installed_at: str = ""
    device_config: Optional[Mapping[str, Any]] = None
    activation_commands: Optional[Sequence[Sequence[str]]] = None
    #: systemd manager 作用域。BIAI 现网多用户采集器是 system-level 的，
    #: 写死 --user 会在错误的 manager 上操作一个不存在的单元。
    timer_scope: str = TIMER_SCOPE_USER

    @property
    def releases_dir(self) -> Path:
        return Path(self.root) / RELEASES_DIR

    @property
    def release_dir(self) -> Path:
        return self.releases_dir / self.version

    def commands(self) -> List[List[str]]:
        if self.activation_commands is not None:
            return [list(argv) for argv in self.activation_commands]
        return [
            ["systemctl", f"--{self.timer_scope}", "daemon-reload"],
            ["systemctl", f"--{self.timer_scope}", "enable", "--now", self.unit_spec.timer_name],
        ]


def default_command_runner(argv: Sequence[str]) -> int:  # pragma: no cover - 真实系统路径
    import subprocess

    completed = subprocess.run(list(argv), capture_output=True, text=True, check=False)
    return completed.returncode


def install_release(
    plan: ReleasePlan,
    *,
    command_runner: Optional[CommandRunner] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """幂等安装或升级一个 release。重复执行不产生重复 timer、来源或配置覆盖。"""

    _validate(plan)
    root = Path(plan.root)
    unit_dir = Path(plan.unit_dir)
    spec = plan.unit_spec
    runner = command_runner or default_command_runner

    if dry_run:
        # 只回报打算做什么，一个文件都不碰，一条命令都不跑。
        return {
            "success": True,
            "dry_run": True,
            "changed": False,
            "version": plan.version,
            "revision": plan.revision,
            "release_dir": str(plan.release_dir),
            "unit_dir": str(unit_dir),
            "units": {"timer": spec.timer_name, "service": spec.service_name},
            "config_path": spec.config_path,
            "timer_scope": plan.timer_scope,
            "commands": plan.commands(),
            "rolled_back": False,
        }

    root.mkdir(parents=True, exist_ok=True)
    plan.releases_dir.mkdir(parents=True, exist_ok=True)
    unit_dir.mkdir(parents=True, exist_ok=True)

    changed = _materialize_release(plan)
    changed |= _write_unit_files(unit_dir, spec)
    config_created = _create_device_config_if_absent(plan)
    changed |= config_created
    changed |= _ensure_runtime_dirs(spec)

    previous_target = _symlink_target(root / PREVIOUS_LINK)
    changed |= _activate_release(root, plan.release_dir)
    previous_target = _symlink_target(root / PREVIOUS_LINK) or previous_target

    commands = plan.commands()
    result = {
        "success": True,
        "dry_run": False,
        "changed": changed,
        "version": plan.version,
        "revision": plan.revision,
        "release_dir": str(plan.release_dir),
        "current_target": _symlink_target(root / CURRENT_LINK),
        "previous_target": previous_target,
        "unit_dir": str(unit_dir),
        "units": {"timer": spec.timer_name, "service": spec.service_name},
        "config_path": spec.config_path,
        "config_created": config_created,
        "commands": commands,
        "rolled_back": False,
    }

    try:
        _run_commands(commands, runner)
    except (ReleaseError, OSError) as exc:
        # 激活失败就退回上一个 release 与 timer；用户配置全程不动。
        # 注意不要传新 plan 的 scope：回滚要按**上一个 release** 记录的 scope 操作，
        # 否则跨 scope 升级失败时会去另一个 manager 上重启一个不存在的单元。
        return _recover_from_failed_activation(root, unit_dir, runner, result, exc)
    return result


def _recover_from_failed_activation(
    root: Path,
    unit_dir: Path,
    command_runner: CommandRunner,
    result: Dict[str, Any],
    exc: Exception,
) -> Dict[str, Any]:
    failed = dict(result)
    failed["success"] = False
    failed["error_type"] = exc.__class__.__name__
    failed["error_message"] = str(exc)
    failed["rollback_files_restored"] = False
    try:
        rollback = rollback_release(root, unit_dir, command_runner=command_runner)
    except ReleaseError as rollback_exc:
        failed["rolled_back"] = False
        failed["rollback_error_type"] = rollback_exc.__class__.__name__
        failed["rollback_error_message"] = str(rollback_exc)
        return failed
    # 文件已经换回旧版，但 systemd 没重新加载时不能自称「已回滚」，
    # 否则就是用低一级证据宣称高一级完成。
    failed["rollback_files_restored"] = True
    failed["rolled_back"] = bool(rollback["success"])
    failed["rollback"] = rollback
    failed["current_target"] = _symlink_target(root / CURRENT_LINK)
    failed["previous_target"] = _symlink_target(root / PREVIOUS_LINK)
    return failed


def rollback_release(
    root: Path,
    unit_dir: Path,
    *,
    command_runner: CommandRunner,
    timer_scope: str | None = None,
) -> Dict[str, Any]:
    """回滚到 `previous` 指向的 release，并恢复它的 timer / service。

    只动 release 链接和由代码生成的单元文件，**绝不触碰用户配置**。
    """

    root = Path(root)
    unit_dir = Path(unit_dir)
    previous_target = _symlink_target(root / PREVIOUS_LINK)
    if not previous_target:
        raise ReleaseError("没有 previous release 可回滚")

    previous_dir = root / previous_target
    manifest = read_manifest(previous_dir)
    if manifest is None:
        raise ReleaseError(f"previous release 缺少 {MANIFEST_NAME}，无法回滚: {previous_dir}")
    spec_fields = manifest.get("unit_spec")
    if not isinstance(spec_fields, dict):
        raise ReleaseError(f"previous release 的 {MANIFEST_NAME} 缺少 unit_spec，无法回滚")

    try:
        spec = CollectorUnitSpec(**spec_fields)
    except TypeError as exc:
        raise ReleaseError(f"previous release 的 unit_spec 无法解析: {exc}") from exc

    scope = timer_scope or manifest.get("timer_scope") or TIMER_SCOPE_USER
    if scope not in TIMER_SCOPES:
        raise ReleaseError(f"timer_scope must be one of {TIMER_SCOPES}: {scope}")

    current_target = _symlink_target(root / CURRENT_LINK)
    unit_dir.mkdir(parents=True, exist_ok=True)
    _write_unit_files(unit_dir, spec)
    _replace_symlink(root / CURRENT_LINK, previous_target)
    if current_target and current_target != previous_target:
        _replace_symlink(root / PREVIOUS_LINK, current_target)

    commands = [
        ["systemctl", f"--{scope}", "daemon-reload"],
        ["systemctl", f"--{scope}", "restart", spec.timer_name],
    ]
    command_error = None
    try:
        _run_commands(commands, command_runner)
    except (ReleaseError, OSError) as exc:
        command_error = f"{exc.__class__.__name__}: {exc}"

    return {
        "success": command_error is None,
        "rolled_back_to": manifest.get("version"),
        "revision": manifest.get("revision"),
        "release_dir": str(previous_dir),
        "current_target": _symlink_target(root / CURRENT_LINK),
        "previous_target": _symlink_target(root / PREVIOUS_LINK),
        "units": {"timer": spec.timer_name, "service": spec.service_name},
        "timer_scope": scope,
        "files_restored": True,
        "commands": commands,
        "command_error": command_error,
    }


def read_manifest(release_dir: Path) -> Optional[Dict[str, Any]]:
    try:
        with (Path(release_dir) / MANIFEST_NAME).open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _validate(plan: ReleasePlan) -> None:
    if not str(plan.version).strip():
        raise ValueError("release version is required")
    if not str(plan.revision).strip():
        raise ValueError("release revision is required")
    if not plan.unit_spec.source_id:
        raise ValueError("unit_spec.source_id is required")
    if not Path(plan.source_dir).is_dir():
        raise ValueError(f"source dir not found: {plan.source_dir}")
    if plan.timer_scope not in TIMER_SCOPES:
        raise ValueError(f"timer_scope must be one of {TIMER_SCOPES}")


def _materialize_release(plan: ReleasePlan) -> bool:
    release_dir = plan.release_dir
    existing = read_manifest(release_dir)
    if existing is not None:
        if str(existing.get("revision")) != str(plan.revision):
            raise ValueError(
                f"release {plan.version} 已安装且 revision 不同"
                f"（已装={existing.get('revision')} 请求={plan.revision}）；"
                "版本号发布后不复用，请改用新版本号。"
            )
        return False

    staged_src = release_dir / "src"
    if staged_src.exists():
        shutil.rmtree(staged_src)
    release_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        Path(plan.source_dir),
        staged_src,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    _write_json(release_dir / MANIFEST_NAME, _build_manifest(plan))
    return True


def _build_manifest(plan: ReleasePlan) -> Dict[str, Any]:
    spec = plan.unit_spec
    installed_at = plan.installed_at or datetime.now(dt_timezone.utc).isoformat()
    return {
        "schema_version": 1,
        "version": plan.version,
        "revision": plan.revision,
        "installed_at": installed_at,
        "source_id": spec.source_id,
        "timer_scope": plan.timer_scope,
        "units": {"timer": spec.timer_name, "service": spec.service_name},
        "unit_spec": asdict(spec),
    }


def _write_unit_files(unit_dir: Path, spec: CollectorUnitSpec) -> bool:
    changed = _write_text_if_changed(unit_dir / spec.timer_name, render_timer_unit(spec))
    changed |= _write_text_if_changed(unit_dir / spec.service_name, render_service_unit(spec))
    return changed


def _create_device_config_if_absent(plan: ReleasePlan) -> bool:
    if plan.device_config is None:
        return False
    config_path = Path(plan.unit_spec.config_path)
    if config_path.exists():
        # 用户配置是用户的，升级绝不覆盖。
        return False
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(config_path, dict(plan.device_config))
    # 设备配置含来源身份与 token 环境变量名，不该让同机其他用户随便读。
    config_path.chmod(CONFIG_FILE_MODE)
    return True


def _ensure_runtime_dirs(spec: CollectorUnitSpec) -> bool:
    changed = False
    # 放 ingest token 的目录必须是 owner-only，不能跟着默认 umask 走。
    secrets_dir = Path(spec.env_file).parent
    if not secrets_dir.exists():
        secrets_dir.mkdir(parents=True, exist_ok=True)
        changed = True
    if stat.S_IMODE(secrets_dir.stat().st_mode) != SECRET_DIR_MODE:
        secrets_dir.chmod(SECRET_DIR_MODE)
        changed = True

    lock_dir = Path(spec.lock_file).parent
    if not lock_dir.exists():
        lock_dir.mkdir(parents=True, exist_ok=True)
        changed = True
    return changed


def _activate_release(root: Path, release_dir: Path) -> bool:
    current = root / CURRENT_LINK
    target = os.path.relpath(release_dir, root)
    current_target = _symlink_target(current)
    if current_target == target:
        return False
    if current_target is not None:
        _replace_symlink(root / PREVIOUS_LINK, current_target)
    _replace_symlink(current, target)
    return True


def _run_commands(commands: Sequence[Sequence[str]], command_runner: CommandRunner) -> None:
    for argv in commands:
        code = command_runner(list(argv))
        if code:
            raise ReleaseError(f"command failed with exit code {code}: {' '.join(argv)}")


def _symlink_target(path: Path) -> Optional[str]:
    try:
        if path.is_symlink():
            return os.readlink(path)
    except OSError:
        return None
    return None


def _replace_symlink(path: Path, target: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    if temporary.is_symlink() or temporary.exists():
        temporary.unlink()
    os.symlink(target, temporary)
    os.replace(temporary, path)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_text_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


__all__ = [
    "CURRENT_LINK",
    "MANIFEST_NAME",
    "PREVIOUS_LINK",
    "RELEASES_DIR",
    "CONFIG_FILE_MODE",
    "ReleaseError",
    "ReleasePlan",
    "SECRET_DIR_MODE",
    "default_command_runner",
    "install_release",
    "read_manifest",
    "rollback_release",
]
