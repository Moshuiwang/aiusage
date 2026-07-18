from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from .limits import LimitContractError, LimitWindow, parse_limit_window


class ClaudeProviderError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


OAUTH_FALLBACK_ERRORS = {"missing_credentials", "unauthorized"}

# Old format: "5h window: 68% used, resets at 2026-06-03T15:30:00+08:00, duration 300 minutes"
_CLI_WINDOW_PATTERNS = (
    ("session", re.compile(r"5h\s+window:\s*([0-9]+(?:\.[0-9]+)?)%\s+used,\s*resets\s+at\s*([^,\s]+),\s*duration\s+([0-9]+)\s+minutes", re.IGNORECASE)),
    ("week", re.compile(r"weekly\s+window:\s*([0-9]+(?:\.[0-9]+)?)%\s+used,\s*resets\s+at\s*([^,\s]+),\s*duration\s+([0-9]+)\s+minutes", re.IGNORECASE)),
)
# New format: "Current session: 35% used · resets Jun 19 at 6:09pm (Asia/Shanghai)"
_CLI_NEW_WINDOW_PATTERNS = (
    ("session", 300, re.compile(
        r"Current\s+session:\s*([0-9]+(?:\.[0-9]+)?)%\s+used\s*[·•]\s*resets\s+"
        r"([A-Za-z]+\s+[0-9]+\s+at\s+[0-9]+(?::[0-9]+)?\s*[ap]m)\s*\([^)]+\)",
        re.IGNORECASE,
    )),
    ("week", 10080, re.compile(
        r"Current\s+week(?:\s+\([^)]+\))?:\s*([0-9]+(?:\.[0-9]+)?)%\s+used\s*[·•]\s*resets\s+"
        r"([A-Za-z]+\s+[0-9]+\s+at\s+[0-9]+(?::[0-9]+)?\s*[ap]m)\s*\([^)]+\)",
        re.IGNORECASE,
    )),
)
_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_CLI_LIMIT_MESSAGE_PATTERN = re.compile(
    r"hit\s+your\s+session\s+limit.*?resets\s+([0-9]{1,2}:[0-9]{2})\s*([ap]m)\s*\(([^)]+)\)",
    re.IGNORECASE,
)


def parse_claude_oauth_usage(payload: Dict[str, Any]) -> List[LimitWindow]:
    if not isinstance(payload, dict):
        raise LimitContractError("claude_oauth_schema_invalid", "Claude OAuth usage payload must be an object")

    if "five_hour" in payload or "seven_day" in payload:
        observed_at = payload.get("observed_at") or _missing_observed_at()
        if not isinstance(observed_at, str) or not observed_at.strip():
            raise LimitContractError("limit_schema_invalid", "observed_at must be a non-empty string")
        windows: List[LimitWindow] = []
        for field, window, duration in (("five_hour", "session", 300), ("seven_day", "week", 10080)):
            window_payload = payload.get(field)
            if window_payload is None:
                continue
            if not isinstance(window_payload, dict):
                raise LimitContractError("limit_schema_invalid", f"{field} must be an object")
            used_percent = _number_field(window_payload, "utilization")
            windows.append(parse_limit_window({
                "provider": "claude",
                "window": window,
                "used_percent": used_percent,
                "remaining_percent": 100.0 - used_percent,
                "reset_at": _string_field(window_payload, "resets_at"),
                "window_duration_minutes": duration,
                "observed_at": observed_at.strip(),
                "source_type": "oauth_usage_api",
                "confidence": "observed",
                "status": "ok",
            }))
        if not windows:
            raise LimitContractError("limit_schema_invalid", "Claude OAuth response contains no verifiable windows")
        return windows

    observed_at = _string_field(payload, "observed_at")
    return [
        _parse_window(
            window_payload=_object_field(payload, "current_session"),
            window="session",
            observed_at=observed_at,
            source_type="oauth_usage_api",
            confidence="observed",
        ),
        _parse_window(
            window_payload=_object_field(payload, "weekly"),
            window="week",
            observed_at=observed_at,
            source_type="oauth_usage_api",
            confidence="observed",
        ),
    ]


def parse_claude_cli_usage(text: str, *, observed_at: str) -> List[LimitWindow]:
    if not isinstance(text, str) or not text.strip():
        raise LimitContractError("claude_cli_schema_invalid", "Claude /usage output must be non-empty text")

    limit_message_windows = _parse_cli_limit_message(text, observed_at=observed_at)
    if limit_message_windows:
        return limit_message_windows

    # Try new format first ("Current session: X% used · resets ...")
    new_format_windows = _parse_cli_new_format(text, observed_at=observed_at)
    if new_format_windows:
        return new_format_windows

    # Fall back to old format ("5h window: X% used, resets at ISO8601, duration N minutes")
    windows: List[LimitWindow] = []
    for window, pattern in _CLI_WINDOW_PATTERNS:
        match = pattern.search(text)
        if match is None:
            raise LimitContractError("claude_cli_schema_invalid", f"missing Claude /usage {window} window")
        used_percent = float(match.group(1))
        windows.append(
            parse_limit_window(
                {
                    "provider": "claude",
                    "window": window,
                    "used_percent": used_percent,
                    "remaining_percent": 100.0 - used_percent,
                    "reset_at": match.group(2),
                    "window_duration_minutes": int(match.group(3)),
                    "observed_at": observed_at,
                    "source_type": "official_cli",
                    "confidence": "observed",
                    "status": "ok",
                }
            )
        )
    return windows


def _parse_cli_new_format(text: str, *, observed_at: str) -> List[LimitWindow]:
    """Parse new-style /usage output: 'Current session: X% used · resets Mon DD at H:MMam (TZ)'"""
    windows: List[LimitWindow] = []
    for window, duration_minutes, pattern in _CLI_NEW_WINDOW_PATTERNS:
        match = pattern.search(text)
        if match is None:
            return []
        used_percent = float(match.group(1))
        reset_at = _parse_human_reset_at(match.group(2), observed_at=observed_at)
        windows.append(
            parse_limit_window(
                {
                    "provider": "claude",
                    "window": window,
                    "used_percent": used_percent,
                    "remaining_percent": 100.0 - used_percent,
                    "reset_at": reset_at,
                    "window_duration_minutes": duration_minutes,
                    "observed_at": observed_at,
                    "source_type": "official_cli",
                    "confidence": "observed",
                    "status": "ok",
                }
            )
        )
    return windows


def _parse_human_reset_at(time_text: str, *, observed_at: str) -> str:
    """Convert 'Jun 19 at 6:09pm' to ISO8601, using observed_at for UTC offset and year context."""
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LimitContractError("claude_cli_schema_invalid", "observed_at must be ISO 8601") from exc

    m = re.match(
        r"([A-Za-z]+)\s+([0-9]+)\s+at\s+([0-9]+)(?::([0-9]+))?\s*(am|pm)",
        time_text.strip(),
        re.IGNORECASE,
    )
    if not m:
        raise LimitContractError("claude_cli_schema_invalid", f"Cannot parse reset time: {time_text!r}")

    month = _MONTH_ABBR.get(m.group(1).lower()[:3])
    if month is None:
        raise LimitContractError("claude_cli_schema_invalid", f"Unknown month: {m.group(1)!r}")
    day = int(m.group(2))
    hour = int(m.group(3))
    minute = int(m.group(4) or "0")
    if m.group(5).lower() == "am":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12

    utc_offset = observed.utcoffset()
    tz = dt_timezone(utc_offset) if utc_offset is not None else dt_timezone.utc
    year = observed.year
    try:
        candidate = datetime(year, month, day, hour, minute, 0, tzinfo=tz)
    except ValueError as exc:
        raise LimitContractError("claude_cli_schema_invalid", f"Invalid date: {time_text!r}") from exc
    if candidate < observed - timedelta(hours=1):
        candidate = datetime(year + 1, month, day, hour, minute, 0, tzinfo=tz)
    return candidate.isoformat()


def _parse_cli_limit_message(text: str, *, observed_at: str) -> List[LimitWindow]:
    match = _CLI_LIMIT_MESSAGE_PATTERN.search(text)
    if match is None:
        return []
    reset_at = _limit_message_reset_at(
        observed_at=observed_at,
        time_text=match.group(1),
        meridiem=match.group(2),
        timezone_name=match.group(3),
    )
    return [
        parse_limit_window(
            {
                "provider": "claude",
                "window": "session",
                "used_percent": 100.0,
                "remaining_percent": 0.0,
                "reset_at": reset_at,
                "window_duration_minutes": 300,
                "observed_at": observed_at,
                "source_type": "official_cli_limit_message",
                "confidence": "observed",
                "status": "ok",
            }
        )
    ]


def _limit_message_reset_at(*, observed_at: str, time_text: str, meridiem: str, timezone_name: str) -> str:
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LimitContractError("claude_cli_schema_invalid", "observed_at must be an ISO 8601 datetime") from exc
    hour_text, minute_text = time_text.split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    marker = meridiem.lower()
    if marker == "am":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12

    candidate = observed.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate < observed:
        candidate += timedelta(days=1)

    # Claude includes the timezone display name in the message. The offset from observed_at is the stable value.
    if not timezone_name.strip():
        raise LimitContractError("claude_cli_schema_invalid", "Claude limit reset timezone is missing")
    return candidate.isoformat()


def parse_claude_active_limits(payload: Dict[str, Any], *, observed_at: str) -> List[LimitWindow]:
    if not isinstance(payload, dict):
        raise LimitContractError("claude_active_limits_schema_invalid", "Claude active limits payload must be an object")
    rate_limits = _object_field(payload, "rate_limits")
    return [
        _parse_active_limit_window(
            window_payload=_object_field(rate_limits, "five_hour"),
            window="session",
            duration_minutes=300,
            observed_at=observed_at,
        ),
        _parse_active_limit_window(
            window_payload=_object_field(rate_limits, "seven_day"),
            window="week",
            duration_minutes=10080,
            observed_at=observed_at,
        ),
    ]


def parse_claude_local_history_estimate(payload: Dict[str, Any]) -> LimitWindow:
    if not isinstance(payload, dict):
        raise LimitContractError("limit_schema_invalid", "Claude local history estimate must be an object")

    used_percent = _number_field(payload, "used_percent")
    return parse_limit_window(
        {
            "provider": "claude",
            "window": _string_field(payload, "window"),
            "used_percent": used_percent,
            "remaining_percent": 100.0 - used_percent,
            "reset_at": _string_field(payload, "reset_at"),
            "window_duration_minutes": int(payload.get("window_duration_minutes", 0)),
            "observed_at": _string_field(payload, "observed_at"),
            "source_type": "local_history_estimate",
            "confidence": "estimated",
            "status": "ok",
        }
    )


class ClaudeLimitsProvider:
    def __init__(
        self,
        oauth_fetcher: Callable[[], Dict[str, Any]] | None = None,
        cli_usage_reader: Callable[[], str] | None = None,
        observed_at_provider: Callable[[], str] | None = None,
    ) -> None:
        self.oauth_fetcher = oauth_fetcher or _missing_oauth_credentials
        self.cli_usage_reader = cli_usage_reader or _unsupported_cli_usage_reader
        self.observed_at_provider = observed_at_provider or _missing_observed_at

    def collect(self) -> List[LimitWindow]:
        try:
            oauth_payload = self.oauth_fetcher()
        except ClaudeProviderError as exc:
            if exc.error_type not in OAUTH_FALLBACK_ERRORS:
                raise
        else:
            return parse_claude_oauth_usage(oauth_payload)

        return parse_claude_cli_usage(self.cli_usage_reader(), observed_at=self.observed_at_provider())


@dataclass(frozen=True)
class ClaudeCommandResult:
    returncode: int
    stdout: str
    stderr: str


class ClaudeSubprocessRunner:
    def run(self, command: list[str], timeout: float, env: dict[str, str] | None = None) -> ClaudeCommandResult:
        child_env = os.environ.copy()
        if env:
            child_env.update(env)
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=child_env,
        )
        return ClaudeCommandResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)


class ClaudeCliUsageProvider:
    def __init__(
        self,
        *,
        command: list[str] | None = None,
        limit_probe_command: list[str] | None = None,
        env: dict[str, str] | None = None,
        runner: ClaudeSubprocessRunner | None = None,
        timeout: float = 20.0,
        observed_at_provider: Callable[[], str] | None = None,
    ) -> None:
        self.command = list(command) if command is not None else [
            "claude",
            "-p",
            "/usage",
            "--output-format",
            "text",
            "--no-session-persistence",
        ]
        self.limit_probe_command = list(limit_probe_command) if limit_probe_command is not None else [
            "claude",
            "-p",
            "Respond with OK only.",
            "--output-format",
            "text",
            "--no-session-persistence",
        ]
        self.env = dict(env) if env else None
        self.runner = runner or ClaudeSubprocessRunner()
        self.timeout = timeout
        self.observed_at_provider = observed_at_provider or _missing_observed_at

    def collect(self) -> List[LimitWindow]:
        try:
            result = self.runner.run(self.command, self.timeout, self.env)
        except Exception as exc:
            raise ClaudeProviderError("provider_failed", f"Claude CLI /usage failed: {exc.__class__.__name__}") from exc
        if result.returncode != 0:
            raise ClaudeProviderError("provider_failed", "Claude CLI /usage failed")
        observed_at = self.observed_at_provider()
        try:
            return parse_claude_cli_usage(result.stdout, observed_at=observed_at)
        except LimitContractError:
            try:
                return parse_claude_active_limits(_load_active_limits_cache(self.env), observed_at=observed_at)
            except ClaudeProviderError:
                return self._probe_limit_message(
                    observed_at,
                    allow_unknown_subscription=_is_subscription_only_usage(result.stdout),
                )

    def _probe_limit_message(self, observed_at: str, *, allow_unknown_subscription: bool = False) -> List[LimitWindow]:
        try:
            result = self.runner.run(self.limit_probe_command, self.timeout, self.env)
        except Exception as exc:
            raise ClaudeProviderError("provider_failed", f"Claude CLI limit probe failed: {exc.__class__.__name__}") from exc
        try:
            return parse_claude_cli_usage(result.stdout, observed_at=observed_at)
        except LimitContractError as exc:
            if allow_unknown_subscription and result.returncode == 0:
                return [_unknown_subscription_window(observed_at)]
            raise ClaudeProviderError("provider_failed", "Claude CLI limit probe did not return limits") from exc


class ClaudeOAuthWithCliFallbackProvider:
    def __init__(self, oauth_provider: "ClaudeOAuthProvider", cli_provider: ClaudeCliUsageProvider) -> None:
        self.oauth_provider = oauth_provider
        self.cli_provider = cli_provider

    def collect(self) -> List[LimitWindow]:
        try:
            return self.oauth_provider.collect()
        except ClaudeProviderError as exc:
            if exc.error_type not in OAUTH_FALLBACK_ERRORS:
                raise
        return self.cli_provider.collect()


class ClaudeOAuthHTTPClient:
    def get_json(self, url: str, headers: dict[str, str], timeout: float) -> Tuple[int, dict]:
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return int(response.status), payload if isinstance(payload, dict) else {}
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except Exception:
                payload = {}
            return int(exc.code), payload if isinstance(payload, dict) else {}
        except Exception as exc:
            raise ClaudeProviderError("provider_failed", f"Claude OAuth usage request failed: {exc.__class__.__name__}") from exc


class ClaudeOAuthProvider:
    def __init__(
        self,
        *,
        auth_file: str,
        usage_url: str,
        http_client: ClaudeOAuthHTTPClient | None = None,
        timeout: float = 20.0,
    ) -> None:
        if not usage_url.strip():
            raise ClaudeProviderError("missing_credentials", "Claude usage URL is required")
        self.auth_file = auth_file
        self.usage_url = usage_url
        self.http_client = http_client or ClaudeOAuthHTTPClient()
        self.timeout = timeout

    def collect(self) -> List[LimitWindow]:
        token = load_claude_access_token(self.auth_file)
        status_code, payload = self.http_client.get_json(
            self.usage_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=self.timeout,
        )
        if status_code in {401, 403}:
            raise ClaudeProviderError("unauthorized", "Claude OAuth authentication failed")
        if status_code != 200:
            raise ClaudeProviderError("provider_failed", f"Claude OAuth usage returned HTTP {status_code}")
        return parse_claude_oauth_usage(payload)


def load_claude_access_token(auth_file: str) -> str:
    path = Path(auth_file)
    if not path.exists():
        raise ClaudeProviderError("missing_credentials", "Claude auth file is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClaudeProviderError("missing_credentials", "Claude auth file cannot be read") from exc
    if not isinstance(payload, dict):
        raise ClaudeProviderError("missing_credentials", "Claude auth file has unsupported shape")

    token = _nested_string(payload, ("oauth", "access_token"))
    if token is None:
        token = _nested_string(payload, ("claudeAiOauth", "accessToken"))
    if token is None:
        token = _nested_string(payload, ("tokens", "access_token"))
    if token is None:
        token = _nested_string(payload, ("access_token",))
    if token is None:
        token = _nested_string(payload, ("token", "access_token"))
    if token is None:
        raise ClaudeProviderError("missing_credentials", "Claude auth file does not contain an access token")
    return token


def _parse_window(
    *,
    window_payload: Dict[str, Any],
    window: str,
    observed_at: str,
    source_type: str,
    confidence: str,
) -> LimitWindow:
    used_percent = _number_field(window_payload, "used_percent", "usedPercent")
    remaining_percent = window_payload.get("remaining_percent")
    if remaining_percent is None:
        remaining_percent = 100.0 - used_percent

    return parse_limit_window(
        {
            "provider": "claude",
            "window": window,
            "used_percent": used_percent,
            "remaining_percent": remaining_percent,
            "reset_at": _string_field(window_payload, "reset_at", "resets_at", "resetsAt"),
            "window_duration_minutes": _int_field(window_payload, "window_duration_minutes", "windowDurationMins"),
            "observed_at": observed_at,
            "source_type": source_type,
            "confidence": confidence,
            "status": _optional_string_field(window_payload, "status", default="ok"),
        }
    )


def _parse_active_limit_window(
    *,
    window_payload: Dict[str, Any],
    window: str,
    duration_minutes: int,
    observed_at: str,
) -> LimitWindow:
    used_percent = _number_field(window_payload, "used_percentage", "used_percent", "usedPercent")
    reset_at = _datetime_value(window_payload, "resets_at", "reset_at", "resetsAt")
    return parse_limit_window(
        {
            "provider": "claude",
            "window": window,
            "used_percent": used_percent,
            "remaining_percent": 100.0 - used_percent,
            "reset_at": reset_at,
            "window_duration_minutes": duration_minutes,
            "observed_at": observed_at,
            "source_type": "active_limits_cache",
            "confidence": "observed",
            "status": _optional_string_field(window_payload, "status", default="ok"),
        }
    )


def _load_active_limits_cache(env: dict[str, str] | None) -> Dict[str, Any]:
    config_dir = Path((env or {}).get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    path = config_dir / "active_limits.json"
    if not path.exists():
        raise ClaudeProviderError("missing_credentials", "Claude active limits cache is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClaudeProviderError("missing_credentials", "Claude active limits cache cannot be read") from exc
    if not isinstance(payload, dict):
        raise ClaudeProviderError("missing_credentials", "Claude active limits cache has unsupported shape")
    return payload


def _is_subscription_only_usage(text: str) -> bool:
    return "using your subscription to power your Claude Code usage" in text


def _unknown_subscription_window(observed_at: str) -> LimitWindow:
    return parse_limit_window(
        {
            "provider": "claude",
            "window": "unknown",
            "used_percent": 0,
            "remaining_percent": 0,
            "reset_at": observed_at,
            "window_duration_minutes": 0,
            "observed_at": observed_at,
            "source_type": "official_cli_subscription",
            "confidence": "missing",
            "status": "unknown",
        }
    )


def _datetime_value(payload: Dict[str, Any], *names: str) -> str:
    value = _first_present(payload, *names)
    if isinstance(value, bool):
        raise LimitContractError("limit_schema_invalid", f"{'/'.join(names)} must be a datetime")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), dt_timezone.utc).isoformat()
    raise LimitContractError("limit_schema_invalid", f"{'/'.join(names)} must be a datetime")


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


def _nested_string(payload: Dict[str, Any], path: tuple[str, ...]) -> str | None:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    if isinstance(current, str) and current.strip():
        return current.strip()
    return None


def _missing_oauth_credentials() -> Dict[str, Any]:
    raise ClaudeProviderError("missing_credentials", "Claude OAuth credentials are not configured")


def _unsupported_cli_usage_reader() -> str:
    raise ClaudeProviderError("unsupported", "Claude CLI /usage reader is not configured")


def _missing_observed_at() -> str:
    return datetime.now(dt_timezone.utc).astimezone().isoformat()
