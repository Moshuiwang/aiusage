from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .limits_config import ConfigError, LimitsProviderConfig, load_limits_config


CommandResolver = Callable[[str], Optional[str]]


def run_limits_doctor(
    config_path: str | None,
    *,
    command_resolver: CommandResolver | None = None,
) -> Dict[str, Any]:
    resolver = command_resolver or shutil.which
    if not config_path:
        return {
            "success": False,
            "doctor": True,
            "checks": [_check("limits_config", "missing", ok=False, configured=False)],
            "providers": [],
        }

    try:
        config = load_limits_config(config_path)
    except (OSError, ConfigError, ValueError) as exc:
        return {
            "success": False,
            "doctor": True,
            "checks": [
                {
                    **_check("limits_config", "invalid", ok=False, configured=True),
                    "error_type": exc.__class__.__name__,
                }
            ],
            "providers": [],
        }

    providers = [_doctor_provider(provider, resolver) for provider in config.enabled_providers]
    success = bool(providers) and all(provider["ready"] for provider in providers)
    return {
        "success": success,
        "doctor": True,
        "checks": [_check("limits_config", "ok", ok=True, configured=True)],
        "timezone": config.timezone,
        "sqlite_configured": bool(config.sqlite_path),
        "latest_configured": bool(config.latest_path),
        "providers": providers,
    }


def _doctor_provider(provider: LimitsProviderConfig, resolver: CommandResolver) -> Dict[str, Any]:
    if provider.provider == "codex":
        return _doctor_codex(provider, resolver)
    if provider.provider == "claude":
        return _doctor_claude(provider, resolver)
    return {
        "provider": provider.provider,
        "ready": False,
        "checks": [_check(f"{provider.provider}.provider", "unsupported", ok=False, configured=True)],
    }


def _doctor_codex(provider: LimitsProviderConfig, resolver: CommandResolver) -> Dict[str, Any]:
    checks = []
    auth_check = _file_check("codex.auth_file", provider.auth_file)
    checks.append(auth_check)

    rpc_command_check = _command_check("codex.rpc_command", "codex", resolver) if provider.codex_rpc else _check(
        "codex.rpc_command",
        "not_configured",
        ok=False,
        configured=False,
    )
    checks.append(rpc_command_check)

    rpc_socket_check = _file_check("codex.rpc_socket", provider.codex_rpc_sock) if provider.codex_rpc_sock else _check(
        "codex.rpc_socket",
        "not_configured",
        ok=True,
        configured=False,
    )
    checks.append(rpc_socket_check)

    auth_ready = auth_check["ok"]
    rpc_ready = provider.codex_rpc and rpc_command_check["ok"] and rpc_socket_check["ok"]
    return {
        "provider": "codex",
        "source_id": provider.source_id or "codex",
        "has_env": bool(provider.env),
        "env_keys": sorted((provider.env or {}).keys()),
        "ready": bool(auth_ready or rpc_ready),
        "checks": checks,
    }


def _doctor_claude(provider: LimitsProviderConfig, resolver: CommandResolver) -> Dict[str, Any]:
    checks = []
    auth_check = _file_check("claude.auth_file", provider.auth_file)
    checks.append(auth_check)
    usage_url_check = _check(
        "claude.usage_url",
        "ok" if provider.usage_url else "not_configured",
        ok=bool(provider.usage_url),
        configured=bool(provider.usage_url),
    )
    checks.append(usage_url_check)
    cli_check = _command_check("claude.cli_command", "claude", resolver) if provider.claude_cli else _check(
        "claude.cli_command",
        "not_configured",
        ok=False,
        configured=False,
    )
    checks.append(cli_check)

    oauth_ready = auth_check["ok"] and usage_url_check["ok"]
    cli_ready = provider.claude_cli and cli_check["ok"]
    return {
        "provider": "claude",
        "source_id": provider.source_id or "claude",
        "has_env": bool(provider.env),
        "env_keys": sorted((provider.env or {}).keys()),
        "ready": bool(oauth_ready or cli_ready),
        "checks": checks,
    }


def _file_check(name: str, path: str | None) -> Dict[str, Any]:
    if not path:
        return _check(name, "not_configured", ok=False, configured=False)
    candidate = Path(path)
    if not candidate.exists():
        return _check(name, "missing", ok=False, configured=True)
    if not os.access(candidate, os.R_OK):
        return _check(name, "unreadable", ok=False, configured=True)
    return _check(name, "ok", ok=True, configured=True)


def _command_check(name: str, command: str, resolver: CommandResolver) -> Dict[str, Any]:
    resolved = resolver(command)
    return _check(name, "ok" if resolved else "missing", ok=bool(resolved), configured=True)


def _check(name: str, status: str, *, ok: bool, configured: bool) -> Dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "ok": ok,
        "configured": configured,
    }
