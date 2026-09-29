"""Claude Code 云端会话（临时 Linux 容器）的用量推送入口，由 Stop hook 调用。

每个云端会话（容器）一个独立 source_id（``claude-cloud-<云端会话号>``），machine / os_user 固定，
所以不会在展示侧刷出一堆随容器主机名变化的假机器。硬约束：hook 永远返回 0，
推送失败、缺环境变量都不能阻断 Claude 会话；输出里不出现 token。
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .config import ConfigError, validate_device_config
from .pusher import DevicePusher

TOKEN_ENV = "AI_USAGE_INGEST_TOKEN"
URL_ENV = "AI_USAGE_INGEST_URL"
INTERVAL_ENV = "AI_USAGE_CLOUD_PUSH_INTERVAL_MINUTES"
TIMEZONE_ENV = "AI_USAGE_CLOUD_TIMEZONE"

SOURCE_ID_PREFIX = "claude-cloud-"
CLOUD_MACHINE = "claude-cloud"
CLOUD_OS_USER = "claude-cloud"
DEFAULT_TIMEZONE = "Asia/Shanghai"
#: 默认 15 分钟节流（环境变量 0 = 不节流）：Worker 每次 ingest 都会删除并重写当天全部来源的汇总，
#: 每次推送约写 150-350 行 D1，逐轮推送会逼近 Cloudflare Free 每日 10 万行写入（#213）。
#: 被节流挡掉的尾段由 SessionEnd hook 的 ``cloud-push --final`` 补推。
DEFAULT_INTERVAL_MINUTES = 15.0
MAX_LOOKBACK_HOURS = 6.0
#: 容器内稳定的云端会话号，优先级最高；hook（有 stdin）与手动运行（无 stdin）必须落到同一 source_id。
REMOTE_SESSION_ID_ENV = "CLAUDE_CODE_REMOTE_SESSION_ID"
#: 没有云端会话号时的兜底：stdin 的 session_id 之后，再回退到此变量。
SESSION_ID_ENV_FALLBACK = "CLAUDE_CODE_SESSION_ID"
HOOK_MARKER = "cloud-push"
_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_ID_LEN = 64


def default_state_path() -> Path:
    return Path.home() / ".ai-usage" / "cloud-push-state.json"


def derive_source_id(session_id: str) -> str:
    cleaned = _SAFE_ID.sub("-", str(session_id)).strip("-")[:_MAX_ID_LEN]
    return SOURCE_ID_PREFIX + cleaned


def resolve_session_id(stdin_text: str, env: Mapping[str, str]) -> str | None:
    """source 对应「容器 / 云端会话」而非 CLI 会话：两者都上报整个容器的日志，
    若 hook 用 CLI 会话 UUID、手动用云端会话号，同一批 token 会被计两次。
    优先级：CLAUDE_CODE_REMOTE_SESSION_ID -> stdin session_id -> CLAUDE_CODE_SESSION_ID。
    """
    try:
        data = json.loads(stdin_text) if stdin_text and stdin_text.strip() else {}
    except json.JSONDecodeError:
        data = {}
    candidates = [
        env.get(REMOTE_SESSION_ID_ENV),
        data.get("session_id") if isinstance(data, dict) else None,
        env.get(SESSION_ID_ENV_FALLBACK),
    ]
    for value in candidates:
        if isinstance(value, str) and _SAFE_ID.sub("", value):
            return value
    return None


def build_device_config(
    session_id: str, server_url: str, timezone: str, home: Path | None = None
) -> dict[str, Any]:
    """``home`` 仅供测试注入；容器内 ``~/.claude.json`` 显式声明为账户指纹来源（#208）。

    文件缺失或没有 oauthAccount 时 pusher 侧降级为不上报账户观察，这里不猜。
    """
    claude_json = (Path(home) if home is not None else Path.home()) / ".claude.json"
    return {
        "schema_version": 1,
        "source_id": derive_source_id(session_id),
        "host": CLOUD_MACHINE,
        "machine": CLOUD_MACHINE,
        "os_user": CLOUD_OS_USER,
        "platform": "linux",
        "timezone": timezone,
        "server_url": server_url,
        "timeout_seconds": 15,
        "token_env": TOKEN_ENV,
        "account_fingerprint_sources": {"claude": str(claude_json)},
    }


def lookback_hours(last_success: datetime | None, now: datetime) -> float:
    """回看窗口 = 距上次成功推送的整点数 + 1 小时余量，夹在 [1, MAX_LOOKBACK_HOURS]。"""
    if last_success is None:
        return MAX_LOOKBACK_HOURS
    elapsed_hours = max((now - last_success).total_seconds(), 0.0) / 3600.0
    return float(min(MAX_LOOKBACK_HOURS, max(1, math.ceil(elapsed_hours) + 1)))


def _interval_minutes(env: Mapping[str, str], override: float | None) -> float:
    if override is not None:
        return float(override)
    try:
        value = float(env.get(INTERVAL_ENV, ""))
    except ValueError:
        return DEFAULT_INTERVAL_MINUTES
    return value if value >= 0 else DEFAULT_INTERVAL_MINUTES


def _read_last_success(state_path: Path, source_id: str) -> datetime | None:
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("source_id") != source_id:
            return None
        parsed = datetime.fromisoformat(state["last_success_at"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt_timezone.utc)


def _write_state(state_path: Path, source_id: str, now: datetime) -> None:
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"source_id": source_id, "last_success_at": now.isoformat()}), encoding="utf-8"
        )
    except OSError:
        pass  # 写不下状态只会少一次节流，不能因此让 hook 失败


def run(
    *,
    stdin_text: str,
    env: Mapping[str, str],
    state_path: Path | None = None,
    now: datetime | None = None,
    pusher_factory: Callable[..., Any] = DevicePusher,
    interval_minutes: float | None = None,
    home: Path | None = None,
    final: bool = False,
) -> int:
    """执行一次云端推送。无论发生什么都返回 0。``final=True`` 绕过节流（SessionEnd 补推尾段）。"""
    try:
        return _run(stdin_text, env, state_path, now, pusher_factory, interval_minutes, home, final)
    except Exception as exc:  # noqa: BLE001 - hook 边界：任何异常都不得阻断会话
        print(f"cloud-push: skipped ({type(exc).__name__})", file=sys.stderr)
        return 0


def _run(stdin_text, env, state_path, now, pusher_factory, interval_minutes, home=None, final=False) -> int:
    server_url = env.get(URL_ENV, "").strip()
    if not env.get(TOKEN_ENV) or not server_url:
        return 0
    session_id = resolve_session_id(stdin_text, env)
    if session_id is None:
        return 0
    now = now or datetime.now(dt_timezone.utc)
    state_path = state_path or default_state_path()
    source_id = derive_source_id(session_id)

    last_success = _read_last_success(state_path, source_id)
    if last_success is not None and not final:
        elapsed_minutes = (now - last_success).total_seconds() / 60.0
        if 0 <= elapsed_minutes < _interval_minutes(env, interval_minutes):
            return 0

    try:
        config = validate_device_config(
            build_device_config(session_id, server_url, env.get(TIMEZONE_ENV) or DEFAULT_TIMEZONE, home=home)
        )
    except ConfigError as exc:
        print(f"cloud-push: invalid config ({type(exc).__name__})", file=sys.stderr)
        return 0
    result = pusher_factory(
        config,
        retry_attempts=2,
        ledger_mode="incremental",
        ledger_lookback_hours=lookback_hours(last_success, now),
    ).push()
    if result.get("success"):
        _write_state(state_path, source_id, now)
    else:
        print(f"cloud-push: push failed (status={result.get('status')})", file=sys.stderr)
    return 0


def _install_event_hook(settings: dict, event: str, command: str) -> None:
    groups = settings.setdefault("hooks", {}).setdefault(event, [])
    ours = {"type": "command", "command": command, "timeout": 60}
    replaced = False
    for group in groups:
        for index, hook in enumerate(group.get("hooks", [])):
            if HOOK_MARKER in str(hook.get("command", "")) and "ai-usage-widget" in str(hook.get("command", "")):
                group["hooks"][index] = ours
                replaced = True
    if not replaced:
        groups.append({"hooks": [ours]})


def install_hooks(settings_path: Path, command: str) -> None:
    """把 Stop（``command``）与 SessionEnd（``command --final``）hook 合并进用户级 settings.json：
    保留其它键和其它 hook，已有我们的条目原地更新，重复执行幂等。"""
    settings_path = Path(settings_path)
    if settings_path.exists() and settings_path.read_text(encoding="utf-8").strip():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{settings_path} 不是合法 JSON，拒绝覆盖") from exc
        if not isinstance(settings, dict):
            raise ValueError(f"{settings_path} 顶层不是对象，拒绝覆盖")
    else:
        settings = {}
    _install_event_hook(settings, "Stop", command)
    _install_event_hook(settings, "SessionEnd", f"{command} --final")
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def default_hook_command() -> str:
    import shutil

    return f"{shutil.which('ai-usage-widget') or 'ai-usage-widget'} cloud-push"


def run_cli(args) -> int:
    if args.install_hook:
        settings = Path(args.settings).expanduser() if args.settings else Path.home() / ".claude" / "settings.json"
        try:
            install_hooks(settings, default_hook_command())
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"installed Stop + SessionEnd hooks into {settings}")
        return 0
    if not os.environ.get(TOKEN_ENV) or not os.environ.get(URL_ENV):
        return 0  # 没配置就不必读 stdin
    stdin_text = "" if sys.stdin is None or sys.stdin.isatty() else sys.stdin.read()
    return run(
        stdin_text=stdin_text,
        env=os.environ,
        state_path=Path(args.state_file).expanduser() if args.state_file else None,
        final=bool(getattr(args, "final", False)),
    )
