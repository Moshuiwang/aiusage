from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import subprocess
import urllib.request
from datetime import datetime, timezone
from http.client import HTTPException
from typing import Any, Callable, Dict, Iterator, List

from .limits import LimitContractError, LimitWindow, parse_limit_window


class AntigravityProviderError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


USER_STATUS_FALLBACK_ERRORS = {"missing_credentials", "unsupported", "provider_unavailable"}


def parse_antigravity_user_status(payload: Dict[str, Any]) -> List[LimitWindow]:
    if not isinstance(payload, dict):
        raise LimitContractError("antigravity_user_status_schema_invalid", "Antigravity user status payload must be an object")

    observed_at = _string_field(payload, "observed_at")
    if _has_any(payload, "response", "groups"):
        status_payload = payload
    else:
        status_payload = _object_field(payload, "user_status", "userStatus", "status")
    return _parse_windows(
        _limits_container(status_payload),
        observed_at=observed_at,
        source_type="language_server",
    )


def parse_antigravity_command_model_configs(payload: Dict[str, Any]) -> List[LimitWindow]:
    if not isinstance(payload, dict):
        raise LimitContractError(
            "antigravity_command_model_configs_schema_invalid",
            "Antigravity command model configs payload must be an object",
        )

    observed_at = _string_field(payload, "observed_at")
    config_payload = _object_field(payload, "command_model_configs", "commandModelConfigs", "configs")
    return _parse_windows(
        _limits_container(config_payload),
        observed_at=observed_at,
        source_type="language_server_config",
    )


class AntigravityLimitsProvider:
    def __init__(
        self,
        user_status_reader: Callable[[], Dict[str, Any]] | None = None,
        command_model_configs_reader: Callable[[], Dict[str, Any]] | None = None,
    ) -> None:
        self.user_status_reader = user_status_reader or live_language_server_status_reader
        self.command_model_configs_reader = command_model_configs_reader or _unsupported_command_model_configs_reader

    def collect(self) -> List[LimitWindow]:
        try:
            user_status_payload = self.user_status_reader()
        except AntigravityProviderError as exc:
            if exc.error_type not in USER_STATUS_FALLBACK_ERRORS:
                raise
            user_status_error = exc
        else:
            return parse_antigravity_user_status(user_status_payload)

        try:
            config_payload = self.command_model_configs_reader()
        except AntigravityProviderError:
            if self.command_model_configs_reader is _unsupported_command_model_configs_reader:
                raise user_status_error
            raise
        return parse_antigravity_command_model_configs(config_payload)


def _parse_windows(container: Any, *, observed_at: str, source_type: str) -> List[LimitWindow]:
    items = _window_items(container)
    windows = [
        _parse_window(
            window=window,
            window_payload=window_payload,
            observed_at=observed_at,
            source_type=source_type,
        )
        for window, window_payload in items
    ]
    if not windows:
        raise LimitContractError("limit_schema_invalid", "Antigravity limits payload must include at least one window")
    return windows


def _parse_window(
    *,
    window: str,
    window_payload: Dict[str, Any],
    observed_at: str,
    source_type: str,
) -> LimitWindow:
    remaining_percent = _remaining_percent(window_payload)
    used_percent = 100.0 - remaining_percent

    return parse_limit_window(
        {
            "provider": "antigravity",
            "window": window,
            "used_percent": used_percent,
            "remaining_percent": remaining_percent,
            "reset_at": _string_field(window_payload, "reset_at", "resetAt", "resets_at", "resetsAt"),
            "window_duration_minutes": _int_field(window_payload, "window_duration_minutes", "windowDurationMins"),
            "observed_at": observed_at,
            "source_type": source_type,
            "confidence": _optional_string_field(window_payload, "confidence", default="observed"),
            "status": _optional_string_field(window_payload, "status", default="ok"),
        }
    )


def _limits_container(payload: Dict[str, Any]) -> Any:
    for name in ("limits", "windows", "quota_windows", "quotaWindows"):
        if name in payload:
            return payload[name]

    # 1. RetrieveUserQuotaSummary structure: response.groups or groups
    res_obj = payload.get("response") if isinstance(payload.get("response"), dict) else payload
    groups = res_obj.get("groups") if isinstance(res_obj, dict) else None
    if isinstance(groups, list) and groups:
        valid_groups = [g for g in groups if isinstance(g, dict) and isinstance(g.get("buckets"), list)]
        res_windows: Dict[str, Any] = {}
        for group in valid_groups:
            prefix = _group_pool_prefix(group, total_groups=len(valid_groups))
            for b in group["buckets"]:
                if not isinstance(b, dict):
                    continue
                win_id = str(b.get("window") or b.get("bucketId") or "").lower()
                rem_frac = b.get("remainingFraction", b.get("remaining_fraction"))
                rem_pct = b.get("remainingPercent", b.get("remaining_percent"))
                if rem_frac is None and rem_pct is not None:
                    rem_frac = float(rem_pct) / 100.0
                reset_time = b.get("resetTime") or b.get("reset_time") or b.get("resetAt") or b.get("resetsAt")
                if "week" in win_id:
                    res_windows[f"{prefix}week"] = {
                        "remainingFraction": rem_frac,
                        "resetAt": reset_time,
                        "windowDurationMins": 10080,
                    }
                elif "5h" in win_id or "session" in win_id or "hour" in win_id:
                    res_windows[f"{prefix}session"] = {
                        "remainingFraction": rem_frac,
                        "resetAt": reset_time,
                        "windowDurationMins": 300,
                    }
        if res_windows:
            ordered_windows = {}
            preferred_order = (
                "session",
                "day",
                "week",
                "month",
                "claude_gpt_session",
                "claude_gpt_week",
                "argon_session",
                "argon_week",
            )
            for k in preferred_order:
                if k in res_windows:
                    ordered_windows[k] = res_windows[k]
            for k, v in res_windows.items():
                if k not in ordered_windows:
                    ordered_windows[k] = v
            return ordered_windows

    # 2. Fallback to GetUserStatus cascadeModelConfigData
    for name in ("cascadeModelConfigData", "cascade_model_config_data"):
        if name in payload and isinstance(payload[name], dict):
            configs = payload[name].get("clientModelConfigs") or payload[name].get("client_model_configs") or []
            gemini_config = next(
                (c for c in configs if isinstance(c, dict) and "gemini" in str(c.get("label", "")).lower()),
                None
            )
            target_configs = [gemini_config] if gemini_config else configs
            for item in target_configs:
                if not isinstance(item, dict):
                    continue
                quota = item.get("quotaInfo") or item.get("quota_info")
                if isinstance(quota, dict) and ("remainingFraction" in quota or "remainingPercent" in quota or "remaining_fraction" in quota):
                    rem_frac = quota.get("remainingFraction", quota.get("remaining_fraction"))
                    rem_pct = quota.get("remainingPercent", quota.get("remaining_percent"))
                    if rem_frac is None and rem_pct is not None:
                        rem_frac = float(rem_pct) / 100.0
                    reset_time = (
                        quota.get("resetTime")
                        or quota.get("reset_time")
                        or quota.get("resetAt")
                        or quota.get("resetsAt")
                    )
                    return {
                        "session": {
                            "remainingFraction": rem_frac,
                            "resetAt": reset_time,
                            "windowDurationMins": quota.get("windowDurationMins", quota.get("window_duration_minutes", 300)),
                        }
                    }

    raise LimitContractError("limit_schema_invalid", "Antigravity payload must include limits or windows")


def _group_pool_prefix(group: Dict[str, Any], *, total_groups: int) -> str:
    display_name = str(group.get("displayName", "")).strip().lower()
    buckets = group.get("buckets") if isinstance(group.get("buckets"), list) else []
    bucket_ids = [str(b.get("bucketId", "")).strip().lower() for b in buckets if isinstance(b, dict)]
    if "argon" in display_name or any("argon" in bid for bid in bucket_ids):
        return "argon_"
    if "claude" in display_name or "gpt" in display_name or any(bid.startswith("3p") for bid in bucket_ids):
        return "claude_gpt_"
    if "gemini" in display_name or any(bid.startswith("gemini") for bid in bucket_ids) or total_groups == 1:
        return ""
    slug = "".join(ch if ch.isalnum() else "_" for ch in display_name).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return f"{slug}_" if slug else ""


def _window_items(container: Any) -> List[tuple[str, Dict[str, Any]]]:
    if isinstance(container, dict):
        items = []
        for window, payload in container.items():
            if not isinstance(window, str) or not window.strip():
                raise LimitContractError("limit_schema_invalid", "Antigravity window names must be non-empty strings")
            if not isinstance(payload, dict):
                raise LimitContractError("limit_schema_invalid", f"Antigravity {window} window must be an object")
            items.append((window.strip(), payload))
        return items

    if isinstance(container, list):
        items = []
        for payload in container:
            if not isinstance(payload, dict):
                raise LimitContractError("limit_schema_invalid", "Antigravity window entries must be objects")
            items.append((_string_field(payload, "window"), payload))
        return items

    raise LimitContractError("limit_schema_invalid", "Antigravity limits payload must be an object or list")


def _remaining_percent(payload: Dict[str, Any]) -> float:
    if _has_any(payload, "remaining_percent", "remainingPercent"):
        value = _number_field(payload, "remaining_percent", "remainingPercent")
        if value < 0 or value > 100:
            raise LimitContractError("limit_schema_invalid", "remaining percent must be between 0 and 100")
        return value

    value = _number_field(payload, "remaining_fraction", "remainingFraction")
    if value < 0 or value > 1:
        raise LimitContractError("limit_schema_invalid", "remaining fraction must be between 0 and 1")
    return value * 100.0


def _object_field(payload: Dict[str, Any], *names: str) -> Dict[str, Any]:
    value = _first_present(payload, *names)
    if not isinstance(value, dict):
        raise LimitContractError("limit_schema_invalid", f"{'/'.join(names)} must be an object")
    return value


def _string_field(payload: Dict[str, Any], *names: str) -> str:
    value = _first_present(payload, *names)
    if not isinstance(value, str) or not value.strip():
        raise LimitContractError("limit_schema_invalid", f"{'/'.join(names)} must be a non-empty string")
    return value.strip()


def _optional_string_field(payload: Dict[str, Any], name: str, default: str) -> str:
    value = payload.get(name, default)
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise LimitContractError("limit_schema_invalid", f"{name} must be a string")
    return value.strip()


def _number_field(payload: Dict[str, Any], *names: str) -> float:
    value = _first_present(payload, *names)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LimitContractError("limit_schema_invalid", f"{'/'.join(names)} must be a number")
    return float(value)


def _int_field(payload: Dict[str, Any], *names: str) -> int:
    value = _first_present(payload, *names)
    if isinstance(value, bool) or not isinstance(value, int):
        raise LimitContractError("limit_schema_invalid", f"{'/'.join(names)} must be an integer")
    return value


def _first_present(payload: Dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload:
            return payload[name]
    raise LimitContractError("limit_schema_invalid", f"missing required limit field: {', '.join(names)}")


def _has_any(payload: Dict[str, Any], *names: str) -> bool:
    return any(name in payload for name in names)


def _unsupported_user_status_reader() -> Dict[str, Any]:
    raise AntigravityProviderError("unsupported", "Antigravity GetUserStatus reader is not configured")


def _unsupported_command_model_configs_reader() -> Dict[str, Any]:
    raise AntigravityProviderError("unsupported", "Antigravity GetCommandModelConfigs reader is not configured")


def _language_server_candidates(timeout: float) -> Iterator[tuple[int, str]]:
    try:
        ps_out = subprocess.check_output(
            ["ps", "-ww", "-U", str(os.getuid()), "-o", "pid=,command="],
            text=True, stderr=subprocess.DEVNULL, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        raise AntigravityProviderError("provider_unavailable", "unable to check Antigravity processes") from None
    for line in ps_out.splitlines():
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or not fields[0].isdigit():
            continue
        pid, command = fields
        executable = command.partition(" --")[0]
        if not re.search(r"(?:^|/)language_server[^\s/]*(?:\s|$)", executable):
            continue
        token = re.search(r"(?:^|\s)--csrf_token(?:=|\s+)(?!-)([^\s]+)", command)
        if token:
            yield int(pid), token.group(1)


def _listening_ports(pid: int, timeout: float) -> list[int]:
    lsof_bin = shutil.which("lsof") or "/usr/sbin/lsof"
    try:
        lsof_out = subprocess.check_output(
            [lsof_bin, "-a", "-nP", "-p", str(pid), "-i4TCP", "-sTCP:LISTEN", "-Fn"],
            text=True, stderr=subprocess.DEVNULL, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    ports: list[int] = []
    for line in lsof_out.splitlines():
        address, separator, port = line.partition(":")
        if separator and address in {"n127.0.0.1", "n*", "n0.0.0.0"} and port.isdigit():
            number = int(port)
            if 0 < number <= 65535 and number not in ports:
                ports.append(number)
    return ports


def language_server_readiness(timeout: float = 2.0) -> str:
    try:
        found = False
        for pid, _ in _language_server_candidates(timeout):
            found = True
            if _listening_ports(pid, timeout):
                return "ok"
        return "no_listening_port" if found else "not_running"
    except AntigravityProviderError:
        return "process_check_failed"


class _NoLoopbackRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def live_language_server_status_reader(timeout: float = 2.0) -> Dict[str, Any]:
    # The local language server can present a self-signed certificate. The CSRF
    # key must stay on the PID's IPv4 loopback listener, even with proxy settings
    # or a redirect in the response.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoLoopbackRedirect(), urllib.request.HTTPSHandler(context=ctx),
    )
    endpoints = (
        "/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary",
        "/exa.language_server_pb.LanguageServerService/GetUserStatus",
    )
    invalid_payload = False
    for pid, csrf_token in _language_server_candidates(timeout):
        for port in _listening_ports(pid, timeout):
            for scheme in ("https", "http"):
                for endpoint in endpoints:
                    request = urllib.request.Request(
                        f"{scheme}://127.0.0.1:{port}{endpoint}",
                        data=b"{}",
                        headers={"Content-Type": "application/json", "x-codeium-csrf-token": csrf_token},
                        method="POST",
                    )
                    try:
                        with opener.open(request, timeout=timeout) as response:
                            if response.status != 200:
                                continue
                            payload = json.loads(response.read())
                        if not isinstance(payload, dict):
                            invalid_payload = True
                            continue
                        payload["observed_at"] = datetime.now(timezone.utc).isoformat()
                        parse_antigravity_user_status(payload)
                        return payload
                    except ValueError:
                        invalid_payload = True
                    except (OSError, HTTPException):
                        continue

    if invalid_payload:
        raise AntigravityProviderError("limit_schema_invalid", "Antigravity returned no valid quota windows")
    raise AntigravityProviderError("provider_unavailable", "unable to contact the Antigravity language server")
