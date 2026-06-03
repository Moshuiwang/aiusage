from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


class ConfigError(ValueError):
    pass


SENSITIVE_FIELD_FRAGMENTS = ("token", "secret", "password", "api_key", "apikey")


@dataclass(frozen=True)
class LimitsProviderConfig:
    provider: str
    enabled: bool = True
    auth_file: str | None = None
    usage_url: str | None = None
    codex_rpc: bool = False
    codex_rpc_sock: str | None = None
    claude_cli: bool = False


@dataclass(frozen=True)
class LimitsConfig:
    timezone: str
    sqlite_path: str
    latest_path: str
    providers: list[LimitsProviderConfig]

    @property
    def enabled_providers(self) -> list[LimitsProviderConfig]:
        return [provider for provider in self.providers if provider.enabled]


def load_limits_config(path: str) -> LimitsConfig:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return parse_limits_config(payload)


def parse_limits_config(payload: Dict[str, Any]) -> LimitsConfig:
    if not isinstance(payload, dict):
        raise ConfigError("limits config must be a JSON object")
    _reject_sensitive_fields(payload)

    timezone = _string(payload, "timezone", required=True) or "Asia/Shanghai"
    sqlite_path = _string(payload, "sqlite", required=False) or "data/usage.sqlite"
    latest_path = _string(payload, "latest", required=False) or "data/latest.json"

    providers_payload = payload.get("providers")
    if not isinstance(providers_payload, list):
        raise ConfigError("limits config providers must be a list")

    providers = [_parse_provider(item) for item in providers_payload]
    return LimitsConfig(
        timezone=timezone,
        sqlite_path=sqlite_path,
        latest_path=latest_path,
        providers=providers,
    )


def _parse_provider(payload: Any) -> LimitsProviderConfig:
    if not isinstance(payload, dict):
        raise ConfigError("limits provider config must be an object")
    _reject_sensitive_fields(payload)

    provider = _string(payload, "provider", required=True)
    enabled = _bool(payload, "enabled", default=True)
    auth_file = _string(payload, "auth_file", required=False)
    usage_url = _string(payload, "usage_url", required=False)

    if provider == "codex":
        codex_rpc = _bool(payload, "rpc", default=False)
        codex_rpc_sock = _string(payload, "rpc_sock", required=False)
        if enabled and not auth_file and not codex_rpc:
            raise ConfigError("codex limits provider requires auth_file or rpc=true")
        return LimitsProviderConfig(
            provider=provider,
            enabled=enabled,
            auth_file=auth_file,
            codex_rpc=codex_rpc,
            codex_rpc_sock=codex_rpc_sock,
        )

    if provider == "claude":
        claude_cli = _bool(payload, "cli", default=False)
        has_oauth_pair = bool(auth_file and usage_url)
        if enabled and not has_oauth_pair and not claude_cli:
            raise ConfigError("claude limits provider requires auth_file+usage_url or cli=true")
        return LimitsProviderConfig(
            provider=provider,
            enabled=enabled,
            auth_file=auth_file,
            usage_url=usage_url,
            claude_cli=claude_cli,
        )

    raise ConfigError(f"unsupported limits provider: {provider}")


def _reject_sensitive_fields(payload: Dict[str, Any]) -> None:
    for key in payload:
        normalized = str(key).lower().replace("-", "_")
        if any(fragment in normalized for fragment in SENSITIVE_FIELD_FRAGMENTS):
            raise ConfigError("limits config must not contain inline secrets")


def _string(payload: Dict[str, Any], key: str, *, required: bool) -> str | None:
    value = payload.get(key)
    if value is None:
        if required:
            raise ConfigError(f"limits config {key} is required")
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"limits config {key} must be a non-empty string")
    return value.strip()


def _bool(payload: Dict[str, Any], key: str, *, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"limits config {key} must be a boolean")
    return value
