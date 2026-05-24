from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


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

