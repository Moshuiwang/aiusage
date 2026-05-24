from __future__ import annotations

from typing import Any, Dict, List, Optional

from .normalize import normalize_ccusage_daily
from .runners import run_source
from .storage_json import atomic_write_json
from .storage_sqlite import build_source_report, write_sqlite
from .timeutil import now_iso


def collect(config: Dict[str, Any], output_path: str, sqlite_path: Optional[str] = None) -> Dict[str, Any]:
    timezone = config["timezone"]
    collected_at = now_iso(timezone)
    items = []
    source_status = []
    source_reports = []

    for source in config["sources"]:
        if not source.get("enabled", True):
            status = _source_status(source, "disabled", None, None)
            source_status.append(status)
            continue

        result = run_source(source)
        if not result.ok:
            status = _source_status(source, "failed", result.error_type, result.error_message)
            source_status.append(status)
            source_reports.append(build_source_report(source, result, "failed"))
            continue

        normalized = normalize_ccusage_daily(source, result.stdout)
        if normalized.status != "ok":
            status = _source_status(source, "failed", normalized.error_type, normalized.error_message)
            source_status.append(status)
            result.error_type = normalized.error_type
            result.error_message = normalized.error_message
            source_reports.append(build_source_report(source, result, "failed"))
            continue

        items.extend(normalized.items)
        status = _source_status(source, "ok", None, None)
        source_status.append(status)
        report = build_source_report(source, result, "ok")
        periods = [item.date for item in normalized.items]
        if periods:
            report["first_period"] = min(periods)
            report["last_period"] = max(periods)
        source_reports.append(report)

    snapshot = {
        "generated_at": collected_at,
        "timezone": timezone,
        "items": [item.to_latest_dict() for item in items],
        "source_status": source_status,
    }
    atomic_write_json(output_path, snapshot)

    if sqlite_path:
        run_status = _run_status(source_status)
        write_sqlite(sqlite_path, collected_at, timezone, run_status, source_reports, items)

    return snapshot


def _source_status(source: Dict[str, Any], status: str, error_type: Optional[str], message: Optional[str]) -> Dict[str, Any]:
    row = {
        "source_id": source["source_id"],
        "status": status,
    }
    if error_type:
        row["error_type"] = error_type
    if message:
        row["message"] = str(message)[:500]
    return row


def _run_status(source_status: List[Dict[str, Any]]) -> str:
    enabled = [row for row in source_status if row["status"] != "disabled"]
    if not enabled:
        return "failed"
    failed = [row for row in enabled if row["status"] != "ok"]
    if not failed:
        return "ok"
    if len(failed) == len(enabled):
        return "failed"
    return "partial_failed"

