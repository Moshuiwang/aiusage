from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from .collector_store import (
    DEFAULT_LIMIT_TTL_SECONDS,
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_FLUSH_BATCH,
    DEFAULT_OUTBOX_PATH,
    OutboxConfig,
)
from .version_contract import DEFAULT_RELEASE_CHANNEL, RELEASE_CHANNELS


class ConfigError(ValueError):
    pass


def load_config(path: str) -> Dict[str, Any]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)

    timezone = config.get("timezone")
    if not isinstance(timezone, str) or not timezone:
        raise ConfigError("config.timezone is required")

    sources = config.get("sources")
    if not isinstance(sources, list):
        raise ConfigError("config.sources must be a list")

    normalized_sources: List[Dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict):
            raise ConfigError("each source must be an object")
        normalized = dict(source)
        normalized.setdefault("enabled", True)
        normalized.setdefault("timeout_seconds", 30)
        normalized.setdefault("reports", {})
        _validate_source(normalized)
        normalized_sources.append(normalized)

    return {"timezone": timezone, "sources": normalized_sources}


def _validate_source(source: Dict[str, Any]) -> None:
    required = ["source_id", "type", "host_label", "os_user"]
    for key in required:
        if not source.get(key):
            raise ConfigError(f"source.{key} is required")

    source_type = source["type"]
    reports = source.get("reports") or {}
    if source_type in {"local", "ssh"}:
        command = reports.get("daily", {}).get("command")
        if not command:
            raise ConfigError(f"{source['source_id']} reports.daily.command is required")
    elif source_type == "file_import":
        path = reports.get("daily", {}).get("path")
        if not path:
            raise ConfigError(f"{source['source_id']} reports.daily.path is required")
    else:
        raise ConfigError(f"unsupported source type: {source_type}")

    if source_type == "ssh":
        for key in ["ssh_user", "ssh_host"]:
            if not source.get(key):
                raise ConfigError(f"{source['source_id']} {key} is required")


SUPPORTED_PLATFORMS = ("darwin", "linux", "windows")


def normalize_platform(value: Any) -> str:
    """设备平台的唯一规范化口径：大小写无关，`mac` 等价于 `darwin`。

    doctor 等下游检查必须复用本函数，不要各自再定义一份，
    否则一台写 `platform: "mac"` 的合法 Mac 会被判成身份写错。
    """

    platform = str(value or "").strip().lower()
    if platform == "mac":
        platform = "darwin"
    if platform not in SUPPORTED_PLATFORMS:
        raise ConfigError(f"Unsupported device platform: {platform}")
    return platform


@dataclass
class DeviceConfig:
    schema_version: int
    source_id: str
    host: str
    machine: str
    os_user: str
    platform: str
    timezone: str
    server_url: str
    timeout_seconds: int = 30
    token_env: Optional[str] = None
    ai_accounts: Optional[Dict[str, Dict[str, Any]]] = None
    release_channel: str = DEFAULT_RELEASE_CHANNEL
    #: 本地 outbox（#73）。``None`` = 这台设备从未启用过，走原来的直推路径，行为零变化。
    #: 存在但 ``enabled=False`` = 已回退到直推，pusher 会先确认磁盘上没有未排空的数据。
    outbox: Optional[OutboxConfig] = None


def validate_device_config(data: Dict[str, Any]) -> DeviceConfig:
    """
    校验终端本地的推送配置，如果有缺项或含有敏感 SSH 配置，抛出 ConfigError
    """
    if not isinstance(data, dict):
        raise ConfigError("Device config must be a JSON object")

    # 1. SSH 防御性拦截
    for key in data.keys():
        if "ssh" in str(key).lower():
            raise ConfigError("SSH parameters are forbidden in device config")

    # 2. 必需字段校验
    required = ["source_id", "server_url", "timezone", "platform"]
    for field in required:
        if not data.get(field):
            raise ConfigError(f"Missing required device config field: {field}")

    # 3. 平台转换与校验
    platform = normalize_platform(data["platform"])

    # 4. 发布通道：只接受版本合同声明的通道，避免各设备自定义通道名
    release_channel = str(data.get("release_channel") or DEFAULT_RELEASE_CHANNEL)
    if release_channel not in RELEASE_CHANNELS:
        raise ConfigError(
            "Unsupported device release_channel: " + ", ".join(RELEASE_CHANNELS) + " expected"
        )

    return DeviceConfig(
        schema_version=int(data.get("schema_version", 1)),
        source_id=str(data["source_id"]),
        host=str(data.get("host", "unknown")),
        machine=str(data.get("machine") or socket.gethostname() or data.get("host", "unknown")),
        os_user=str(data.get("os_user", "unknown")),
        platform=platform,
        timezone=str(data["timezone"]),
        server_url=str(data["server_url"]),
        timeout_seconds=int(data.get("timeout_seconds", 30)),
        token_env=data.get("token_env"),
        ai_accounts=data.get("ai_accounts") if isinstance(data.get("ai_accounts"), dict) else None,
        release_channel=release_channel,
        outbox=_parse_outbox(data.get("outbox")),
    )


def _parse_outbox(raw: Any) -> Optional[OutboxConfig]:
    """解析设备配置里的 ``outbox`` 块。

    整块缺失返回 ``None``——那台设备走原来的直推路径，一个字节都不变。
    写错的配置一律 ``ConfigError`` 当场报错：一个「悄悄用默认值兜底」的 outbox
    配置错误，表现出来就是「以为在缓冲、其实没有」，故障时才发现历史已经没了。
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError("config.outbox must be an object")

    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("config.outbox.enabled must be a boolean")

    path = raw.get("path", DEFAULT_OUTBOX_PATH)
    if not isinstance(path, str) or not path.strip():
        raise ConfigError("config.outbox.path must be a non-empty string")
    # 相对路径会让「库文件是哪个」取决于谁用什么 cwd 拉起采集：LaunchAgent 的 cwd 通常
    # 是 `/` 或 `$HOME`，人工执行时是仓库根。两次运行会开两个库，先前缓冲的数据从此
    # 无人读取，且账面上看不出任何异常。这正是本 Issue 要消灭的静默丢失，所以在这里
    # 就拒绝，而不是等到某次真实故障之后才发现。
    resolved = Path(path.strip()).expanduser()
    if not resolved.is_absolute():
        raise ConfigError(
            "config.outbox.path must be an absolute path (or start with ~); "
            f"got a relative path: {path}"
        )

    max_bytes = _positive_int(raw, "max_bytes", DEFAULT_MAX_BYTES)
    max_flush_batch = _positive_int(raw, "max_flush_batch", DEFAULT_MAX_FLUSH_BATCH)

    limit_ttl_seconds = raw.get("limit_ttl_seconds", DEFAULT_LIMIT_TTL_SECONDS)
    try:
        limit_ttl_seconds = float(limit_ttl_seconds)
    except (TypeError, ValueError):
        raise ConfigError("config.outbox.limit_ttl_seconds must be a number") from None
    if limit_ttl_seconds <= 0:
        raise ConfigError("config.outbox.limit_ttl_seconds must be positive")

    return OutboxConfig(
        enabled=enabled,
        path=str(resolved),
        max_bytes=max_bytes,
        limit_ttl_seconds=limit_ttl_seconds,
        max_flush_batch=max_flush_batch,
    )


def _positive_int(raw: Dict[str, Any], key: str, default: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"config.outbox.{key} must be an integer")
    if value <= 0:
        raise ConfigError(f"config.outbox.{key} must be positive")
    return value
