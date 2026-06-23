from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, Optional

from .auth import TokenAuthenticator
from .ingest import IngestResponse, IngestValidationError, validate_ingest_payload
from .limits import LOCAL_ESTIMATE_SOURCE_TYPES, LimitContractError, parse_limit_window
from .mobile_summary import build_mobile_summary
from .normalize import (
    normalize_ingest_block_request,
    normalize_ingest_hourly_facts,
    normalize_ingest_hourly_request,
    normalize_ingest_request,
)
from .storage_sqlite import write_limit_windows, write_sqlite
from .snapshot_builder import build_snapshot


class ServiceError(Exception):
    def __init__(self, status_code: int, error_type: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_type = error_type
        self.message = message


def handle_ingest_payload(
    payload: Dict[str, Any],
    *,
    token: Optional[str],
    authenticator: TokenAuthenticator,
    db_path: str,
    latest_path: str,
    timezone: str,
) -> Dict[str, Any]:
    try:
        req = validate_ingest_payload(
            payload,
            token=token,
            authenticator=authenticator,
        )
    except IngestValidationError as exc:
        status_code = 401 if exc.error_type == "http_auth_failed" else 400
        raise ServiceError(status_code, exc.error_type, str(exc)) from exc
    except Exception as exc:
        raise ServiceError(500, "internal_error", str(exc)) from exc

    items = normalize_ingest_request(req)
    hourly_items = normalize_ingest_hourly_request(req)
    hourly_facts = normalize_ingest_hourly_facts(req)
    block_items = normalize_ingest_block_request(req)

    collected_at = datetime.now(dt_timezone.utc).astimezone().isoformat()
    report = {
        "source_id": req.source_id,
        "report_type": "daily",
        "command": "HTTP Ingest",
        "status": req.collection_status,
        "ccusage_version": None,
        "first_period": None,
        "last_period": None,
        "error_type": req.error_type,
        "error_message": req.error_message,
    }
    periods = [item.date for item in items]
    if periods:
        report["first_period"] = min(periods)
        report["last_period"] = max(periods)

    try:
        write_sqlite(
            path=db_path,
            collected_at=collected_at,
            timezone=timezone,
            run_status="ok",
            source_reports=[report],
            items=items,
            hourly_items=hourly_items,
            hourly_facts=hourly_facts,
            block_items=block_items,
            source_identities=[{
                "source_id": req.source_id,
                "host": req.host,
                "machine": req.machine or req.host,
                "os_user": req.os_user,
                "platform": req.platform,
            }],
        )
    except Exception as exc:
        raise ServiceError(500, "write_failed", f"Failed to save data: {exc}") from exc

    today_str = datetime.now(dt_timezone.utc).astimezone().strftime("%Y-%m-%d")
    try:
        build_snapshot(
            db_path=db_path,
            output_path=latest_path,
            date_str=today_str,
            timezone_str=timezone,
        )
    except Exception as exc:
        print(f"Failed to build snapshot during ingest: {exc}")

    return IngestResponse(
        status="accepted",
        source_id=req.source_id,
        accepted_at=collected_at,
        facts_accepted=len(hourly_facts),
        message="Data accepted successfully",
    ).to_dict()


def handle_ingest_limits_payload(
    payload: Dict[str, Any],
    *,
    token: Optional[str],
    authenticator: TokenAuthenticator,
    db_path: str,
    latest_path: str,
    timezone: str,
) -> Dict[str, Any]:
    if not authenticator.verify(token):
        raise ServiceError(401, "http_auth_failed", "Invalid or missing token")

    try:
        observed_at, windows = validate_limits_ingest_payload(payload)
    except LimitContractError as exc:
        raise ServiceError(400, exc.error_type, str(exc)) from exc

    try:
        write_limit_windows(db_path, windows, seen_at=observed_at)
    except Exception as exc:
        raise ServiceError(500, "write_failed", f"Failed to save limits: {exc}") from exc

    try:
        build_snapshot(
            db_path=db_path,
            output_path=latest_path,
            date_str=observed_at[:10],
            timezone_str=timezone,
            current_time_str=observed_at,
        )
    except Exception as exc:
        print(f"Failed to build snapshot during limits ingest: {exc}")

    return {
        "success": True,
        "status": "accepted",
        "windows_written": len(windows),
        "accepted_at": observed_at,
    }


def build_summary_response(
    *,
    db_path: str,
    latest_path: str,
    timezone: str,
    date_str: str,
    period: str,
    machine_filter: Optional[str],
    account_filter: Optional[str],
) -> str:
    return _build_request_snapshot(
        db_path=db_path,
        latest_path=latest_path,
        timezone=timezone,
        date_str=date_str,
        period=period,
        machine_filter=machine_filter,
        account_filter=account_filter,
    )


def build_mobile_summary_response(
    *,
    db_path: str,
    latest_path: str,
    timezone: str,
    date_str: str,
    period: str,
    machine_filter: Optional[str],
    account_filter: Optional[str],
) -> Dict[str, Any]:
    snapshot_data = _build_request_snapshot(
        db_path=db_path,
        latest_path=latest_path,
        timezone=timezone,
        date_str=date_str,
        period=period,
        machine_filter=machine_filter,
        account_filter=account_filter,
    )
    snapshot = json.loads(snapshot_data)
    return build_mobile_summary(snapshot)


def build_health_response(
    *,
    db_path: str,
    latest_path: str,
    now_provider=None,
) -> Dict[str, Any]:
    latest_data: Dict[str, Any] = {}
    if os.path.exists(latest_path):
        try:
            with open(latest_path, "r", encoding="utf-8") as f:
                latest_data = json.load(f)
        except (OSError, json.JSONDecodeError):
            latest_data = {}

    source_status = latest_data.get("source_status") if isinstance(latest_data, dict) else []
    if not isinstance(source_status, list):
        source_status = []
    counts: Dict[str, int] = {}
    for source in source_status:
        if not isinstance(source, dict):
            continue
        status = str(source.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1

    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    limits_health = _limits_health(db_path)
    latest_mtime = (
        datetime.fromtimestamp(os.path.getmtime(latest_path), dt_timezone.utc).astimezone().isoformat()
        if os.path.exists(latest_path)
        else None
    )
    now = now_provider or _default_now
    return {
        "status": "ok",
        "generated_at": now(),
        "backend_mode": "origin_direct",
        "canonical_store": "origin_sqlite",
        "database": {
            "path": db_path,
            "size_bytes": db_size,
            "exists": os.path.exists(db_path),
        },
        "snapshot": {
            "path": latest_path,
            "exists": os.path.exists(latest_path),
            "updated_at": latest_mtime,
        },
        "source_status": {
            "total": len(source_status),
            "counts": counts,
            "non_ok": [
                {
                    "source_id": str(source.get("source_id") or ""),
                    "status": str(source.get("status") or "unknown"),
                }
                for source in source_status
                if isinstance(source, dict) and str(source.get("status") or "unknown") != "ok"
            ],
        },
        "limits": limits_health,
    }


def _limits_health(db_path: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "latest_observed_at": None,
        "effective_window_count": 0,
        "raw_window_count": 0,
        "stale_window_count": 0,
    }
    if not os.path.exists(db_path):
        return result
    try:
        with sqlite3.connect(db_path) as conn:
            if not _sqlite_table_exists(conn, "limit_windows"):
                return result
            rows = conn.execute(
                """
                SELECT observed_at, source_type, confidence, status
                FROM limit_windows
                """
            ).fetchall()
    except sqlite3.Error:
        return result
    effective_observed = [
        str(observed_at or "")
        for observed_at, source_type, confidence, status in rows
        if status == "ok"
        and confidence == "observed"
        and source_type not in LOCAL_ESTIMATE_SOURCE_TYPES
    ]
    result["raw_window_count"] = len(rows)
    result["effective_window_count"] = len(effective_observed)
    result["stale_window_count"] = len(rows) - len(effective_observed)
    result["latest_observed_at"] = max(effective_observed, default=None)
    return result


def _sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def validate_limits_ingest_payload(payload: Any):
    if not isinstance(payload, dict):
        raise LimitContractError("limit_schema_invalid", "limits payload must be an object")
    _reject_sensitive_payload_keys(payload)

    if payload.get("schema_version") != 1:
        raise LimitContractError("limit_schema_invalid", "schema_version must be 1")
    observed_at = payload.get("observed_at")
    if not isinstance(observed_at, str) or not observed_at.strip():
        raise LimitContractError("limit_schema_invalid", "observed_at must be a non-empty string")
    observed_at = observed_at.strip()
    try:
        datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LimitContractError("limit_schema_invalid", "observed_at must be an ISO 8601 datetime") from exc

    windows_payload = payload.get("windows")
    if not isinstance(windows_payload, list):
        raise LimitContractError("limit_schema_invalid", "windows must be a list")
    windows = []
    for item in windows_payload:
        if not isinstance(item, dict):
            raise LimitContractError("limit_schema_invalid", "limit window must be an object")
        _reject_sensitive_payload_keys(item)
        windows.append(parse_limit_window(item))
    return observed_at, windows


def _build_request_snapshot(
    *,
    db_path: str,
    latest_path: str,
    timezone: str,
    date_str: str,
    period: str,
    machine_filter: Optional[str],
    account_filter: Optional[str],
) -> str:
    latest_dir = os.path.dirname(latest_path) or "."
    os.makedirs(latest_dir, exist_ok=True)
    tmp_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        prefix="request-snapshot-",
        dir=latest_dir,
        delete=False,
    )
    tmp_path = tmp_file.name
    tmp_file.close()
    try:
        build_snapshot(
            db_path=db_path,
            output_path=tmp_path,
            date_str=date_str,
            timezone_str=timezone,
            period=period,
            machine_filter=machine_filter,
            account_filter=account_filter,
        )
        with open(tmp_path, "r", encoding="utf-8") as handle:
            return handle.read()
    finally:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass


def _reject_sensitive_payload_keys(payload: Dict[str, Any]) -> None:
    sensitive_keys = {"token", "auth_file", "api_key", "secret", "env", "raw_json", "raw"}
    present = sorted(key for key in payload if key in sensitive_keys)
    if present:
        raise LimitContractError("limit_schema_invalid", "sensitive fields are not accepted: " + ", ".join(present))


def _default_now() -> str:
    return datetime.now(dt_timezone.utc).astimezone().isoformat()
