from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass


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
    platform = str(data["platform"]).lower()
    if platform == "mac":
        platform = "darwin"
    if platform not in {"darwin", "linux", "windows"}:
        raise ConfigError(f"Unsupported device platform: {platform}")

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
    )
