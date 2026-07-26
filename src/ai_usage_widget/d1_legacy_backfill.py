from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence


DAILY_PROVENANCE = "historical_ccusage_fallback_v1"
HOURLY_PROVENANCE = "legacy_hourly_archive_backfill_v1"
MIN_START_DATE = "2026-05-18"
LEGACY_TABLES = ("usage_daily", "usage_daily_models", "usage_hourly", "usage_blocks")
LEDGER_TABLES = (
    "usage_hourly_facts",
    "usage_hourly_models",
    "usage_hourly_rollups",
    "usage_daily_rollups",
)


@dataclass(frozen=True)
class BackfillOptions:
    start_date: str
    end_date: str
    as_of_date: str
    timezone: str = "Asia/Shanghai"
    batch_size: int = 500
    identity_overrides: dict[str, dict[str, str]] = field(default_factory=dict)

    def validate(self) -> None:
        start = _date(self.start_date)
        end = _date(self.end_date)
        _date(self.as_of_date)
        if start < _date(MIN_START_DATE):
            raise ValueError(f"start_date must be on or after {MIN_START_DATE}")
        if end < start:
            raise ValueError("end_date must be on or after start_date")
        if self.timezone != "Asia/Shanghai":
            raise ValueError("this migration contract currently supports only Asia/Shanghai")
        if not 1 <= self.batch_size <= 1000:
            raise ValueError("batch_size must be between 1 and 1000")


@dataclass
class BackfillPlan:
    options: BackfillOptions
    daily_rows: list[dict[str, Any]]
    hourly_rows: list[dict[str, Any]]
    unresolved_identities: list[dict[str, str]]
    batches: list[list[tuple[str, tuple[Any, ...]]]]
    estimated_rows_read: int
    legacy_writes: bool = False
    model_rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ApplyResult:
    rows_written: int
    batches_applied: int


def build_plan(conn: sqlite3.Connection, options: BackfillOptions) -> BackfillPlan:
    options.validate()
    conn.row_factory = sqlite3.Row
    candidates = _legacy_candidates(conn, options)
    mappings, unresolved = _resolve_identities(conn, candidates, options.identity_overrides)
    estimated_reads = _estimated_rows_read(conn, options)
    if unresolved:
        return BackfillPlan(options, [], [], unresolved, [], estimated_reads)

    daily_rows = [
        _daily_row(row, mappings[(row["source_id"], row["agent"])], options)
        for row in candidates["daily"]
    ]
    hourly_rows = [
        _hourly_row(row, mappings[(row["source_id"], row["agent"])], options)
        for row in candidates["hourly"]
    ]
    operation_units: list[list[tuple[str, tuple[Any, ...]]]] = []
    for row in daily_rows:
        operation_units.append([_daily_operation(row)])
    for row in hourly_rows:
        operation_units.append([
            _hourly_fact_operation(row),
            _hourly_rollup_operation(row),
        ])
    batches = _pack_batches(operation_units, options.batch_size)
    return BackfillPlan(options, daily_rows, hourly_rows, [], batches, estimated_reads)


def _pack_batches(
    units: Sequence[list[tuple[str, tuple[Any, ...]]]],
    batch_size: int,
) -> list[list[tuple[str, tuple[Any, ...]]]]:
    batches: list[list[tuple[str, tuple[Any, ...]]]] = []
    current: list[tuple[str, tuple[Any, ...]]] = []
    for unit in units:
        if current and len(current) + len(unit) > batch_size:
            batches.append(current)
            current = []
        current.extend(unit)
    if current:
        batches.append(current)
    return batches


def apply_plan(
    conn: sqlite3.Connection,
    plan: BackfillPlan,
    *,
    batch_indexes: Sequence[int] | None = None,
) -> ApplyResult:
    if plan.unresolved_identities:
        raise ValueError("identity mapping is unresolved; refusing to apply")
    indexes = list(batch_indexes) if batch_indexes is not None else list(range(len(plan.batches)))
    before = conn.total_changes
    for index in indexes:
        batch = plan.batches[index]
        with conn:
            for sql, params in batch:
                conn.execute(sql, params)
    return ApplyResult(rows_written=conn.total_changes - before, batches_applied=len(indexes))


def render_report(conn: sqlite3.Connection, plan: BackfillPlan) -> dict[str, Any]:
    options = plan.options
    old_scope_rows = _old_daily_rows(conn, options)
    new_scope_rows = _effective_daily_rows(conn, options)
    parity_options = replace(options, end_date=max(options.end_date, options.as_of_date))
    old_rows = _old_daily_rows(conn, parity_options)
    new_rows = _effective_daily_rows(conn, parity_options)
    mapping = _mapping_for_report(conn, options.identity_overrides)
    daily = _differences(old_scope_rows, new_scope_rows, ("date", "source_id"))
    periods = {
        period: {
            "legacy_tokens": _period_total(old_rows, period, options.as_of_date),
            "ledger_tokens": _period_total(new_rows, period, options.as_of_date),
        }
        for period in ("today", "week", "month", "all")
    }

    for values in periods.values():
        values["difference_tokens"] = values["ledger_tokens"] - values["legacy_tokens"]

    machine_old = _group_by_identity(old_rows, mapping, "machine_id")
    machine_new = _group_by_identity(new_rows, mapping, "machine_id")
    system_old = _group_by_identity(old_rows, mapping, "os_user")
    system_new = _group_by_identity(new_rows, mapping, "os_user")
    ai_account_old = _group_by_identity(old_rows, mapping, "ai_account_id")
    ai_account_new = _group_by_identity(new_rows, mapping, "ai_account_id")
    logical_writes = len(plan.daily_rows) + (2 * len(plan.hourly_rows))
    return {
        "scope": {
            "start_date": options.start_date,
            "end_date": options.end_date,
            "as_of_date": options.as_of_date,
            "timezone": options.timezone,
        },
        "status": "blocked_identity_mapping" if plan.unresolved_identities else "ready",
        "unresolved_identities": plan.unresolved_identities,
        "parity": periods,
        "daily_differences": daily,
        "filters": {
            "machines": _group_differences(machine_old, machine_new),
            "system_accounts": _group_differences(system_old, system_new),
            "ai_accounts": _group_differences(ai_account_old, ai_account_new),
        },
        "table_counts": {
            "legacy": {table: _count(conn, table) for table in LEGACY_TABLES},
            "ledger": {table: _count(conn, table) for table in LEDGER_TABLES},
        },
        "plan": {
            "daily_fallback_rows": len(plan.daily_rows),
            "hourly_fact_rows": len(plan.hourly_rows),
            "model_rows": 0,
            "batch_count": len(plan.batches),
            "batch_size": options.batch_size,
        },
        "estimated_d1": {
            "rows_read": plan.estimated_rows_read,
            "rows_written": logical_writes,
            "rows_written_conservative_with_indexes": (
                len(plan.daily_rows) * 2 + len(plan.hourly_rows) * 9
            ),
            "actual_rows_read": None,
            "actual_rows_written": None,
            "note": "Actual billed rows must be copied from wrangler D1 JSON metadata.",
        },
        "model_breakdown_user_impact": (
            "Backfilled dates keep total usage and filters, but model breakdown remains empty."
        ),
    }


def summarize_d1_meta(payloads: Iterable[Any]) -> dict[str, int]:
    totals = {"rows_read": 0, "rows_written": 0}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            meta = value.get("meta")
            if isinstance(meta, dict):
                totals["rows_read"] += int(meta.get("rows_read") or 0)
                totals["rows_written"] += int(meta.get("rows_written") or 0)
            for key, child in value.items():
                if key != "meta":
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for payload in payloads:
        visit(payload)
    return totals


def emit_sql(plan: BackfillPlan, output_dir: Path) -> list[Path]:
    if plan.unresolved_identities:
        raise ValueError("identity mapping is unresolved; refusing to emit write SQL")
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index, batch in enumerate(plan.batches, start=1):
        path = output_dir / f"apply-{index:04d}.sql"
        statements = [
            "-- Generated by d1_legacy_backfill; new ledger tables only.",
            *[_literal_sql(sql, params) + ";" for sql, params in batch],
            "",
        ]
        path.write_text("\n".join(statements))
        paths.append(path)
    rollback = output_dir / "rollback.sql"
    rollback.write_text(_rollback_sql(plan))
    paths.append(rollback)
    return paths


def _legacy_candidates(
    conn: sqlite3.Connection, options: BackfillOptions
) -> dict[str, list[Any]]:
    params = (options.start_date, options.end_date)
    raw_daily = conn.execute(
        """
        SELECT d.*
        FROM usage_daily d
        WHERE d.date >= ? AND d.date <= ?
          AND NOT EXISTS (
            SELECT 1 FROM usage_daily_rollups r
            WHERE r.date = d.date AND r.source_id = d.source_id AND r.agent = d.agent
          )
        ORDER BY d.date, d.source_id, d.agent
        """,
        params,
    ).fetchall()
    daily = [dict(row) for row in raw_daily]
    hourly = conn.execute(
        """
        SELECT h.*
        FROM usage_hourly h
        WHERE substr(h.hour, 1, 10) >= ? AND substr(h.hour, 1, 10) <= ?
          AND NOT EXISTS (
            SELECT 1 FROM usage_hourly_facts f
            WHERE f.window_start = h.hour AND f.source_id = h.source_id AND f.agent = h.agent
          )
        ORDER BY h.hour, h.source_id, h.agent
        """,
        params,
    ).fetchall()
    return {"daily": daily, "hourly": hourly}


def _resolve_identities(
    conn: sqlite3.Connection,
    candidates: dict[str, list[Any]],
    overrides: dict[str, dict[str, str]],
) -> tuple[dict[tuple[str, str], dict[str, str]], list[dict[str, str]]]:
    keys = sorted(
        {
            (str(row["source_id"]), str(row["agent"]))
            for rows in candidates.values()
            for row in rows
        }
    )
    mappings: dict[tuple[str, str], dict[str, str]] = {}
    unresolved: list[dict[str, str]] = []
    for row in candidates["daily"]:
        if str(row["agent"]).lower() != "all":
            continue
        if conn.execute(
            """
            SELECT 1 FROM usage_daily_rollups
            WHERE date = ? AND source_id = ? AND agent <> 'all'
            LIMIT 1
            """,
            (row["date"], row["source_id"]),
        ).fetchone():
            unresolved.append(_unresolved(
                str(row["source_id"]),
                str(row["agent"]),
                f"all-agent row overlaps detailed identities on {row['date']}",
            ))
    for source_id, agent in keys:
        override = overrides.get(f"{source_id}|{agent}", {})
        identity = conn.execute(
            """
            SELECT s.machine, s.host, s.os_user, s.platform,
                   m.machine_id, m.machine_name
            FROM source_identities s
            LEFT JOIN machines m ON m.machine_name = s.machine
            WHERE s.source_id = ?
            """,
            (source_id,),
        ).fetchall()
        fact_identity = conn.execute(
            """
            SELECT DISTINCT machine_id, os_user, ai_provider, ai_account_id
            FROM usage_hourly_facts
            WHERE source_id = ? AND agent = ?
            """,
            (source_id, agent),
        ).fetchall()
        accounts = {
            (str(row["ai_provider"]), str(row["ai_account_id"]))
            for row in fact_identity
        }
        machine_ids = {
            str(row["machine_id"]) for row in fact_identity if row["machine_id"]
        }
        os_users = {str(row["os_user"]) for row in fact_identity if row["os_user"]}
        if len(identity) != 1:
            unresolved.append(_unresolved(source_id, agent, "missing or ambiguous source identity"))
            continue
        source = identity[0]
        if len(machine_ids) > 1 and not override.get("machine_id"):
            unresolved.append(_unresolved(source_id, agent, "multiple machines require an explicit identity map"))
            continue
        if len(os_users) > 1 and not override.get("os_user"):
            unresolved.append(_unresolved(source_id, agent, "multiple OS users require an explicit identity map"))
            continue
        machine_id = override.get("machine_id") or (
            next(iter(machine_ids)) if len(machine_ids) == 1 else str(source["machine_id"] or "")
        )
        os_user = override.get("os_user") or (
            next(iter(os_users)) if len(os_users) == 1 else str(source["os_user"] or "")
        )
        provider = override.get("ai_provider")
        account_id = override.get("ai_account_id")
        if not provider or not account_id:
            if len(accounts) == 1:
                provider, account_id = next(iter(accounts))
            elif len(accounts) > 1:
                unresolved.append(_unresolved(source_id, agent, "multiple accounts require an explicit identity map"))
                continue
            else:
                unresolved.append(_unresolved(source_id, agent, "missing account requires an explicit identity map"))
                continue
        if not machine_id or not os_user:
            unresolved.append(_unresolved(source_id, agent, "missing machine or OS user mapping"))
            continue
        if not conn.execute(
            "SELECT 1 FROM machines WHERE machine_id = ?",
            (machine_id,),
        ).fetchone():
            unresolved.append(_unresolved(source_id, agent, "mapped machine_id does not exist"))
            continue
        if not conn.execute(
            "SELECT 1 FROM ai_accounts WHERE provider = ? AND account_id = ?",
            (provider, account_id),
        ).fetchone():
            unresolved.append(_unresolved(source_id, agent, "mapped AI account does not exist"))
            continue
        mappings[(source_id, agent)] = {
            "machine_id": machine_id,
            "machine_name": str(source["machine"] or source["host"] or machine_id),
            "os_user": os_user,
            "platform": str(source["platform"] or "unknown"),
            "ai_provider": provider,
            "ai_account_id": account_id,
        }
    return mappings, unresolved


def _daily_row(
    row: Any, identity: dict[str, str], options: BackfillOptions
) -> dict[str, Any]:
    day = str(row["date"])
    return {
        **identity,
        "date": day,
        "bucket_start": f"{day}T00:00:00+08:00",
        "bucket_end": f"{day}T23:59:59+08:00",
        "source_id": str(row["source_id"]),
        "agent": str(row["agent"]),
        "client": "legacy_daily_archive",
        "attribution_confidence": "legacy_identity_mapped",
        "provenance": DAILY_PROVENANCE,
        **_usage(row),
        "reasoning_output_tokens": 0,
        "event_count": 0,
        "session_count": 0,
        "fact_count": 0,
    }


def _hourly_row(
    row: Any, identity: dict[str, str], options: BackfillOptions
) -> dict[str, Any]:
    start = str(row["hour"])
    end = (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat()
    stable = f"{row['source_id']}|{row['agent']}|{start}|{HOURLY_PROVENANCE}"
    return {
        **identity,
        "fact_id": "legacy-hourly-v1-" + hashlib.sha256(stable.encode()).hexdigest(),
        "source_id": str(row["source_id"]),
        "agent": str(row["agent"]),
        "client": "legacy_hourly_archive",
        "window_start": start,
        "window_end": end,
        "timezone": options.timezone,
        "attribution_confidence": "legacy_identity_mapped",
        "provenance": HOURLY_PROVENANCE,
        **_usage(row),
        "reasoning_output_tokens": 0,
        "event_count": 0,
        "session_count": 0,
        "account_evidence_json": json.dumps({"source": "reviewed_legacy_identity_map"}),
        "metadata_json": json.dumps({"backfill": HOURLY_PROVENANCE}),
        "first_seen_at": str(row["first_seen_at"]),
        "last_seen_at": str(row["last_seen_at"]),
        "fact_count": 1,
    }


def _usage(row: Any) -> dict[str, Any]:
    return {
        "input_tokens": int(row["input_tokens"] or 0),
        "output_tokens": int(row["output_tokens"] or 0),
        "cache_creation_tokens": int(row["cache_creation_tokens"] or 0),
        "cache_read_tokens": int(row["cache_read_tokens"] or 0),
        "total_tokens": int(row["total_tokens"] or 0),
        "total_cost": row["total_cost"],
    }


def _daily_operation(row: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    columns = (
        "date", "bucket_start", "bucket_end", "source_id", "machine_id", "os_user",
        "ai_provider", "ai_account_id", "agent", "client", "attribution_confidence",
        "provenance", "input_tokens", "output_tokens", "cache_creation_tokens",
        "cache_read_tokens", "reasoning_output_tokens", "total_tokens", "event_count",
        "session_count", "fact_count",
    )
    return _upsert_operation("usage_daily_rollups", columns, row)


def _hourly_rollup_operation(row: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    converted = {
        **row,
        "bucket_start": row["window_start"],
        "bucket_end": row["window_end"],
    }
    columns = (
        "bucket_start", "bucket_end", "source_id", "machine_id", "os_user",
        "ai_provider", "ai_account_id", "agent", "client", "attribution_confidence",
        "provenance", "input_tokens", "output_tokens", "cache_creation_tokens",
        "cache_read_tokens", "reasoning_output_tokens", "total_tokens", "event_count",
        "session_count", "fact_count",
    )
    return _upsert_operation("usage_hourly_rollups", columns, converted)


def _hourly_fact_operation(row: dict[str, Any]) -> tuple[str, tuple[Any, ...]]:
    columns = (
        "fact_id", "source_id", "machine_id", "os_user", "ai_provider",
        "ai_account_id", "agent", "client", "window_start", "window_end", "timezone",
        "input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens",
        "reasoning_output_tokens", "total_tokens", "total_cost", "event_count",
        "session_count", "attribution_confidence", "provenance",
        "account_evidence_json", "metadata_json", "first_seen_at", "last_seen_at",
    )
    return _upsert_operation("usage_hourly_facts", columns, row)


def _upsert_operation(
    table: str, columns: Sequence[str], row: dict[str, Any]
) -> tuple[str, tuple[Any, ...]]:
    values = tuple(row[column] for column in columns)
    assignments = ", ".join(f"{column}=excluded.{column}" for column in columns)
    changed = " OR ".join(f"{table}.{column} IS NOT excluded.{column}" for column in columns)
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)}) "
        f"ON CONFLICT DO UPDATE SET {assignments} WHERE {changed}"
    )
    return sql, values


def _old_daily_rows(conn: sqlite3.Connection, options: BackfillOptions) -> list[dict[str, Any]]:
    legacy = [
        dict(row)
        for row in conn.execute(
        """
        SELECT date, source_id, agent, total_tokens
        FROM usage_daily WHERE date >= ? AND date <= ?
        """,
        (options.start_date, options.end_date),
        ).fetchall()
    ]
    detailed = [
        dict(row)
        for row in conn.execute(
            """
            SELECT date, source_id, agent, machine_id, os_user, ai_account_id,
                   sum(total_tokens) AS total_tokens
            FROM usage_daily_rollups
            WHERE date >= ? AND date <= ? AND provenance <> ?
            GROUP BY date, source_id, agent, machine_id, os_user, ai_account_id
            """,
            (options.start_date, options.end_date, DAILY_PROVENANCE),
        ).fetchall()
    ]
    detailed_by_key = {
        (row["date"], row["source_id"], row["agent"]) for row in detailed
    }
    detailed_by_source_date: dict[tuple[str, str], int] = {}
    for row in detailed:
        key = (row["date"], row["source_id"])
        detailed_by_source_date[key] = detailed_by_source_date.get(key, 0) + int(row["total_tokens"])
    result = list(detailed)
    for row in legacy:
        key = (row["date"], row["source_id"], row["agent"])
        if key in detailed_by_key:
            continue
        if str(row["agent"]).lower() == "all":
            residual = max(
                int(row["total_tokens"]) - detailed_by_source_date.get((row["date"], row["source_id"]), 0),
                0,
            )
            if residual:
                result.append({**row, "total_tokens": residual})
        else:
            result.append(row)
    return result


def _effective_daily_rows(conn: sqlite3.Connection, options: BackfillOptions) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT date, source_id, agent, machine_id, os_user, ai_account_id,
               provenance, total_tokens
        FROM usage_daily_rollups WHERE date >= ? AND date <= ?
        """,
        (options.start_date, options.end_date),
    ).fetchall()
    authoritative_source_dates = {
        (str(row["date"]), str(row["source_id"]))
        for row in rows
        if row["provenance"] == DAILY_PROVENANCE
        and str(row["agent"]).lower() == "all"
    }
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for raw in rows:
        row = dict(raw)
        if (
            (row["date"], row["source_id"]) in authoritative_source_dates
            and row["provenance"] != DAILY_PROVENANCE
        ):
            continue
        grouped.setdefault((row["date"], row["source_id"], row["agent"]), []).append(row)
    result: list[dict[str, Any]] = []
    for key, values in grouped.items():
        fallback = [row for row in values if row["provenance"] == DAILY_PROVENANCE]
        chosen = fallback if fallback else values
        result.extend(chosen)
    return result


def _differences(
    old_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
    keys: Sequence[str],
) -> list[dict[str, Any]]:
    old = _totals(old_rows, keys)
    new = _totals(new_rows, keys)
    result = []
    for key in sorted(set(old) | set(new)):
        difference = new.get(key, 0) - old.get(key, 0)
        if difference:
            result.append({
                **dict(zip(keys, key)),
                "legacy_tokens": old.get(key, 0),
                "ledger_tokens": new.get(key, 0),
                "difference_tokens": difference,
            })
    return result


def _totals(rows: Iterable[dict[str, Any]], keys: Sequence[str]) -> dict[tuple[Any, ...], int]:
    result: dict[tuple[Any, ...], int] = {}
    for row in rows:
        key = tuple(row[name] for name in keys)
        result[key] = result.get(key, 0) + int(row["total_tokens"])
    return result


def _period_total(rows: list[dict[str, Any]], period: str, as_of: str) -> int:
    end = _date(as_of)
    if period == "today":
        start = end
    elif period == "week":
        start = end - timedelta(days=6)
    elif period == "month":
        start = end - timedelta(days=29)
    else:
        start = date.min
    return sum(
        int(row["total_tokens"])
        for row in rows
        if start <= _date(str(row["date"])) <= end
    )


def _mapping_for_report(
    conn: sqlite3.Connection, overrides: dict[str, dict[str, str]]
) -> dict[tuple[str, str], dict[str, str]]:
    candidates = {
        "daily": conn.execute(
            "SELECT DISTINCT source_id, date, agent FROM usage_daily"
        ).fetchall(),
        "hourly": [],
    }
    mappings, _ = _resolve_identities(conn, candidates, overrides)
    return mappings


def _group_by_identity(
    rows: list[dict[str, Any]],
    mapping: dict[tuple[str, str], dict[str, str]],
    field: str,
) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        direct = str(row.get(field) or "")
        identity = mapping.get((row["source_id"], row["agent"]))
        key = direct or (identity[field] if identity else "")
        if not key:
            continue
        result[key] = result.get(key, 0) + int(row["total_tokens"])
    return result


def _group_differences(old: dict[str, int], new: dict[str, int]) -> dict[str, dict[str, int]]:
    return {
        key: {
            "legacy_tokens": old.get(key, 0),
            "ledger_tokens": new.get(key, 0),
            "difference_tokens": new.get(key, 0) - old.get(key, 0),
        }
        for key in sorted(set(old) | set(new))
    }


def _estimated_rows_read(conn: sqlite3.Connection, options: BackfillOptions) -> int:
    ranged = 0
    for table, expression in (("usage_daily", "date"), ("usage_hourly", "substr(hour, 1, 10)")):
        ranged += int(conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {expression} >= ? AND {expression} <= ?",
            (options.start_date, options.end_date),
        ).fetchone()[0])
    return ranged + sum(
        _count(conn, table)
        for table in ("source_identities", "machines", "usage_hourly_facts", "usage_daily_rollups")
    )


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _unresolved(source_id: str, agent: str, reason: str) -> dict[str, str]:
    return {"source_id": source_id, "agent": agent, "reason": reason}


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _literal_sql(sql: str, params: Sequence[Any]) -> str:
    pieces = sql.split("?")
    if len(pieces) != len(params) + 1:
        raise ValueError("placeholder count does not match parameters")
    result = pieces[0]
    for value, tail in zip(params, pieces[1:]):
        result += _sql_literal(value) + tail
    return result


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _rollback_sql(plan: BackfillPlan) -> str:
    statements = ["-- Removes only exact primary keys emitted by this plan."]
    for row in plan.hourly_rows:
        statements.append(
            f"DELETE FROM usage_hourly_models WHERE fact_id = {_sql_literal(row['fact_id'])};"
        )
        statements.append(
            f"DELETE FROM usage_hourly_facts WHERE fact_id = {_sql_literal(row['fact_id'])} "
            f"AND provenance = {_sql_literal(HOURLY_PROVENANCE)};"
        )
        statements.append(_delete_rollup_sql(
            "usage_hourly_rollups",
            row,
            (
                ("bucket_start", "window_start"), ("source_id", "source_id"),
                ("machine_id", "machine_id"), ("os_user", "os_user"),
                ("ai_provider", "ai_provider"), ("ai_account_id", "ai_account_id"),
                ("agent", "agent"), ("client", "client"),
                ("attribution_confidence", "attribution_confidence"),
                ("provenance", "provenance"),
            ),
        ))
    for row in plan.daily_rows:
        statements.append(_delete_rollup_sql(
            "usage_daily_rollups",
            row,
            (
                ("date", "date"), ("source_id", "source_id"),
                ("machine_id", "machine_id"), ("os_user", "os_user"),
                ("ai_provider", "ai_provider"), ("ai_account_id", "ai_account_id"),
                ("agent", "agent"), ("client", "client"),
                ("attribution_confidence", "attribution_confidence"),
                ("provenance", "provenance"),
            ),
        ))
    statements.append("")
    return "\n".join(statements)


def _delete_rollup_sql(
    table: str,
    row: dict[str, Any],
    columns: Sequence[tuple[str, str]],
) -> str:
    where = " AND ".join(
        f"{column} = {_sql_literal(row[key])}" for column, key in columns
    )
    return f"DELETE FROM {table} WHERE {where};"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plan a bounded D1 legacy-archive to ledger backfill from a read-only export."
    )
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--as-of-date", required=True)
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--identity-map", type=Path)
    parser.add_argument(
        "--actual-meta",
        type=Path,
        nargs="+",
        default=[],
        help="One or more Wrangler --json result files to aggregate actual D1 rows.",
    )
    parser.add_argument(
        "--emit-write-sql",
        type=Path,
        help="Explicitly emit idempotent SQL batches; never executes them.",
    )
    args = parser.parse_args(argv)
    overrides = {}
    if args.identity_map:
        overrides = json.loads(args.identity_map.read_text())
    options = BackfillOptions(
        start_date=args.start_date,
        end_date=args.end_date,
        as_of_date=args.as_of_date,
        timezone=args.timezone,
        batch_size=args.batch_size,
        identity_overrides=overrides,
    )
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        plan = build_plan(conn, options)
        report = render_report(conn, plan)
        if args.actual_meta:
            actual = summarize_d1_meta(
                json.loads(path.read_text()) for path in args.actual_meta
            )
            report["estimated_d1"]["actual_rows_read"] = actual["rows_read"]
            report["estimated_d1"]["actual_rows_written"] = actual["rows_written"]
        if args.emit_write_sql:
            report["sql_files"] = [str(path) for path in emit_sql(plan, args.emit_write_sql)]
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 2 if plan.unresolved_identities else 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
