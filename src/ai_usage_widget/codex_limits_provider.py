from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from .limits import LimitContractError, LimitWindow, parse_limit_window


WHAM_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"


class CodexProviderError(RuntimeError):
    def __init__(self, error_type: str, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type


WHAM_AUTH_FALLBACK_ERRORS = {"missing_credentials", "unauthorized"}


def parse_codex_wham_usage(payload: Dict[str, Any]) -> List[LimitWindow]:
    if not isinstance(payload, dict):
        raise LimitContractError("codex_wham_schema_invalid", "Codex WHAM usage payload must be an object")

    observed_at = _string_field(payload, "observed_at")
    return [
        _parse_window(
            window_payload=_object_field(payload, "primary_window"),
            window="session",
            observed_at=observed_at,
            source_type="runtime_api",
        ),
        _parse_window(
            window_payload=_object_field(payload, "secondary_window"),
            window="week",
            observed_at=observed_at,
            source_type="runtime_api",
        ),
    ]


def parse_codex_rpc_rate_limits(payload: Dict[str, Any], *, observed_at: str | None = None) -> List[LimitWindow]:
    if not isinstance(payload, dict):
        raise LimitContractError("codex_rpc_schema_invalid", "Codex RPC rate limits payload must be an object")

    payload = _unwrap_rpc_result(payload)
    observed_at = observed_at or _string_field(payload, "observed_at")
    rate_limits = _object_field(payload, "rate_limits", "rateLimits")
    return [
        _parse_window(
            window_payload=_object_field(rate_limits, "primary"),
            window="session",
            observed_at=observed_at,
            source_type="cli_rpc",
        ),
        _parse_window(
            window_payload=_object_field(rate_limits, "secondary"),
            window="week",
            observed_at=observed_at,
            source_type="cli_rpc",
        ),
    ]


class CodexLimitsProvider:
    def __init__(
        self,
        wham_fetcher: Callable[[], Dict[str, Any]] | None = None,
        rpc_reader: Callable[[], Dict[str, Any]] | None = None,
    ) -> None:
        self.wham_fetcher = wham_fetcher or _missing_wham_credentials
        self.rpc_reader = rpc_reader or _unsupported_rpc_reader

    def collect(self) -> List[LimitWindow]:
        try:
            wham_payload = self.wham_fetcher()
        except CodexProviderError as exc:
            if exc.error_type not in WHAM_AUTH_FALLBACK_ERRORS:
                raise
        else:
            return parse_codex_wham_usage(wham_payload)

        return parse_codex_rpc_rate_limits(self.rpc_reader())


@dataclass(frozen=True)
class CodexCommandResult:
    returncode: int
    stdout: str
    stderr: str


class CodexSubprocessRunner:
    def run(self, command: list[str], stdin: str, timeout: float) -> CodexCommandResult:
        result = subprocess.run(
            command,
            input=stdin,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return CodexCommandResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)


class CodexAppServerRPCProvider:
    REQUEST_ID = "ai-usage-widget-rate-limits"

    def __init__(
        self,
        *,
        command: list[str] | None = None,
        socket_path: str | None = None,
        runner: CodexSubprocessRunner | None = None,
        timeout: float = 20.0,
        observed_at_provider: Callable[[], str] | None = None,
    ) -> None:
        self.command = list(command) if command is not None else ["codex", "app-server", "proxy"]
        if socket_path:
            self.command.extend(["--sock", socket_path])
        self.runner = runner or CodexSubprocessRunner()
        self.timeout = timeout
        self.observed_at_provider = observed_at_provider or _default_observed_at

    def collect(self) -> List[LimitWindow]:
        request = {
            "id": self.REQUEST_ID,
            "method": "account/rateLimits/read",
            "params": None,
        }
        try:
            result = self.runner.run(self.command, json.dumps(request) + "\n", self.timeout)
        except Exception as exc:
            raise CodexProviderError("provider_failed", f"Codex app-server proxy failed: {exc.__class__.__name__}") from exc

        if result.returncode != 0:
            raise CodexProviderError("provider_failed", "Codex app-server proxy failed")

        payload = _parse_json_rpc_stdout(result.stdout)
        if "error" in payload:
            raise CodexProviderError("provider_failed", "Codex app-server RPC returned an error")
        return parse_codex_rpc_rate_limits(payload, observed_at=self.observed_at_provider())


class CodexWhamWithRPCFallbackProvider:
    def __init__(self, wham_provider: "CodexWhamProvider", rpc_provider: CodexAppServerRPCProvider) -> None:
        self.wham_provider = wham_provider
        self.rpc_provider = rpc_provider

    def collect(self) -> List[LimitWindow]:
        try:
            return self.wham_provider.collect()
        except CodexProviderError as exc:
            if exc.error_type not in WHAM_AUTH_FALLBACK_ERRORS:
                raise
        return self.rpc_provider.collect()


class CodexWhamHTTPClient:
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
            raise CodexProviderError("provider_failed", f"Codex WHAM request failed: {exc.__class__.__name__}") from exc


class CodexWhamProvider:
    def __init__(
        self,
        *,
        auth_file: str,
        http_client: CodexWhamHTTPClient | None = None,
        usage_url: str = WHAM_USAGE_URL,
        timeout: float = 20.0,
    ) -> None:
        self.auth_file = auth_file
        self.http_client = http_client or CodexWhamHTTPClient()
        self.usage_url = usage_url
        self.timeout = timeout

    def collect(self) -> List[LimitWindow]:
        token = load_codex_access_token(self.auth_file)
        status_code, payload = self.http_client.get_json(
            self.usage_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=self.timeout,
        )
        if status_code in {401, 403}:
            raise CodexProviderError("unauthorized", "Codex WHAM authentication failed")
        if status_code != 200:
            raise CodexProviderError("provider_failed", f"Codex WHAM returned HTTP {status_code}")
        return parse_codex_wham_usage(payload)


def load_codex_access_token(auth_file: str) -> str:
    path = Path(auth_file)
    if not path.exists():
        raise CodexProviderError("missing_credentials", "Codex auth file is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CodexProviderError("missing_credentials", "Codex auth file cannot be read") from exc
    if not isinstance(payload, dict):
        raise CodexProviderError("missing_credentials", "Codex auth file has unsupported shape")

    token = _nested_string(payload, ("tokens", "access_token"))
    if token is None:
        token = _nested_string(payload, ("oauth", "access_token"))
    if token is None:
        token = _nested_string(payload, ("access_token",))
    if token is None:
        token = _nested_string(payload, ("token", "access_token"))
    if token is None:
        raise CodexProviderError("missing_credentials", "Codex auth file does not contain an access token")
    return token


def _parse_window(
    *,
    window_payload: Dict[str, Any],
    window: str,
    observed_at: str,
    source_type: str,
) -> LimitWindow:
    used_percent = _number_field(window_payload, "used_percent", "usedPercent")
    reset_at = _datetime_field(window_payload, "reset_at", "resets_at", "resetsAt")
    duration = _int_field(window_payload, "window_duration_minutes", "windowDurationMins")
    remaining_percent = window_payload.get("remaining_percent")
    if remaining_percent is None:
        remaining_percent = 100.0 - used_percent

    return parse_limit_window(
        {
            "provider": "codex",
            "window": window,
            "used_percent": used_percent,
            "remaining_percent": remaining_percent,
            "reset_at": reset_at,
            "window_duration_minutes": duration,
            "observed_at": observed_at,
            "source_type": source_type,
            "confidence": _optional_string_field(window_payload, "confidence", default="observed"),
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


def _datetime_field(payload: Dict[str, Any], *names: str) -> str:
    value = _first_present(payload, *names)
    if isinstance(value, bool):
        raise LimitContractError("limit_schema_invalid", f"{'/'.join(names)} must be a datetime")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), dt_timezone.utc).isoformat()
    raise LimitContractError("limit_schema_invalid", f"{'/'.join(names)} must be a datetime")


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


def _unwrap_rpc_result(payload: Dict[str, Any]) -> Dict[str, Any]:
    result = payload.get("result")
    if result is None:
        return payload
    if not isinstance(result, dict):
        raise LimitContractError("codex_rpc_schema_invalid", "Codex RPC result must be an object")
    return result


def _parse_json_rpc_stdout(stdout: str) -> Dict[str, Any]:
    text = stdout.strip()
    if not text:
        raise CodexProviderError("provider_failed", "Codex app-server RPC returned empty output")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("id") == CodexAppServerRPCProvider.REQUEST_ID:
                return payload
        raise CodexProviderError("provider_failed", "Codex app-server RPC returned invalid JSON")
    if not isinstance(payload, dict):
        raise CodexProviderError("provider_failed", "Codex app-server RPC response must be an object")
    return payload


def _default_observed_at() -> str:
    return datetime.now(dt_timezone.utc).astimezone().isoformat()


def _missing_wham_credentials() -> Dict[str, Any]:
    raise CodexProviderError("missing_credentials", "Codex OAuth credentials are not configured")


def _unsupported_rpc_reader() -> Dict[str, Any]:
    raise CodexProviderError("unsupported", "Codex CLI RPC reader is not configured")
