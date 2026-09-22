from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import datetime, timezone as dt_timezone
from pathlib import Path

from .timezones import get_timezone
from .usage_models import add_model_usage, finalize_model_usage, model_name


PROVENANCE = "mswusage_codex_token_count"
COLLECTOR_VERSION = "0.2.0"
PARSER_SCHEMA_VERSION = 3
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

    read_errors = _to_non_negative_int((read_diagnostics or {}).get("read_errors"))
    parse_stats["read_errors"] = read_errors
    scan_complete = read_errors == 0 and parse_stats["unresolved_mismatch"] == 0
    collector = {
        "version": COLLECTOR_VERSION,
        "parser_schema_version": PARSER_SCHEMA_VERSION,
        "mode": mode,
        "lookback_hours": float(lookback_hours) if mode == "incremental" and lookback_hours is not None else None,
        "coverage": coverage,
        "counts": parse_stats,
        "scan_complete": scan_complete,
    }
    report = {
        "schema_version": 1,
        "source": "mswusage_codex",
        "timezone": timezone,
        "generated_at": generated_at,
        "provenance": PROVENANCE,
        "daily": [_finalize_bucket(row) for _, row in sorted(daily.items())],
        "hourly": [_finalize_bucket(row) for _, row in sorted(hourly.items())],
        "sessions": [_finalize_bucket(row, include_session_count=False) for _, row in sorted(sessions.items())],
        "collector": collector,
    }
    collector["report_digest"] = _safe_report_digest(report)
    return report


def read_local_codex_jsonl_lines(
    root: Path | None = None,
    *,
    include_archived: bool = True,
    modified_since: datetime | None = None,
    diagnostics: dict | None = None,
) -> list[str]:
    codex_roots = _codex_roots(root, include_archived=include_archived)
    cutoff = modified_since.timestamp() if modified_since is not None else None

    lines: list[str] = []
    files_scanned = 0
    read_errors = 0
    roots_found = 0
    for codex_root in codex_roots:
        if not codex_root.exists():
            continue
        roots_found += 1
        for path in sorted(codex_root.glob("**/*.jsonl")):
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
    if roots_found == 0:
        read_errors += 1
    if diagnostics is not None:
        diagnostics.update({"files_scanned": files_scanned, "read_errors": read_errors})
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


def _parse_events(jsonl_lines: Iterable[str], tz, *, since: datetime | None = None) -> tuple[list[dict], dict, dict]:
    current_session_id: str | None = None
    current_model = "unknown"
    file_scope = 0
    candidates: list[dict] = []
    events: list[dict] = []
    seen_event_keys: set[str] = set()
    stats = {
        "scanned": 0,
        "seeded": 0,
        "accepted": 0,
        "exact_duplicate": 0,
        "no_growth": 0,
        "cumulative_reset": 0,
        "non_contiguous_transition": 0,
        "same_total_state_change": 0,
        "fallback": 0,
        "unresolved_mismatch": 0,
    }

    for input_index, line in enumerate(jsonl_lines):
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue

        if row.get("type") == "mswusage_file_boundary":
            file_scope += 1
            current_session_id = None
            current_model = "unknown"
            continue

        if row.get("type") == "session_meta":
            current_model = "unknown"
            candidate = row.get("payload", {}).get("id") if isinstance(row.get("payload"), dict) else None
            if _is_safe_session_id(candidate):
                current_session_id = candidate
            continue

        payload = row.get("payload")
        if row.get("type") == "turn_context":
            current_model = model_name(payload.get("model")) if isinstance(payload, dict) else "unknown"
            continue
        if not isinstance(payload, dict) or payload.get("type") != "token_count":
            continue
        info = payload.get("info")
        usage = info.get("last_token_usage") if isinstance(info, dict) else None
        if not isinstance(usage, dict):
            continue

        event_at = _parse_timestamp(row.get("timestamp"), tz)
        if event_at is None:
            continue
        normalized = _normalize_usage(usage)
        if normalized["total_tokens"] <= 0:
            continue
        cumulative_usage = info.get("total_token_usage") if isinstance(info, dict) else None
        cumulative = _normalize_usage(cumulative_usage) if isinstance(cumulative_usage, dict) else None
        if cumulative is not None and cumulative["total_tokens"] <= 0:
            cumulative = None
        scope = f"session:{current_session_id}" if current_session_id else f"file:{file_scope}"
        candidates.append({
            "model": model_name(info.get("model", payload.get("model", current_model))),
            "scope": scope,
            "session_id": current_session_id,
            "timestamp": row.get("timestamp"),
            "event_at_value": event_at,
            "input_index": input_index,
            "usage": usage,
            "normalized": normalized,
            "cumulative": cumulative,
        })

    seen_cumulative_states: dict[str, set[tuple[int, ...]]] = {}
    previous_cumulative: dict[str, dict[str, int]] = {}
    coverage_times: list[datetime] = []
    for candidate in sorted(candidates, key=lambda item: (item["scope"], item["event_at_value"], item["input_index"])):
        stats["scanned"] += 1
        event_at = candidate["event_at_value"]
        coverage_times.append(event_at)
        event_key = _event_key(candidate["session_id"], candidate["timestamp"], candidate["usage"])
        if event_key in seen_event_keys:
            stats["exact_duplicate"] += 1
            continue
        seen_event_keys.add(event_key)

        normalized = candidate["normalized"]
        cumulative = candidate["cumulative"]
        accept = True
        if cumulative is not None:
            scope = candidate["scope"]
            state = tuple(cumulative[field] for field in TOKEN_FIELDS)
            previous = previous_cumulative.get(scope)
            if previous is not None and cumulative["total_tokens"] == previous["total_tokens"] and state != tuple(previous[field] for field in TOKEN_FIELDS):
                stats["same_total_state_change"] += 1
            reset = previous is not None and any(cumulative[field] < previous[field] for field in TOKEN_FIELDS)
            if reset:
                stats["cumulative_reset"] += 1
                seen_cumulative_states[scope] = set()
            states = seen_cumulative_states.setdefault(scope, set())
            if state in states:
                stats["no_growth"] += 1
                accept = False
            else:
                states.add(state)
            mismatch = any(cumulative[field] < normalized[field] for field in TOKEN_FIELDS)
            if previous is not None and not reset and accept and any(
                    cumulative[field] - previous[field] != normalized[field]
                    for field in TOKEN_FIELDS
            ):
                stats["non_contiguous_transition"] += 1
            if mismatch:
                stats["unresolved_mismatch"] += 1
            previous_cumulative[scope] = cumulative
        else:
            stats["fallback"] += 1

        if since is not None and event_at < since:
            if cumulative is not None:
                stats["seeded"] += 1
            continue
        if not accept:
            continue
        event = {
            **normalized,
            "model": candidate["model"],
            "session_id": candidate["session_id"],
            "event_at": _format_datetime(event_at),
            "hour": _format_datetime(event_at.replace(minute=0, second=0, microsecond=0)),
            "date": event_at.date().isoformat(),
        }
        events.append(event)
        stats["accepted"] += 1

    coverage = _coverage(coverage_times)
    return events, stats, coverage


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


def _coverage(event_times: list[datetime]) -> dict:
    if not event_times:
        return {"start": None, "end": None}
    start = min(event_times).replace(minute=0, second=0, microsecond=0)
    end = max(event_times).replace(minute=0, second=0, microsecond=0)
    from datetime import timedelta
    return {"start": _format_datetime(start), "end": _format_datetime(end + timedelta(hours=1))}


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
        from datetime import timedelta
        end_hour += timedelta(hours=1)
    return {"start": _format_datetime(start_hour), "end": _format_datetime(end_hour)}


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
    add_model_usage(bucket, event, TOKEN_FIELDS)
    for field in TOKEN_FIELDS:
        bucket[field] += event[field]
    bucket["event_count"] += 1
    bucket["_session_ids"].add(session_id)


def _finalize_bucket(bucket: dict, *, include_session_count: bool = True) -> dict:
    row = dict(bucket)
    finalize_model_usage(row)
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
