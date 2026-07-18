from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any

from .timezones import get_timezone


PROVENANCE = "mswusage_claude_assistant_usage"
COLLECTOR_VERSION = "0.2.0"
PARSER_SCHEMA_VERSION = 1
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
    mode: str = "full-rescan",
    lookback_hours: float | None = None,
    read_diagnostics: dict | None = None,
    coverage_start: datetime | None = None,
) -> dict:
    tz = get_timezone(timezone)
    now_at = _coerce_now(now, tz)
    generated_at = _format_datetime(now_at)
    since_at = _coerce_datetime(since, tz) if since is not None else None
    coverage_start_at = _coerce_datetime(coverage_start, tz) if coverage_start is not None else None
    effective_since = coverage_start_at if coverage_start_at is not None else since_at
    events, parse_stats, coverage = _parse_events(jsonl_lines, tz, since=effective_since)
    if coverage_start_at is not None:
        coverage = _explicit_coverage(coverage_start_at, now_at)

    hourly: dict[str, dict] = {}
    daily: dict[str, dict] = {}
    for event in events:
        _add_usage(
            hourly.setdefault(event["hour"], _new_bucket({"hour": event["hour"], "agent": "claude"})),
            event,
        )
        _add_usage(
            daily.setdefault(event["date"], _new_bucket({"date": event["date"], "agent": "claude"})),
            event,
        )

    read_errors = _to_non_negative_int((read_diagnostics or {}).get("read_errors"))
    parse_stats["read_errors"] = read_errors
    collector = {
        "version": COLLECTOR_VERSION,
        "parser_schema_version": PARSER_SCHEMA_VERSION,
        "mode": mode,
        "lookback_hours": float(lookback_hours) if mode == "incremental" and lookback_hours is not None else None,
        "coverage": coverage,
        "counts": parse_stats,
        "scan_complete": read_errors == 0,
    }
    report = {
        "schema_version": 1,
        "source": "mswusage_claude",
        "timezone": timezone,
        "generated_at": generated_at,
        "provenance": PROVENANCE,
        "daily": [_finalize_bucket(row) for _, row in sorted(daily.items())],
        "hourly": [_finalize_bucket(row) for _, row in sorted(hourly.items())],
        "sessions": [],
        "collector": collector,
    }
    collector["report_digest"] = _safe_report_digest(report)
    return report


def read_local_claude_jsonl_lines(
    root: Path | None = None,
    *,
    modified_since: datetime | None = None,
    diagnostics: dict | None = None,
) -> list[str]:
    projects_root = Path(root) if root is not None else _default_projects_root()
    if not projects_root.exists():
        if diagnostics is not None:
            diagnostics.update({"files_scanned": 0, "read_errors": 1})
        return []
    cutoff = modified_since.timestamp() if modified_since is not None else None
    lines: list[str] = []
    files_scanned = 0
    read_errors = 0
    for path in sorted(projects_root.glob("**/*.jsonl")):
        if not path.is_file():
            continue
        try:
            if cutoff is not None and path.stat().st_mtime < cutoff:
                continue
            files_scanned += 1
            lines.append(json.dumps({"type": "mswusage_file_boundary"}, separators=(",", ":")))
            lines.extend(path.read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeDecodeError):
            read_errors += 1
            continue
    if diagnostics is not None:
        diagnostics.update({"files_scanned": files_scanned, "read_errors": read_errors})
    return lines


def _default_projects_root() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        return Path(config_dir) / "projects"
    return Path.home() / ".claude" / "projects"


def _parse_events(jsonl_lines: Iterable[str], tz, *, since: datetime | None = None) -> tuple[list[dict], dict, dict]:
    latest_by_key: dict[str, dict] = {}
    scanned = 0
    event_times: list[datetime] = []
    for line in jsonl_lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or row.get("type") != "assistant":
            continue
        message = row.get("message")
        if not isinstance(message, dict):
            continue
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        event_at = _parse_timestamp(row.get("timestamp"), tz)
        if event_at is None:
            continue
        scanned += 1
        event_times.append(event_at)
        if since is not None and event_at < since:
            continue
        normalized = _normalize_usage(usage)
        if normalized["total_tokens"] <= 0:
            continue
        event_key = _message_event_key(row, message, usage)
        event = {
            **normalized,
            "event_key": event_key,
            "event_at": _format_datetime(event_at),
            "_event_at_sort": event_at.timestamp(),
            "hour": _format_datetime(event_at.replace(minute=0, second=0, microsecond=0)),
            "date": event_at.date().isoformat(),
        }
        existing = latest_by_key.get(event_key)
        if existing is None or (
            event["_event_at_sort"],
            event["total_tokens"],
        ) >= (
            existing["_event_at_sort"],
            existing["total_tokens"],
        ):
            latest_by_key[event_key] = event
    events = [
        {key: value for key, value in event.items() if not key.startswith("_")}
        for event in sorted(latest_by_key.values(), key=lambda item: (item["event_at"], item["event_key"]))
    ]
    return events, {
        "scanned": scanned,
        "accepted": len(events),
        "exact_duplicate": max(scanned - len(events), 0),
        "read_errors": 0,
        "unresolved_mismatch": 0,
    }, _coverage(event_times)


def _coverage(event_times: list[datetime]) -> dict:
    if not event_times:
        return {"start": None, "end": None}
    start = min(event_times).replace(minute=0, second=0, microsecond=0)
    end = max(event_times).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return {"start": _format_datetime(start), "end": _format_datetime(end)}


def _safe_report_digest(report: dict) -> str:
    collector = report["collector"]
    coverage = collector["coverage"]
    hourly = [
        row for row in report["hourly"]
        if (not coverage.get("start") or row["hour"] >= coverage["start"])
        and (not coverage.get("end") or row["hour"] < coverage["end"])
    ]
    payload = {
        "source": report["source"],
        "timezone": report["timezone"],
        "parser_schema_version": collector["parser_schema_version"],
        "coverage": collector["coverage"],
        "scan_complete": collector["scan_complete"],
        "hourly": hourly,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _explicit_coverage(start: datetime, now: datetime) -> dict:
    start_hour = start.replace(minute=0, second=0, microsecond=0)
    end_hour = now.replace(minute=0, second=0, microsecond=0)
    if now > end_hour:
        end_hour += timedelta(hours=1)
    return {"start": _format_datetime(start_hour), "end": _format_datetime(end_hour)}


def _message_event_key(row: dict[str, Any], message: dict[str, Any], usage: dict[str, Any]) -> str:
    message_id = message.get("id")
    request_id = row.get("requestId") or row.get("request_id") or message.get("requestId") or message.get("request_id")
    if isinstance(message_id, str) and message_id:
        return f"{message_id}:{request_id or ''}"
    payload = {
        "timestamp": row.get("timestamp") if isinstance(row.get("timestamp"), str) else "",
        "usage": {
            key: usage.get(key)
            for key in sorted(usage)
            if key.endswith("_tokens")
        },
    }
    fingerprint = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return f"fallback:{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:16]}"


def _normalize_usage(usage: dict[str, Any]) -> dict[str, int]:
    input_tokens = _to_non_negative_int(usage.get("input_tokens"))
    output_tokens = _to_non_negative_int(usage.get("output_tokens"))
    cache_creation = _to_non_negative_int(
        usage.get("cache_creation_input_tokens", usage.get("cache_creation_tokens"))
    )
    cache_read = _to_non_negative_int(usage.get("cache_read_input_tokens", usage.get("cache_read_tokens")))
    reasoning = _to_non_negative_int(usage.get("reasoning_output_tokens"))
    total = input_tokens + output_tokens + cache_creation + cache_read
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_tokens": cache_creation,
        "cache_read_tokens": cache_read,
        "reasoning_output_tokens": reasoning,
        "total_tokens": total,
    }


def _new_bucket(base: dict) -> dict:
    row = {**base, "event_count": 0, "session_count": 0, "provenance": PROVENANCE}
    for field in TOKEN_FIELDS:
        row[field] = 0
    return row


def _add_usage(bucket: dict, event: dict) -> None:
    for field in TOKEN_FIELDS:
        bucket[field] += int(event.get(field) or 0)
    bucket["event_count"] += 1


def _finalize_bucket(bucket: dict) -> dict:
    return dict(bucket)


def _parse_timestamp(value: object, tz) -> datetime | None:
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


def _coerce_now(now: datetime | None, tz) -> datetime:
    if now is None:
        return datetime.now(dt_timezone.utc).astimezone(tz)
    return _coerce_datetime(now, tz)


def _coerce_datetime(value: datetime, tz) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt_timezone.utc).astimezone(tz)
    return value.astimezone(tz)


def _to_non_negative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    return 0
