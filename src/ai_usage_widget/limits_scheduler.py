from __future__ import annotations

import os
import plistlib
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping

from .macos_launchd import CommandRunner, ensure_agent_loaded


@dataclass(frozen=True)
class LimitsSchedulerConfig:
    repo_dir: Path
    limits_config: Path
    url: str
    token_env_file: Path
    runner_path: Path
    plist_path: Path
    log_dir: Path
    lock_file: Path
    runtime_src_dir: Path | None = None
    runtime_limits_config: Path | None = None
    label: str = "com.chunbai.aiusage.limits-push"
    interval_seconds: int = 1800
    python_executable: str = "/usr/bin/python3"
    token_env_name: str = "AI_USAGE_INGEST_TOKEN"
    path_value: str | None = None


def install_limits_scheduler(
    config: LimitsSchedulerConfig,
    *,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
    activate: bool = False,
    command_runner: CommandRunner | None = None,
) -> Dict[str, Any]:
    _validate_config(config)
    supplied_env = env or os.environ
    token_value = supplied_env.get(config.token_env_name, "")
    if not dry_run and not token_value:
        raise ValueError(f"missing token env: {config.token_env_name}")

    result = {
        "success": True,
        "dry_run": dry_run,
        "label": config.label,
        "interval_seconds": config.interval_seconds,
        "repo_dir": str(config.repo_dir),
        "limits_config": str(config.limits_config),
        "url": config.url,
        "token_env_file": str(config.token_env_file),
        "runner_path": str(config.runner_path),
        "plist_path": str(config.plist_path),
        "log_dir": str(config.log_dir),
        "runtime_src_dir": str(_runtime_src_dir(config)),
        "runtime_limits_config": str(_runtime_limits_config(config)),
        "launchctl_bootstrap": f"launchctl bootstrap gui/$(id -u) {config.plist_path}",
        "launchctl_kickstart": f"launchctl kickstart -k gui/$(id -u)/{config.label}",
        "activation": {
            "requested": activate,
            "performed": False,
            "reason": "dry_run" if dry_run else "not_requested",
        },
    }
    if dry_run:
        return result

    _validate_source_paths(config)
    config.token_env_file.parent.mkdir(parents=True, exist_ok=True)
    config.runner_path.parent.mkdir(parents=True, exist_ok=True)
    config.plist_path.parent.mkdir(parents=True, exist_ok=True)
    config.lock_file.parent.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)

    _write_token_env(config.token_env_file, config.token_env_name, token_value)
    _copy_runtime_files(config)
    _write_runner(config)
    _write_plist(config)
    if activate:
        result["activation"] = ensure_agent_loaded(
            config.plist_path,
            config.label,
            command_runner=command_runner,
        )
        result["activation"]["performed"] = True
    return result


def _validate_config(config: LimitsSchedulerConfig) -> None:
    if config.interval_seconds < 300:
        raise ValueError("interval_seconds must be at least 300")
    if not config.url.startswith(("http://", "https://")):
        raise ValueError("url must be http(s)")
    if not config.label.strip():
        raise ValueError("label is required")


def _validate_source_paths(config: LimitsSchedulerConfig) -> None:
    """源代码和配置缺失时，先拒绝安装，保留现有运行文件（#144）。"""
    package = config.repo_dir / "src" / "ai_usage_widget"
    for name, path in (
        ("source_init", package / "__init__.py"),
        ("source_cli", package / "cli.py"),
        ("limits_config", config.limits_config),
    ):
        if not path.is_file():
            raise ValueError(f"installation preflight failed: {name} must be a file: {path}")


def _write_token_env(path: Path, token_env_name: str, token_value: str) -> None:
    path.write_text(f"{token_env_name}={_shell_single_quote(token_value)}\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _write_runner(config: LimitsSchedulerConfig) -> None:
    runtime_src_dir = _runtime_src_dir(config)
    runtime_limits_config = _runtime_limits_config(config)
    python_launcher = (
        "import sys; "
        f"sys.path.insert(0, {str(runtime_src_dir)!r}); "
        "from ai_usage_widget.cli import main; "
        "raise SystemExit(main(sys.argv[1:]))"
    )
    script = "\n".join(
        [
            "#!/bin/zsh",
            "set -euo pipefail",
            f"cd {_shell_single_quote(str(runtime_src_dir.parent))}",
            f"source {_shell_single_quote(str(config.token_env_file))}",
            "export " + config.token_env_name,
            f"export PATH={_shell_single_quote(config.path_value)}" if config.path_value else "",
            "exec "
            + " ".join(
                [
                    _shell_single_quote(config.python_executable),
                    "-c",
                    _shell_single_quote(python_launcher),
                    "push-limits",
                    "--limits-config",
                    _shell_single_quote(str(runtime_limits_config)),
                    "--url",
                    _shell_single_quote(config.url),
                    "--token-env",
                    _shell_single_quote(config.token_env_name),
                    "--lock-file",
                    _shell_single_quote(str(config.lock_file)),
                ]
            ),
            "",
        ]
    )
    config.runner_path.write_text(script, encoding="utf-8")
    config.runner_path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)


def _write_plist(config: LimitsSchedulerConfig) -> None:
    payload = {
        "Label": config.label,
        "ProgramArguments": ["/bin/zsh", str(config.runner_path)],
        "StartInterval": config.interval_seconds,
        "RunAtLoad": True,
        "StandardOutPath": str(config.log_dir / "limits-push.stdout.log"),
        "StandardErrorPath": str(config.log_dir / "limits-push.stderr.log"),
    }
    with config.plist_path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=False)


def _copy_runtime_files(config: LimitsSchedulerConfig) -> None:
    runtime_src_dir = _runtime_src_dir(config)
    runtime_limits_config = _runtime_limits_config(config)
    source_package = config.repo_dir / "src" / "ai_usage_widget"
    runtime_package = runtime_src_dir / "ai_usage_widget"
    runtime_src_dir.mkdir(parents=True, exist_ok=True)
    if runtime_package.exists():
        shutil.rmtree(runtime_package)
    shutil.copytree(
        source_package,
        runtime_package,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    runtime_limits_config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config.limits_config, runtime_limits_config)
    runtime_limits_config.chmod(stat.S_IRUSR | stat.S_IWUSR)


def _runtime_src_dir(config: LimitsSchedulerConfig) -> Path:
    return config.runtime_src_dir or config.token_env_file.parent / "runtime/src"


def _runtime_limits_config(config: LimitsSchedulerConfig) -> Path:
    return config.runtime_limits_config or config.token_env_file.parent / "runtime/limits.local.json"


def _shell_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
