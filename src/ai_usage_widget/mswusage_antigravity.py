from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any

from .timezones import get_timezone
from .usage_models import add_model_usage, finalize_model_usage, model_name


PROVENANCE = "mswusage_antigravity_token_count"
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


def _decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    res = 0
    shift = 0
    while True:
        b = data[offset]
        offset += 1
        res |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            break
    return res, offset


def _parse_proto(data: bytes) -> dict[int, list[tuple[int, Any]]]:
    fields: dict[int, list[tuple[int, Any]]] = {}
    offset = 0
    length = len(data)
    while offset < length:
        tag, offset = _decode_varint(data, offset)
        wire_type = tag & 0x7
        field_num = tag >> 3
        if wire_type == 0:  # varint
            val, offset = _decode_varint(data, offset)
        elif wire_type == 1:  # 64-bit
            val = data[offset : offset + 8]
            offset += 8
        elif wire_type == 2:  # length-delimited
            flen, offset = _decode_varint(data, offset)
            val = data[offset : offset + flen]
            offset += flen
        elif wire_type == 5:  # 32-bit
            val = data[offset : offset + 4]
            offset += 4
        else:
            break
        fields.setdefault(field_num, []).append((wire_type, val))
    return fields


def default_antigravity_roots() -> list[Path]:
    roots = []
    gemini_dir = os.environ.get("GEMINI_DIR")
    base = Path(gemini_dir) if gemini_dir else Path.home() / ".gemini"
    for sub in ("antigravity", "antigravity-cli", "antigravity-ide"):
        conv = base / sub / "conversations"
        if conv.exists() and conv.is_dir():
            roots.append(conv)
    return roots


def read_local_antigravity_events(
    roots: list[Path] | None = None,
    *,
    modified_since: datetime | None = None,
    diagnostics: dict | None = None,
) -> list[dict]:
    search_roots = roots if roots is not None else default_antigravity_roots()
    events: list[dict] = []
    files_scanned = 0
    read_errors = 0
    cutoff = modified_since.timestamp() if modified_since is not None else None

    for root in search_roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.db")):
            if not path.is_file():
                continue
            try:
                st = path.stat()
                if cutoff is not None and st.st_mtime < cutoff:
                    continue
                files_scanned += 1
                session_events = _extract_events_from_db(path)
                events.extend(session_events)
            except (OSError, sqlite3.Error, UnicodeDecodeError, ValueError):
                read_errors += 1
                continue

    if diagnostics is not None:
        diagnostics.update({"files_scanned": files_scanned, "read_errors": read_errors})

    events.sort(key=lambda ev: ev["timestamp_sec"])
    return events


def _extract_events_from_db(db_path: Path) -> list[dict]:
    events: list[dict] = []
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT s.idx, s.metadata, g.data
            FROM steps s
            JOIN gen_metadata g ON s.idx = g.idx
            ORDER BY s.idx
            """
        )
        rows = cursor.fetchall()
        for idx, step_meta_bytes, gen_data_bytes in rows:
            if not step_meta_bytes or not gen_data_bytes:
                continue
            try:
                # 1. Parse timestamp from steps.metadata
                step_meta = _parse_proto(step_meta_bytes)
                ts_field = step_meta.get(7) or step_meta.get(6) or step_meta.get(8) or step_meta.get(32)
                if not ts_field:
                    continue
                ts_proto = _parse_proto(ts_field[0][1])
                sec = ts_proto.get(1, [(0, 0)])[0][1]
                if not sec or sec <= 0:
                    continue

                # 2. Parse UsageMetadata & model from gen_metadata.data
                gen_top = _parse_proto(gen_data_bytes)
                f1_list = gen_top.get(1)
                if not f1_list:
                    continue
                f1 = _parse_proto(f1_list[0][1])

                model = "unknown"
                if 19 in f1:
                    model = f1[19][0][1].decode(errors="ignore").strip()

                if 4 not in f1:
                    continue
                f4 = _parse_proto(f1[4][0][1])
                prompt_tokens = int(f4.get(1, [(0, 0)])[0][1])
                output_tokens = int(f4.get(2, [(0, 0)])[0][1])
                cached_tokens = int(f4.get(5, [(0, 0)])[0][1])
                thoughts_tokens = int(f4.get(6, [(0, 0)])[0][1])
                total_tokens = prompt_tokens + output_tokens + cached_tokens

                if total_tokens <= 0:
                    continue

                events.append(
                    {
                        "session_id": db_path.stem,
                        "step_index": idx,
                        "timestamp_sec": sec,
                        "model": model_name(model),
                        "input_tokens": prompt_tokens,
                        "output_tokens": output_tokens,
                        "cache_creation_tokens": 0,
                        "cache_read_tokens": cached_tokens,
                        "reasoning_output_tokens": thoughts_tokens,
                        "total_tokens": total_tokens,
                    }
                )
            except Exception:
                continue
    finally:
        conn.close()
    return events


def build_report(
    events: Iterable[dict],
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

    hourly: dict[str, dict] = {}
    daily: dict[str, dict] = {}
    scanned = 0
    accepted = 0
    event_times: list[datetime] = []

    for ev in events:
        scanned += 1
        dt = datetime.fromtimestamp(ev["timestamp_sec"], tz=dt_timezone.utc).astimezone(tz)
        event_times.append(dt)
        if effective_since is not None and dt < effective_since:
            continue
        accepted += 1

        hour_key = _format_datetime(dt.replace(minute=0, second=0, microsecond=0))
        date_key = dt.date().isoformat()

        _add_usage(
            hourly.setdefault(hour_key, _new_bucket({"hour": hour_key, "agent": "antigravity"})),
            ev,
        )
        _add_usage(
            daily.setdefault(date_key, _new_bucket({"date": date_key, "agent": "antigravity"})),
            ev,
        )

    if coverage_start_at is not None:
        coverage = _explicit_coverage(coverage_start_at, now_at)
    else:
        coverage = _coverage(event_times)

    read_errors = _to_non_negative_int((read_diagnostics or {}).get("read_errors"))
    collector = {
        "version": COLLECTOR_VERSION,
        "parser_schema_version": PARSER_SCHEMA_VERSION,
        "mode": mode,
        "lookback_hours": float(lookback_hours) if mode == "incremental" and lookback_hours is not None else None,
        "coverage": coverage,
        "counts": {
            "scanned": scanned,
            "accepted": accepted,
            "exact_duplicate": 0,
            "read_errors": read_errors,
            "unresolved_mismatch": 0,
        },
        "scan_complete": read_errors == 0,
    }
    report = {
        "schema_version": 1,
        "source": "mswusage_antigravity",
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


def _new_bucket(initial: dict[str, Any]) -> dict[str, Any]:
    bucket = dict(initial)
    for field in TOKEN_FIELDS:
        bucket[field] = 0
    return bucket


def _add_usage(bucket: dict[str, Any], event: dict[str, Any]) -> None:
    for field in TOKEN_FIELDS:
        bucket[field] += int(event.get(field) or 0)
    add_model_usage(bucket, event, TOKEN_FIELDS)


def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    finalized = dict(bucket)
    finalize_model_usage(finalized)
    return finalized


def _coverage(event_times: list[datetime]) -> dict:
    if not event_times:
        return {"start": None, "end": None}
    start = min(event_times).replace(minute=0, second=0, microsecond=0)
    end = max(event_times).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return {"start": _format_datetime(start), "end": _format_datetime(end)}


def _explicit_coverage(start: datetime, end: datetime) -> dict:
    return {
        "start": _format_datetime(start.replace(minute=0, second=0, microsecond=0)),
        "end": _format_datetime(end.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)),
    }


def _safe_report_digest(report: dict) -> str:
    collector = report["collector"]
    coverage = collector["coverage"]
    hourly = [
        row
        for row in report["hourly"]
        if (not coverage.get("start") or row["hour"] >= coverage["start"])
        and (not coverage.get("end") or row["hour"] < coverage["end"])
    ]
    payload = {
        "schema_version": report["schema_version"],
        "source": report["source"],
        "provenance": report["provenance"],
        "timezone": report["timezone"],
        "coverage": coverage,
        "hourly": hourly,
        "daily": report["daily"],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _format_datetime(value: datetime) -> str:
    return value.isoformat()


def _coerce_now(now: datetime | None, tz) -> datetime:
    if now is None:
        return datetime.now(tz)
    return _coerce_datetime(now, tz)


def _coerce_datetime(value: datetime, tz) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)


def _to_non_negative_int(value: Any) -> int:
    try:
        val = int(value)
        return val if val >= 0 else 0
    except (TypeError, ValueError):
        return 0
