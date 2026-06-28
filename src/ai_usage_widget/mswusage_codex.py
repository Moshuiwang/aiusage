from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from .timezones import get_timezone


PROVENANCE = "mswusage_codex_token_count"
FORBIDDEN_SESSION_MARKERS = ("/", "\\", "~", ".codex", ".claude", ".jsonl", "/Users/", "/home/")
SAFE_SESSION_RE = re.compile(r"^[A-Za-z0-9:_-]{1,128}$")
TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_tokens",
    "cache_read_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)


def build_report(
    jsonl_lines: Iterable[str],
    timezone: str,
    now: datetime | None = None,
    since: datetime | None = None,
) -> dict:
    tz = get_timezone(timezone)
    generated_at = _format_datetime(_coerce_now(now, tz))
    since_at = _coerce_datetime(since, tz) if since is not None else None
    events = _parse_events(jsonl_lines, tz, since=since_at)
    fallback_session_id = _fallback_session_id(events)

    hourly: dict[str, dict] = {}
    daily: dict[str, dict] = {}
    sessions: dict[str, dict] = {}

    for event in events:
        session_id = event["session_id"] or fallback_session_id
        hour_key = event["hour"]
        date_key = event["date"]

        _add_usage(
            hourly.setdefault(hour_key, _new_bucket({"hour": hour_key, "agent": "codex"})),
            event,
            session_id=session_id,
        )
        _add_usage(
            daily.setdefault(date_key, _new_bucket({"date": date_key, "agent": "codex"})),
            event,
            session_id=session_id,
        )
        session = sessions.setdefault(
            session_id,
            _new_bucket(
                {
                    "session_id": session_id,
                    "agent": "codex",
                    "first_event_at": event["event_at"],
                    "last_event_at": event["event_at"],
                }
            ),
        )
        session["first_event_at"] = min(session["first_event_at"], event["event_at"])
        session["last_event_at"] = max(session["last_event_at"], event["event_at"])
        _add_usage(session, event, session_id=session_id)

    return {
        "schema_version": 1,
        "source": "mswusage_codex",
        "timezone": timezone,
        "generated_at": generated_at,
        "provenance": PROVENANCE,
        "daily": [_finalize_bucket(row) for _, row in sorted(daily.items())],
        "hourly": [_finalize_bucket(row) for _, row in sorted(hourly.items())],
        "sessions": [_finalize_bucket(row, include_session_count=False) for _, row in sorted(sessions.items())],
    }


def read_local_codex_jsonl_lines(
    root: Path | None = None,
    *,
    include_archived: bool = True,
    modified_since: datetime | None = None,
) -> list[str]:
    codex_roots = _codex_roots(root, include_archived=include_archived)
    cutoff = modified_since.timestamp() if modified_since is not None else None

    lines: list[str] = []
    for codex_root in codex_roots:
        if not codex_root.exists():
            continue
        for path in sorted(codex_root.glob("**/*.jsonl")):
            if not path.is_file():
                continue
            try:
                if cutoff is not None and path.stat().st_mtime < cutoff:
                    continue
                lines.append(json.dumps({"type": "mswusage_file_boundary"}, separators=(",", ":")))
                lines.extend(path.read_text(encoding="utf-8").splitlines())
            except (OSError, UnicodeDecodeError):
                continue
    return lines


def _codex_roots(root: Path | None, *, include_archived: bool) -> list[Path]:
    if root is not None:
        root = Path(root)
        sessions = root / "sessions"
        archived = root / "archived_sessions"
        if sessions.exists() or archived.exists():
            roots = [sessions]
            if include_archived:
                roots.append(archived)
            return roots
        return [root]
    codex_home = Path.home() / ".codex"
    roots = [codex_home / "sessions"]
    if include_archived:
        roots.append(codex_home / "archived_sessions")
    return roots


def _parse_events(jsonl_lines: Iterable[str], tz, *, since: datetime | None = None) -> list[dict]:
    current_session_id: str | None = None
    events: list[dict] = []
    seen_event_keys: set[str] = set()

    for line in jsonl_lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue

        if row.get("type") == "mswusage_file_boundary":
            current_session_id = None
            continue

        if row.get("type") == "session_meta":
            candidate = row.get("payload", {}).get("id") if isinstance(row.get("payload"), dict) else None
            if _is_safe_session_id(candidate):
                current_session_id = candidate
            continue

        payload = row.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        usage = info.get("last_token_usage") if isinstance(info, dict) else None
        if not isinstance(usage, dict):
            continue

        event_at = _parse_timestamp(row.get("timestamp"), tz)
        if event_at is None:
            continue
        if since is not None and event_at < since:
            continue

        normalized = _normalize_usage(usage)
        if normalized["total_tokens"] <= 0:
            continue
        event_key = _event_key(current_session_id, row.get("timestamp"), usage)
        if event_key in seen_event_keys:
            continue
        seen_event_keys.add(event_key)
        event = {
            **normalized,
            "session_id": current_session_id,
            "event_at": _format_datetime(event_at),
            "hour": _format_datetime(event_at.replace(minute=0, second=0, microsecond=0)),
            "date": event_at.date().isoformat(),
        }
        events.append(event)

    return events


def _event_key(session_id: str | None, timestamp: object, usage: dict) -> str:
    payload = {
        "session_id": session_id or "",
        "timestamp": timestamp if isinstance(timestamp, str) else "",
        "usage": {
            key: usage.get(key)
            for key in sorted(usage)
            if key.endswith("_tokens") or key in {"total_tokens"}
        },
    }
    fingerprint = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def _normalize_usage(usage: dict) -> dict[str, int]:
    raw_input = _to_non_negative_int(usage.get("input_tokens"))
    cached_input = _to_non_negative_int(usage.get("cached_input_tokens"))
    output = _to_non_negative_int(usage.get("output_tokens"))
    reasoning_output = _to_non_negative_int(usage.get("reasoning_output_tokens"))
    cache_read = min(cached_input, raw_input)
    input_tokens = max(raw_input - cache_read, 0)
    cache_creation = 0
    total = input_tokens + output + cache_creation + cache_read
    return {
        "input_tokens": input_tokens,
        "output_tokens": output,
        "cache_creation_tokens": cache_creation,
        "cache_read_tokens": cache_read,
        "reasoning_output_tokens": reasoning_output,
        "total_tokens": total,
    }


def _new_bucket(base: dict) -> dict:
    row = {**base, "event_count": 0, "_session_ids": set(), "provenance": PROVENANCE}
    for field in TOKEN_FIELDS:
        row[field] = 0
    return row


def _add_usage(bucket: dict, event: dict, *, session_id: str) -> None:
    for field in TOKEN_FIELDS:
        bucket[field] += event[field]
    bucket["event_count"] += 1
    bucket["_session_ids"].add(session_id)


def _finalize_bucket(bucket: dict, *, include_session_count: bool = True) -> dict:
    row = dict(bucket)
    session_ids = row.pop("_session_ids")
    if include_session_count:
        row["session_count"] = len(session_ids)
    return row


def _parse_timestamp(value: object, tz: ZoneInfo) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_timezone.utc)
    return parsed.astimezone(tz)


def _format_datetime(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def _coerce_now(now: datetime | None, tz: ZoneInfo) -> datetime:
    if now is None:
        return datetime.now(dt_timezone.utc).astimezone(tz)
    return _coerce_datetime(now, tz)


def _coerce_datetime(value: datetime, tz: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt_timezone.utc).astimezone(tz)
    return value.astimezone(tz)


def _fallback_session_id(events: list[dict]) -> str:
    if not events:
        return "fallback:000000000000"
    fingerprint = json.dumps(
        [
            {
                "event_at": event["event_at"],
                "input_tokens": event["input_tokens"],
                "output_tokens": event["output_tokens"],
                "cache_read_tokens": event["cache_read_tokens"],
                "total_tokens": event["total_tokens"],
            }
            for event in events
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"fallback:{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:12]}"


def _is_safe_session_id(value: object) -> bool:
    if not isinstance(value, str) or not SAFE_SESSION_RE.match(value):
        return False
    lowered = value.lower()
    return not any(marker.lower() in lowered for marker in FORBIDDEN_SESSION_MARKERS)


def _to_non_negative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    return 0
