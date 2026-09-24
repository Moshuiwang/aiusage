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
    source_id: str | None = None
    auth_file: str | None = None
    usage_url: str | None = None
    codex_rpc: bool = False
    codex_rpc_sock: str | None = None
    claude_cli: bool = False
    env: dict[str, str] | None = None


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
    _reject_duplicate_runtime_ids(providers)
    return LimitsConfig(
        timezone=timezone,
        sqlite_path=sqlite_path,
        latest_path=latest_path,
        providers=providers,
    )


def summarize_limits_config(config: LimitsConfig) -> Dict[str, Any]:
    return {
        "timezone": config.timezone,
        "sqlite": config.sqlite_path,
        "latest": config.latest_path,
        "providers": [_summarize_provider(provider) for provider in config.enabled_providers],
    }


def _summarize_provider(provider: LimitsProviderConfig) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "provider": provider.provider,
        "source_id": provider.source_id or provider.provider,
        "enabled": provider.enabled,
        "has_auth_file": bool(provider.auth_file),
        "has_env": bool(provider.env),
        "env_keys": sorted((provider.env or {}).keys()),
    }
    if provider.provider == "codex":
        summary.update(
            {
                "codex_rpc": provider.codex_rpc,
                "has_codex_rpc_sock": bool(provider.codex_rpc_sock),
            }
        )
    if provider.provider == "claude":
        summary.update(
            {
                "has_usage_url": bool(provider.usage_url),
                "claude_cli": provider.claude_cli,
            }
        )
    return summary


def _parse_provider(payload: Any) -> LimitsProviderConfig:
    if not isinstance(payload, dict):
        raise ConfigError("limits provider config must be an object")
    _reject_sensitive_fields(payload)

    provider = _string(payload, "provider", required=True)
    enabled = _bool(payload, "enabled", default=True)
    source_id = _string(payload, "source_id", required=False)
    auth_file = _string(payload, "auth_file", required=False)
    usage_url = _string(payload, "usage_url", required=False)
    env = _env_map(payload, "env")

    if provider == "codex":
        codex_rpc = _bool(payload, "rpc", default=False)
        codex_rpc_sock = _string(payload, "rpc_sock", required=False)
        if enabled and not auth_file and not codex_rpc:
            raise ConfigError("codex limits provider requires auth_file or rpc=true")
        return LimitsProviderConfig(
            provider=provider,
            enabled=enabled,
            source_id=source_id,
            auth_file=auth_file,
            codex_rpc=codex_rpc,
            codex_rpc_sock=codex_rpc_sock,
            env=env,
        )

    if provider == "claude":
        claude_cli = _bool(payload, "cli", default=False)
        has_oauth_pair = bool(auth_file and usage_url)
        if enabled and not has_oauth_pair and not claude_cli:
            raise ConfigError("claude limits provider requires auth_file+usage_url or cli=true")
        return LimitsProviderConfig(
            provider=provider,
            enabled=enabled,
            source_id=source_id,
            auth_file=auth_file,
            usage_url=usage_url,
            claude_cli=claude_cli,
            env=env,
        )

    if provider == "antigravity":
        return LimitsProviderConfig(
            provider=provider,
            enabled=enabled,
            source_id=source_id,
            env=env,
        )

    raise ConfigError(f"unsupported limits provider: {provider}")


def runtime_id(provider: LimitsProviderConfig) -> str:
    """采集运行时用来给提供方分槽位的键。缺省时回落到 provider 名。"""
    return provider.source_id or provider.provider


def _reject_duplicate_runtime_ids(providers: List[LimitsProviderConfig]) -> None:
    """启用的提供方之间不许共用运行时标识（#144）。

    运行时以这个标识为字典键装配提供方，重名会让后加载的那个**静默覆盖**前者：
    任务照常报成功，实际却重复采了同一个提供方，另一个提供方一条额度都没写。
    这种失败没有任何声响，只能在配置校验阶段挡住。
    """
    seen: Dict[str, str] = {}
    for provider in providers:
        if not provider.enabled:
            # 停用的提供方根本不进运行时映射，谈不上互相覆盖。
            continue
        key = runtime_id(provider)
        if key in seen:
            raise ConfigError(
                f"limits config duplicate runtime id {key!r}: "
                f"provider {seen[key]!r} and {provider.provider!r} would collide; "
                "give each enabled provider its own source_id"
            )
        seen[key] = provider.provider


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


def _env_map(payload: Dict[str, Any], key: str) -> dict[str, str]:
    value = payload.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"limits config {key} must be an object")
    result: dict[str, str] = {}
    for env_key, env_value in value.items():
        if not isinstance(env_key, str) or not env_key.strip():
            raise ConfigError("limits config env keys must be non-empty strings")
        normalized = env_key.lower().replace("-", "_")
        if any(fragment in normalized for fragment in SENSITIVE_FIELD_FRAGMENTS):
            raise ConfigError("limits config env must not contain inline secrets")
        if not isinstance(env_value, str) or not env_value.strip():
            raise ConfigError("limits config env values must be non-empty strings")
        result[env_key.strip()] = env_value.strip()
    return result
