from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from ai_usage_widget import server_services
from ai_usage_widget.auth import TokenAuthenticator
from ai_usage_widget.mobile_summary import build_mobile_summary
from ai_usage_widget.server_services import handle_ingest_limits_payload, handle_ingest_payload
from ai_usage_widget.snapshot_builder import build_snapshot


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "native_worker_ingest_payloads.json"
GOLDEN_PATH = REPO_ROOT / "cloudflare" / "native-worker" / "test" / "ingest_value_golden.json"

VOLATILE_FIELDS = {
    "accepted_at",
    "generated_at",
    "mtime",
    "path",
    "size_bytes",
    "updated_at",
    "last_seen_at",
}

REQUESTS = [
    ("summary-today", "/api/summary?date=2026-06-03&period=today"),
    ("mobile-summary-today", "/api/mobile/summary?date=2026-06-03&period=today"),
    ("summary-week", "/api/summary?date=2026-06-03&period=week"),
    ("mobile-summary-week", "/api/mobile/summary?date=2026-06-03&period=week"),
    ("summary-month", "/api/summary?date=2026-06-03&period=month"),
    ("mobile-summary-month", "/api/mobile/summary?date=2026-06-03&period=month"),
    ("summary-all", "/api/summary?date=2026-06-03&period=all"),
    ("mobile-summary-all", "/api/mobile/summary?date=2026-06-03&period=all"),
    ("summary-week-machine-filter", "/api/summary?date=2026-06-03&period=week&machine=macbook-pro"),
    ("mobile-summary-week-machine-filter", "/api/mobile/summary?date=2026-06-03&period=week&machine=linux-dev"),
    ("summary-week-account-filter", "/api/summary?date=2026-06-03&period=week&account=alice"),
    ("mobile-summary-week-account-filter", "/api/mobile/summary?date=2026-06-03&period=week&account=bob"),
]


def main() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    timezone = str(fixture["timezone"])
    current_time = str(fixture["current_time"])
    token = "contract-test-token"
    authenticator = TokenAuthenticator.from_values(token)
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "native-ingest-parity.sqlite"
        latest_path = Path(temp_dir) / "latest.json"
        fd = os.open(db_path, os.O_CREAT | os.O_RDWR)
        os.close(fd)
        for payload in fixture["ingest_payloads"]:
            with patch.object(server_services, "datetime", _frozen_datetime(str(payload["observed_at"]))):
                handle_ingest_payload(
                    payload,
                    token=token,
                    authenticator=authenticator,
                    db_path=str(db_path),
                    latest_path=str(latest_path),
                    timezone=timezone,
                )
        for payload in fixture["limits_payloads"]:
            handle_ingest_limits_payload(
                payload,
                token=token,
                authenticator=authenticator,
                db_path=str(db_path),
                latest_path=str(latest_path),
                timezone=timezone,
            )
        records = [
            record(
                name=name,
                request_path=request_path,
                db_path=db_path,
                temp_dir=Path(temp_dir),
                timezone=timezone,
                current_time=current_time,
            )
            for name, request_path in REQUESTS
        ]
    GOLDEN_PATH.write_text(
        json.dumps(records, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _frozen_datetime(iso_value: str) -> type[datetime]:
    observed_at = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            if tz is None:
                return observed_at.replace(tzinfo=None)
            return observed_at.astimezone(tz)

    return FrozenDateTime


def record(
    *,
    name: str,
    request_path: str,
    db_path: Path,
    temp_dir: Path,
    timezone: str,
    current_time: str,
) -> dict[str, Any]:
    parsed = urlparse(request_path)
    params = parse_qs(parsed.query)
    payload = build_payload(parsed.path, params, db_path, temp_dir, timezone, current_time)
    return {
        "name": name,
        "request": {
            "method": "GET",
            "path": request_path,
            "auth": True,
        },
        "response": {
            "status": 200,
            "content_type": "application/json",
            "location": None,
            "body": mask_volatile(payload),
        },
    }


def build_payload(
    path: str,
    params: dict[str, list[str]],
    db_path: Path,
    temp_dir: Path,
    timezone: str,
    current_time: str,
) -> dict[str, Any]:
    output_path = temp_dir / "request-snapshot.json"
    build_snapshot(
        db_path=str(db_path),
        output_path=str(output_path),
        date_str=single(params, "date", "2026-06-03"),
        timezone_str=timezone,
        current_time_str=current_time,
        period=single(params, "period", "today"),
        machine_filter=optional_single(params, "machine"),
        account_filter=optional_single(params, "account"),
    )
    snapshot = json.loads(output_path.read_text(encoding="utf-8"))
    snapshot = with_machine_source_ids(snapshot)
    if path == "/api/mobile/summary":
        return build_mobile_summary(snapshot)
    return snapshot


def single(params: dict[str, list[str]], name: str, default: str) -> str:
    values = params.get(name)
    return values[0] if values else default


def optional_single(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    return values[0] if values else None


def with_machine_source_ids(snapshot: dict[str, Any]) -> dict[str, Any]:
    groups = snapshot.get("groups")
    if not isinstance(groups, dict):
        return snapshot
    machines = groups.get("by_machine")
    if not isinstance(machines, list):
        return snapshot
    for machine in machines:
        if not isinstance(machine, dict):
            continue
        source_ids = set(str(source_id) for source_id in machine.get("source_ids") or [])
        users = machine.get("users")
        if isinstance(users, list):
            for user in users:
                if not isinstance(user, dict):
                    continue
                source_ids.update(str(source_id) for source_id in user.get("source_ids") or [])
        if source_ids:
            machine["source_ids"] = sorted(source_ids)
    return snapshot


def mask_volatile(value: Any, field_name: str = "", parent_name: str = "") -> Any:
    if field_name in VOLATILE_FIELDS or field_name.endswith("_path"):
        return "<masked>"
    if parent_name in {"source_status", "sources"} and field_name in {
        "observed_at",
        "last_observed_at",
        "last_pushed_at",
    }:
        return "<masked>"
    if isinstance(value, list):
        return [mask_volatile(item, parent_name, field_name) for item in value]
    if isinstance(value, dict):
        return {key: mask_volatile(item, key, parent_name) for key, item in value.items()}
    return value


if __name__ == "__main__":
    main()
