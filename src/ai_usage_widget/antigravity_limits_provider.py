from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List

from .limits import LimitContractError, LimitWindow, parse_limit_window

#: 按 window_duration_minutes 或 reset 间隔推断窗口类别的容差（分钟）。
#: week ~= 10080 分钟（7 天），session ~= 300 分钟（5 小时）。真实数据有抖动
#: （提前/延后几分钟核对），留出容差但不越界到会与另一类混淆的范围。
_WEEK_DURATION_RANGE_MINUTES = (9000, 11500)
_SESSION_DURATION_RANGE_MINUTES = (200, 400)


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
        _limits_container(status_payload, observed_at=observed_at),
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
        _limits_container(config_payload, observed_at=observed_at),
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
        else:
            return parse_antigravity_user_status(user_status_payload)

        return parse_antigravity_command_model_configs(self.command_model_configs_reader())


def _parse_windows(container: Any, *, observed_at: str, source_type: str) -> List[LimitWindow]:
    items = _window_items(container)
    windows: List[LimitWindow] = []
    for window, window_payload in items:
        # #182：一个窗口字段缺失（例如没有 reset_at）不该让整批解析全炸——
        # 之前任何单个窗口出错都会冒泡到 collect()，被 limits_runtime 兜底成
        # 单条 window=unknown/provider_failed，哪怕另一个窗口的数据完整可信。
        # 这里按窗口隔离故障：跳过解析失败的那一个，保留其它能解析出来的。
        try:
            windows.append(
                _parse_window(
                    window=window,
                    window_payload=window_payload,
                    observed_at=observed_at,
                    source_type=source_type,
                )
            )
        except LimitContractError:
            continue
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


def _limits_container(payload: Dict[str, Any], *, observed_at: str = "") -> Any:
    for name in ("limits", "windows", "quota_windows", "quotaWindows"):
        if name in payload:
            return payload[name]

    # 1. RetrieveUserQuotaSummary structure: response.groups or groups
    res_obj = payload.get("response") if isinstance(payload.get("response"), dict) else payload
    groups = res_obj.get("groups") if isinstance(res_obj, dict) else None
    if isinstance(groups, list) and groups:
        gemini_group = next(
            (g for g in groups if isinstance(g, dict) and "gemini" in str(g.get("displayName", "")).lower()),
            None
        )
        target_group = gemini_group if gemini_group is not None else groups[0]
        if isinstance(target_group, dict) and isinstance(target_group.get("buckets"), list):
            res_windows: Dict[str, Any] = {}
            for b in target_group["buckets"]:
                if not isinstance(b, dict):
                    continue
                rem_frac = b.get("remainingFraction", b.get("remaining_fraction"))
                rem_pct = b.get("remainingPercent", b.get("remaining_percent"))
                if rem_frac is None and rem_pct is not None:
                    rem_frac = float(rem_pct) / 100.0
                if rem_frac is None:
                    # 没有可信的剩余量字段，跟着猜类别毫无意义——丢掉这个桶。
                    continue
                reset_time = b.get("resetTime") or b.get("reset_time") or b.get("resetAt") or b.get("resetsAt")
                duration_mins = b.get("windowDurationMins") or b.get("window_duration_minutes")
                category = _classify_bucket_window(b, reset_time=reset_time, duration_mins=duration_mins, observed_at=observed_at)
                if category is None:
                    # #182：假设——TZ 上实际返回的桶标识可能不含 week/session 关键词
                    # （例如纯 UUID）。无法从关键词、时长或 reset 间隔任何一路识别出
                    # 类别时，不伪造一个——直接丢弃这个桶，保留组里其它能识别的。
                    continue
                res_windows[category] = {
                    "remainingFraction": rem_frac,
                    "resetAt": reset_time,
                    "windowDurationMins": duration_mins or (10080 if category == "week" else 300),
                }
            if res_windows:
                ordered_windows = {}
                for k in ("session", "day", "week", "month"):
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


def _classify_bucket_window(
    bucket: Dict[str, Any],
    *,
    reset_time: Any,
    duration_mins: Any,
    observed_at: str,
) -> str | None:
    """把一个 quota bucket 归类成 "week" 或 "session"，识别不出就返回 None（不猜）。

    三路依次尝试，任意一路命中即返回：
    1. 关键词——文本字段（window / bucketId / displayName / description）里出现
       week/weekly 或 5h/hour/session。
    2. 时长——windowDurationMins 落在 ~7 天或 ~5 小时的范围内。
    3. reset 间隔——观测时刻到 resetTime 的间隔落在同样的范围内（有些真实响应
       不带 window 标识也不带时长字段，只有 resetTime）。
    """
    text_parts: List[str] = []
    for key in ("window", "bucketId", "bucket_id", "displayName", "display_name", "description"):
        value = bucket.get(key)
        if isinstance(value, str):
            text_parts.append(value.lower())
    text = " ".join(text_parts)
    if "week" in text:
        return "week"
    if "5h" in text or "hour" in text or "session" in text:
        return "session"

    if isinstance(duration_mins, (int, float)) and not isinstance(duration_mins, bool):
        if _WEEK_DURATION_RANGE_MINUTES[0] <= duration_mins <= _WEEK_DURATION_RANGE_MINUTES[1]:
            return "week"
        if _SESSION_DURATION_RANGE_MINUTES[0] <= duration_mins <= _SESSION_DURATION_RANGE_MINUTES[1]:
            return "session"

    if isinstance(reset_time, str) and reset_time.strip() and observed_at:
        delta_minutes = _minutes_between(observed_at, reset_time)
        if delta_minutes is not None:
            if _WEEK_DURATION_RANGE_MINUTES[0] <= delta_minutes <= _WEEK_DURATION_RANGE_MINUTES[1]:
                return "week"
            if _SESSION_DURATION_RANGE_MINUTES[0] <= delta_minutes <= _SESSION_DURATION_RANGE_MINUTES[1]:
                return "session"

    return None


def _minutes_between(start: str, end: str) -> float | None:
    try:
        start_time = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    if (start_time.tzinfo is None) != (end_time.tzinfo is None):
        return None
    return (end_time - start_time).total_seconds() / 60.0


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


def live_language_server_status_reader(timeout: float = 2.0) -> Dict[str, Any]:
    import json
    import ssl
    import subprocess
    import urllib.request
    from datetime import datetime, timezone as dt_timezone

    try:
        ps_out = subprocess.check_output(["ps", "aux"], text=True, stderr=subprocess.DEVNULL)
    except Exception as exc:
        raise AntigravityProviderError("provider_unavailable", f"failed to check processes: {exc}")

    csrf_token = None
    target_pid = None
    for line in ps_out.splitlines():
        if "language_server" in line and "--csrf_token" in line:
            parts = line.split()
            for i, p in enumerate(parts):
                if p == "--csrf_token" and i + 1 < len(parts):
                    csrf_token = parts[i + 1]
                elif p.startswith("--csrf_token="):
                    csrf_token = p.split("=", 1)[1]
            if len(parts) >= 2 and parts[1].isdigit():
                target_pid = int(parts[1])
            break

    if not csrf_token or not target_pid:
        raise AntigravityProviderError("provider_unavailable", "Antigravity language server process is not running")

    # Find listening ports for PID
    ports = []
    try:
        lsof_out = subprocess.check_output(
            ["lsof", "-a", "-nP", "-p", str(target_pid), "-iTCP", "-sTCP:LISTEN"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        for line in lsof_out.splitlines():
            # Format: ... TCP 127.0.0.1:58435 (LISTEN) or TCP *:58435 (LISTEN)
            parts = line.split()
            for part in parts:
                if ":" in part and "(" not in part:
                    port_str = part.rsplit(":", 1)[-1]
                    if port_str.isdigit():
                        p = int(port_str)
                        if p not in ports:
                            ports.append(p)
    except Exception:
        pass

    if not ports:
        raise AntigravityProviderError("provider_unavailable", f"no listening ports found for language_server PID {target_pid}")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    last_error = None
    endpoints = [
        "/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary",
        "/exa.language_server_pb.LanguageServerService/GetUserStatus",
    ]
    for port in ports:
        for scheme in ("https", "http"):
            for endpoint in endpoints:
                url = f"{scheme}://127.0.0.1:{port}{endpoint}"
                req = urllib.request.Request(
                    url,
                    data=b"{}",
                    headers={
                        "Content-Type": "application/json",
                        "x-codeium-csrf-token": csrf_token,
                    },
                    method="POST",
                )
                try:
                    with urllib.request.urlopen(req, context=ctx if scheme == "https" else None, timeout=timeout) as resp:
                        if resp.status == 200:
                            payload = json.loads(resp.read().decode("utf-8"))
                            observed_at = datetime.now(dt_timezone.utc).astimezone().isoformat()
                            payload["observed_at"] = observed_at
                            return payload
                except Exception as exc:
                    last_error = exc
                    continue

    raise AntigravityProviderError("provider_unavailable", f"unable to connect to Antigravity language_server RPC: {last_error}")
