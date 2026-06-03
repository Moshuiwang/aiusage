from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from .limits import LimitContractError, LimitWindow, parse_limit_window


class ClaudeProviderError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


OAUTH_FALLBACK_ERRORS = {"missing_credentials", "unauthorized"}

_CLI_WINDOW_PATTERNS = (
    ("session", re.compile(r"5h\s+window:\s*([0-9]+(?:\.[0-9]+)?)%\s+used,\s*resets\s+at\s*([^,\s]+),\s*duration\s+([0-9]+)\s+minutes", re.IGNORECASE)),
    ("week", re.compile(r"weekly\s+window:\s*([0-9]+(?:\.[0-9]+)?)%\s+used,\s*resets\s+at\s*([^,\s]+),\s*duration\s+([0-9]+)\s+minutes", re.IGNORECASE)),
)


def parse_claude_oauth_usage(payload: Dict[str, Any]) -> List[LimitWindow]:
    if not isinstance(payload, dict):
        raise LimitContractError("claude_oauth_schema_invalid", "Claude OAuth usage payload must be an object")

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
    def run(self, command: list[str], timeout: float) -> ClaudeCommandResult:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return ClaudeCommandResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)


class ClaudeCliUsageProvider:
    def __init__(
        self,
        *,
        command: list[str] | None = None,
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
        self.runner = runner or ClaudeSubprocessRunner()
        self.timeout = timeout
        self.observed_at_provider = observed_at_provider or _missing_observed_at

    def collect(self) -> List[LimitWindow]:
        try:
            result = self.runner.run(self.command, self.timeout)
        except Exception as exc:
            raise ClaudeProviderError("provider_failed", f"Claude CLI /usage failed: {exc.__class__.__name__}") from exc
        if result.returncode != 0:
            raise ClaudeProviderError("provider_failed", "Claude CLI /usage failed")
        return parse_claude_cli_usage(result.stdout, observed_at=self.observed_at_provider())


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
