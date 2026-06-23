from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ai_usage_widget.mobile_summary import build_mobile_summary
from ai_usage_widget.snapshot_builder import build_snapshot


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "cloudflare" / "migrations" / "0001_initial_schema.sql"
SEED_PATH = REPO_ROOT / "cloudflare" / "native-worker" / "test" / "seed.sql"
GOLDEN_PATH = REPO_ROOT / "cloudflare" / "native-worker" / "test" / "value_golden.json"
TIMEZONE = "Asia/Shanghai"
FIXED_NOW = "2026-06-03T12:00:00+08:00"

VOLATILE_FIELDS = {
    "accepted_at",
    "generated_at",
    "mtime",
    "path",
    "size_bytes",
    "updated_at",
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
    ("summary-week-observed-limits", "/api/summary?date=2026-06-03&period=week"),
    ("mobile-summary-week-observed-limits", "/api/mobile/summary?date=2026-06-03&period=week"),
]


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "value-parity.sqlite"
        with sqlite3.connect(db_path) as conn:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.executescript(SEED_PATH.read_text(encoding="utf-8"))

        records = [
            record(name=name, request_path=request_path, db_path=db_path, temp_dir=Path(temp_dir))
            for name, request_path in REQUESTS
        ]

    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(
        json.dumps(records, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def record(*, name: str, request_path: str, db_path: Path, temp_dir: Path) -> dict[str, Any]:
    parsed = urlparse(request_path)
    params = parse_qs(parsed.query)
    payload = build_payload(parsed.path, params, db_path, temp_dir)
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


def build_payload(path: str, params: dict[str, list[str]], db_path: Path, temp_dir: Path) -> dict[str, Any]:
    snapshot = build_snapshot_payload(
        db_path=db_path,
        output_path=temp_dir / "request-snapshot.json",
        date_str=single(params, "date", "2026-06-03"),
        period=single(params, "period", "today"),
        machine_filter=optional_single(params, "machine"),
        account_filter=optional_single(params, "account"),
    )
    snapshot = with_machine_source_ids(snapshot)
    if path == "/api/mobile/summary":
        return build_mobile_summary(snapshot)
    return snapshot


def build_snapshot_payload(
    *,
    db_path: Path,
    output_path: Path,
    date_str: str,
    period: str,
    machine_filter: str | None,
    account_filter: str | None,
) -> dict[str, Any]:
    build_snapshot(
        db_path=str(db_path),
        output_path=str(output_path),
        date_str=date_str,
        timezone_str=TIMEZONE,
        current_time_str=FIXED_NOW,
        period=period,
        machine_filter=machine_filter,
        account_filter=account_filter,
    )
    return json.loads(output_path.read_text(encoding="utf-8"))


def single(params: dict[str, list[str]], name: str, default: str) -> str:
    values = params.get(name)
    if not values:
        return default
    return values[0]


def optional_single(params: dict[str, list[str]], name: str) -> str | None:
    values = params.get(name)
    if not values:
        return None
    return values[0]


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


def mask_volatile(value: Any, field_name: str = "") -> Any:
    if field_name in VOLATILE_FIELDS or field_name.endswith("_path"):
        return "<masked>"
    if isinstance(value, list):
        return [mask_volatile(item) for item in value]
    if isinstance(value, dict):
        return {key: mask_volatile(item, key) for key, item in value.items()}
    return value


if __name__ == "__main__":
    main()
