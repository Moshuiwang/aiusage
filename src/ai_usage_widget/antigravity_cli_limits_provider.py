from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone

from .antigravity_limits_provider import AntigravityProviderError
from .limits import LimitContractError, LimitWindow, parse_limit_window


# agy 1.5.14 emits the built-in /usage report as a four-column TSV in the JSON response.
_WINDOWS = {
    ("Gemini Models", "Five Hour Limit Remaining"): ("session", 300),
    ("Gemini Models", "Weekly Limit Remaining"): ("week", 10080),
    ("Claude and GPT models", "Five Hour Limit Remaining"): ("claude_gpt_session", 300),
    ("Claude and GPT models", "Weekly Limit Remaining"): ("claude_gpt_week", 10080),
    ("Gemini 4 Argon", "Gemini 4 Argon Weekly Limit"): ("argon_week", 10080),
}
_USAGE_COUNTERS = {"input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens", "total_tokens"}
_CLI_ENV_KEYS = (
    "HOME", "PATH", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR",
    "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS",
)
_PERCENT = re.compile(r"[0-9]{1,3}(?:\.[0-9]+)?%")
_RESET = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)


class AntigravityCliLimitsProvider:
    def __init__(self, *, env: dict[str, str] | None = None) -> None:
        self.env = env

    def collect(self) -> list[LimitWindow]:
        # Keep the user's CLI profile and PATH without passing the collector's ingest credentials.
        env = {key: os.environ[key] for key in _CLI_ENV_KEYS if key in os.environ}
        env.update(self.env or {})
        try:
            result = subprocess.run(
                ["agy", "--settings", '{"disableSlashCommands":false}', "-p", "/usage", "--output-format", "json"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                encoding="utf-8",
                timeout=45,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired:
            raise AntigravityProviderError("timeout", "Antigravity CLI quota command timed out") from None
        except (OSError, UnicodeError):
            raise AntigravityProviderError("provider_unavailable", "Antigravity CLI quota command could not run") from None
        if result.returncode != 0:
            raise AntigravityProviderError("provider_unavailable", "Antigravity CLI quota command failed")

        return _parse_cli_quota(result.stdout, observed_at=datetime.now(timezone.utc).isoformat())


def _parse_cli_quota(raw: str, *, observed_at: str) -> list[LimitWindow]:
    try:
        envelope = json.loads(raw)
    except ValueError:
        raise LimitContractError("limit_schema_invalid", "Antigravity CLI quota output must be JSON") from None
    if (
        not isinstance(envelope, dict)
        or envelope.get("status") != "SUCCESS"
        or envelope.get("error")
        or not isinstance(envelope.get("response"), str)
    ):
        raise LimitContractError("limit_schema_invalid", "Antigravity CLI did not return a successful quota report")

    turns, usage = envelope.get("num_turns"), envelope.get("usage")
    if (
        type(turns) is not int or turns != 0
        or not isinstance(usage, dict) or not _USAGE_COUNTERS <= usage.keys()
        or any(type(count) is not int or count != 0 for count in usage.values())
    ):
        raise LimitContractError("limit_schema_invalid", "Antigravity CLI quota report did not prove a zero-turn command")

    windows: dict[str, LimitWindow] = {}
    for line in envelope["response"].splitlines():
        columns = line.split("\t")
        if len(columns) != 4:
            raise LimitContractError("limit_schema_invalid", "Antigravity CLI quota row has an unexpected shape")
        group, label, percent, reset_at = columns
        definition = _WINDOWS.get((group, label))
        if definition is None or not _PERCENT.fullmatch(percent) or not _RESET.fullmatch(reset_at):
            raise LimitContractError("limit_schema_invalid", "Antigravity CLI quota row has unexpected fields")
        window, duration = definition
        if window in windows:
            raise LimitContractError("limit_schema_invalid", "Antigravity CLI quota report duplicated a window")
        remaining = float(percent[:-1])
        windows[window] = parse_limit_window(
            {
                "provider": "antigravity",
                "window": window,
                "used_percent": 100.0 - remaining,
                "remaining_percent": remaining,
                "reset_at": reset_at,
                "window_duration_minutes": duration,
                "observed_at": observed_at,
                "source_type": "official_cli",
                "confidence": "observed",
                "status": "ok",
            }
        )

    if not {"session", "week"} <= windows.keys() or ("claude_gpt_session" in windows) != ("claude_gpt_week" in windows):
        raise LimitContractError("limit_schema_invalid", "Antigravity CLI quota report has an incomplete window pair")
    return [windows[window] for window, _ in _WINDOWS.values() if window in windows]
