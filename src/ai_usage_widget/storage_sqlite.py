from __future__ import annotations

import json
import hashlib
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .limits import LimitWindow
from .models import CommandResult, UsageBlockItem, UsageHourlyFact, UsageHourlyItem, UsageItem


def write_sqlite(
    path: str,
    collected_at: str,
    timezone: str,
    run_status: str,
    source_reports: List[Dict[str, Any]],
    items: Iterable[UsageItem],
    hourly_items: Optional[Iterable[UsageHourlyItem]] = None,
    hourly_facts: Optional[Iterable[UsageHourlyFact]] = None,
    block_items: Optional[Iterable[UsageBlockItem]] = None,
    source_identities: Optional[Iterable[Dict[str, Any]]] = None,
    usage_ledger_runs: Optional[List[Dict[str, Any]]] = None,
    usage_hourly_fact_payloads: Optional[List[Dict[str, Any]]] = None,
    accuracy_source_id: Optional[str] = None,
    accuracy_observed_at: Optional[str] = None,
) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        _ensure_schema(conn)
        run_id = _insert_run(conn, collected_at, timezone, run_status)
        for report in source_reports:
            _insert_source_report(conn, run_id, report)
        for identity in source_identities or []:
            _upsert_source_identity(conn, identity, collected_at)
        for item in items:
            _upsert_item(conn, item, collected_at)
        hourly_list = list(hourly_items or [])
        _delete_replaced_codex_hourly_rows(conn, hourly_list)
        for item in hourly_list:
            _upsert_hourly_item(conn, item, collected_at)
        fact_payloads = list(usage_hourly_fact_payloads or [])
        allowed_fact_ids = _ledger_coverage_fact_ids(fact_payloads, usage_ledger_runs or [])
        hourly_fact_list = list(hourly_facts or [])
        if allowed_fact_ids is not None:
            hourly_fact_list = [fact for fact in hourly_fact_list if fact.fact_id in allowed_fact_ids]
            fact_payloads = [fact for fact in fact_payloads if str(fact.get("fact_id") or "") in allowed_fact_ids]
        for fact in hourly_fact_list:
            _upsert_hourly_fact(conn, fact, collected_at)
        for item in block_items or []:
            _upsert_block_item(conn, item, collected_at)
        if accuracy_source_id is not None:
            _update_source_accuracy(
                conn,
                source_id=accuracy_source_id,
                runs=usage_ledger_runs or [],
                facts=fact_payloads,
                observed_at=accuracy_observed_at or collected_at,
            )


def write_limit_windows(path: str, windows: Iterable[LimitWindow], seen_at: str) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        _ensure_schema(conn)
        for window in windows:
            _upsert_limit_window(conn, window, seen_at)


def build_source_report(source: Dict[str, Any], result: CommandResult, status: str) -> Dict[str, Any]:
    return {
        "source_id": source["source_id"],
        "report_type": "daily",
        "command": result.command,
        "status": status,
        "ccusage_version": None,
        "first_period": None,
        "last_period": None,
        "error_type": result.error_type,
        "error_message": _safe_error(result.error_message or result.stderr),
    }


def _update_source_accuracy(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    runs: List[Dict[str, Any]],
    facts: List[Dict[str, Any]],
    observed_at: str,
) -> None:
    reported_agents = [str(run.get("agent")) for run in runs if isinstance(run, dict) and run.get("agent")]
    if reported_agents:
        placeholders = ",".join("?" for _ in reported_agents)
        conn.execute(
            f"""
            UPDATE source_accuracy
            SET accuracy_status='unknown', mode='legacy', matching_full_scans=0,
                scan_complete=0, observed_at=?, last_seen_at=?
            WHERE source_id=? AND agent NOT IN ({placeholders})
            """,
            (observed_at, observed_at, source_id, *reported_agents),
        )
    else:
        conn.execute(
            """
            UPDATE source_accuracy
            SET accuracy_status='unknown', mode='legacy', matching_full_scans=0,
                scan_complete=0, observed_at=?, last_seen_at=?
            WHERE source_id=?
            """,
            (observed_at, observed_at, source_id),
        )

    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("collector"), dict):
            continue
        collector = run["collector"]
        counts = collector.get("counts") if isinstance(collector.get("counts"), dict) else {}
        coverage = collector.get("coverage") if isinstance(collector.get("coverage"), dict) else {}
        agent = str(run.get("agent") or "unknown")
        provenance = str(run.get("provenance") or "unknown")
        coverage_start = str(coverage.get("start")) if coverage.get("start") else None
        coverage_end = str(coverage.get("end")) if coverage.get("end") else None
        report_digest = str(collector.get("report_digest") or "")
        facts_digest = str(run.get("facts_digest") or "")
        computed_digest = _safe_facts_digest(facts, agent, provenance, coverage_start, coverage_end)
        version = str(collector.get("version") or "")
        parser_schema = int(collector.get("parser_schema_version") or 0)
        read_errors = int(counts.get("read_errors") or 0)
        unresolved = int(counts.get("unresolved_mismatch") or 0)
        scan_complete = collector.get("scan_complete") is True
        mode = str(collector.get("mode") or "unknown")
        complete = (
            mode == "full-rescan"
            and scan_complete
            and read_errors == 0
            and unresolved == 0
            and bool(version)
            and parser_schema > 0
            and bool(report_digest)
            and bool(facts_digest)
            and facts_digest == computed_digest
        )
        previous_row = conn.execute(
            """
            SELECT provenance, collector_version, parser_schema_version, coverage_start, coverage_end,
                   report_digest, facts_digest, scan_complete, read_errors, unresolved_mismatch,
                   matching_full_scans, accuracy_status, verified_at, observed_at
            FROM source_accuracy WHERE source_id=? AND agent=?
            """,
            (source_id, agent),
        ).fetchone()
        same = bool(previous_row) and complete and (
            str(previous_row[0] or "") == provenance
            and str(previous_row[1] or "") == version
            and int(previous_row[2] or 0) == parser_schema
            and previous_row[3] == coverage_start
            and previous_row[4] == coverage_end
            and str(previous_row[5] or "") == report_digest
            and str(previous_row[6] or "") == facts_digest
            and int(previous_row[7] or 0) == 1
            and int(previous_row[8] or 0) == 0
            and int(previous_row[9] or 0) == 0
        )
        replayed_scan = same and str(previous_row[13] or "") == observed_at
        if replayed_scan:
            matching = int(previous_row[10] or 0)
        else:
            matching = min(int(previous_row[10] or 0) + 1, 2) if same else (1 if complete else 0)
        has_coverage = bool(coverage_start and coverage_end and coverage_start < coverage_end)
        if replayed_scan:
            status = str(previous_row[11] or "unverified")
            verified_at = previous_row[12]
        else:
            status = "verified" if matching >= 2 and has_coverage else "unverified"
            verified_at = (previous_row[12] if previous_row and previous_row[12] else observed_at) if status == "verified" else None
        if mode == "incremental" and previous_row and previous_row[11] == "verified" and str(previous_row[0] or "") == provenance and str(previous_row[1] or "") == version and int(previous_row[2] or 0) == parser_schema:
            matching = int(previous_row[10] or 2)
            status = "verified"
            verified_at = previous_row[12] or observed_at
        metadata_json = json.dumps(collector, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        conn.execute(
            """
            INSERT INTO source_accuracy (
              source_id, agent, provenance, collector_version, parser_schema_version, mode,
              lookback_hours, coverage_start, coverage_end, report_digest, facts_digest,
              scan_complete, read_errors, unresolved_mismatch, matching_full_scans,
              accuracy_status, verified_at, metadata_json, observed_at, first_seen_at, last_seen_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(source_id, agent) DO UPDATE SET
              provenance=excluded.provenance, collector_version=excluded.collector_version,
              parser_schema_version=excluded.parser_schema_version, mode=excluded.mode,
              lookback_hours=excluded.lookback_hours, coverage_start=excluded.coverage_start,
              coverage_end=excluded.coverage_end, report_digest=excluded.report_digest,
              facts_digest=excluded.facts_digest, scan_complete=excluded.scan_complete,
              read_errors=excluded.read_errors, unresolved_mismatch=excluded.unresolved_mismatch,
              matching_full_scans=excluded.matching_full_scans, accuracy_status=excluded.accuracy_status,
              verified_at=excluded.verified_at, metadata_json=excluded.metadata_json,
              observed_at=excluded.observed_at, last_seen_at=excluded.last_seen_at
            """,
            (
                source_id, agent, provenance, version, parser_schema, mode,
                float(collector["lookback_hours"]) if collector.get("lookback_hours") is not None else None,
                coverage_start, coverage_end, report_digest, facts_digest, int(scan_complete),
                read_errors, unresolved, matching, status, verified_at, metadata_json,
                observed_at, observed_at, observed_at,
            ),
        )
        if complete and matching >= 2 and has_coverage:
            matching_ids = [
                str(fact.get("fact_id"))
                for fact in facts
                if str(fact.get("agent") or "") == agent
                and str(fact.get("provenance") or "") == provenance
                and coverage_start <= str(fact.get("window_start") or "") < coverage_end
            ]
            for fact_id in matching_ids:
                conn.execute("UPDATE usage_hourly_facts SET last_seen_at=? WHERE fact_id=?", (observed_at, fact_id))
            conn.execute(
                """
                DELETE FROM usage_hourly_models WHERE fact_id IN (
                  SELECT fact_id FROM usage_hourly_facts
                  WHERE source_id=? AND agent=? AND provenance=?
                    AND window_start>=? AND window_start<? AND last_seen_at IS NOT ?
                )
                """,
                (source_id, agent, provenance, coverage_start, coverage_end, observed_at),
            )
            conn.execute(
                """
                DELETE FROM usage_hourly_facts
                WHERE source_id=? AND agent=? AND provenance=?
                  AND window_start>=? AND window_start<? AND last_seen_at IS NOT ?
                """,
                (source_id, agent, provenance, coverage_start, coverage_end, observed_at),
            )


def _safe_facts_digest(
    facts: List[Dict[str, Any]],
    agent: str,
    provenance: str,
    coverage_start: str | None,
    coverage_end: str | None,
) -> str:
    keys = (
        "fact_id", "agent", "client", "window_start", "window_end", "usage",
        "event_count", "session_count", "attribution_confidence", "provenance",
    )
    canonical = [
        {key: fact.get(key) for key in keys}
        for fact in facts
        if str(fact.get("agent") or "") == agent
        and str(fact.get("provenance") or "") == provenance
        and (not coverage_start or str(fact.get("window_start") or "") >= coverage_start)
        and (not coverage_end or str(fact.get("window_start") or "") < coverage_end)
    ]
    canonical.sort(key=lambda row: str(row.get("fact_id") or ""))
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _ledger_coverage_fact_ids(
    facts: List[Dict[str, Any]],
    runs: List[Dict[str, Any]],
) -> set[str] | None:
    authoritative: dict[tuple[str, str], tuple[str, str]] = {}
    for run in runs:
        if not isinstance(run, dict) or not isinstance(run.get("collector"), dict):
            continue
        collector = run["collector"]
        coverage = collector.get("coverage") if isinstance(collector.get("coverage"), dict) else {}
        start = str(coverage.get("start")) if coverage.get("start") else ""
        end = str(coverage.get("end")) if coverage.get("end") else ""
        if collector.get("mode") == "full-rescan" and start and end and start < end:
            authoritative[(str(run.get("agent") or ""), str(run.get("provenance") or ""))] = (start, end)
    if not authoritative:
        return None
    allowed: set[str] = set()
    for fact in facts:
        key = (str(fact.get("agent") or ""), str(fact.get("provenance") or ""))
        coverage = authoritative.get(key)
        window_start = str(fact.get("window_start") or "")
        if coverage is None or coverage[0] <= window_start < coverage[1]:
            allowed.add(str(fact.get("fact_id") or ""))
    return allowed


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS collection_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          collected_at TEXT NOT NULL,
          timezone TEXT NOT NULL,
          collector_version TEXT,
          status TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS source_reports (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id INTEGER NOT NULL,
          source_id TEXT NOT NULL,
          report_type TEXT NOT NULL,
          command TEXT NOT NULL,
          status TEXT NOT NULL,
          ccusage_version TEXT,
          first_period TEXT,
          last_period TEXT,
          error_type TEXT,
          error_message TEXT,
          FOREIGN KEY(run_id) REFERENCES collection_runs(id)
        );

        CREATE TABLE IF NOT EXISTS usage_daily (
          source_id TEXT NOT NULL,
          date TEXT NOT NULL,
          agent TEXT NOT NULL,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
          cache_read_tokens INTEGER NOT NULL DEFAULT 0,
          total_tokens INTEGER NOT NULL DEFAULT 0,
          total_cost REAL,
          metadata_json TEXT,
          raw_json TEXT,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          PRIMARY KEY(source_id, date, agent)
        );

        CREATE TABLE IF NOT EXISTS usage_daily_models (
          source_id TEXT NOT NULL,
          date TEXT NOT NULL,
          agent TEXT NOT NULL,
          model_name TEXT NOT NULL,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
          cache_read_tokens INTEGER NOT NULL DEFAULT 0,
          total_tokens INTEGER NOT NULL DEFAULT 0,
          cost REAL,
          raw_json TEXT,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          PRIMARY KEY(source_id, date, agent, model_name)
        );

        CREATE TABLE IF NOT EXISTS usage_hourly (
          source_id TEXT NOT NULL,
          hour TEXT NOT NULL,
          agent TEXT NOT NULL,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
          cache_read_tokens INTEGER NOT NULL DEFAULT 0,
          total_tokens INTEGER NOT NULL DEFAULT 0,
          total_cost REAL,
          metadata_json TEXT,
          raw_json TEXT,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          PRIMARY KEY(source_id, hour, agent)
        );

        CREATE TABLE IF NOT EXISTS usage_blocks (
          source_id TEXT NOT NULL,
          start_time TEXT NOT NULL,
          end_time TEXT NOT NULL,
          agent TEXT NOT NULL,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
          cache_read_tokens INTEGER NOT NULL DEFAULT 0,
          total_tokens INTEGER NOT NULL DEFAULT 0,
          total_cost REAL,
          metadata_json TEXT,
          raw_json TEXT,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          PRIMARY KEY(source_id, start_time, end_time, agent)
        );

        CREATE TABLE IF NOT EXISTS source_identities (
          source_id TEXT PRIMARY KEY,
          host TEXT,
          machine TEXT,
          os_user TEXT,
          platform TEXT,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS machines (
          machine_id TEXT PRIMARY KEY,
          machine_name TEXT NOT NULL,
          host TEXT,
          platform TEXT NOT NULL,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS os_identities (
          machine_id TEXT NOT NULL,
          os_user TEXT NOT NULL,
          display_name TEXT NOT NULL,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          PRIMARY KEY(machine_id, os_user)
        );

        CREATE TABLE IF NOT EXISTS ai_accounts (
          provider TEXT NOT NULL,
          account_id TEXT NOT NULL,
          account_label TEXT NOT NULL,
          display_name TEXT,
          subscription TEXT,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          PRIMARY KEY(provider, account_id)
        );

        CREATE TABLE IF NOT EXISTS usage_hourly_facts (
          fact_id TEXT PRIMARY KEY,
          source_id TEXT NOT NULL,
          machine_id TEXT NOT NULL,
          os_user TEXT NOT NULL,
          ai_provider TEXT NOT NULL,
          ai_account_id TEXT NOT NULL,
          agent TEXT NOT NULL,
          client TEXT,
          window_start TEXT NOT NULL,
          window_end TEXT NOT NULL,
          timezone TEXT NOT NULL,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
          cache_read_tokens INTEGER NOT NULL DEFAULT 0,
          reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
          total_tokens INTEGER NOT NULL DEFAULT 0,
          total_cost REAL,
          event_count INTEGER NOT NULL DEFAULT 0,
          session_count INTEGER NOT NULL DEFAULT 0,
          attribution_confidence TEXT NOT NULL,
          provenance TEXT NOT NULL,
          account_evidence_json TEXT,
          metadata_json TEXT,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS usage_hourly_models (
          fact_id TEXT NOT NULL,
          model TEXT NOT NULL,
          input_tokens INTEGER NOT NULL DEFAULT 0,
          output_tokens INTEGER NOT NULL DEFAULT 0,
          cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
          cache_read_tokens INTEGER NOT NULL DEFAULT 0,
          reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
          total_tokens INTEGER NOT NULL DEFAULT 0,
          total_cost REAL,
          metadata_json TEXT,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          PRIMARY KEY(fact_id, model)
        );

        CREATE TABLE IF NOT EXISTS source_accuracy (
          source_id TEXT NOT NULL,
          agent TEXT NOT NULL,
          provenance TEXT NOT NULL,
          collector_version TEXT,
          parser_schema_version INTEGER,
          mode TEXT NOT NULL,
          lookback_hours REAL,
          coverage_start TEXT,
          coverage_end TEXT,
          report_digest TEXT,
          facts_digest TEXT,
          scan_complete INTEGER NOT NULL DEFAULT 0,
          read_errors INTEGER NOT NULL DEFAULT 0,
          unresolved_mismatch INTEGER NOT NULL DEFAULT 0,
          matching_full_scans INTEGER NOT NULL DEFAULT 0,
          accuracy_status TEXT NOT NULL,
          verified_at TEXT,
          metadata_json TEXT,
          observed_at TEXT NOT NULL,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          PRIMARY KEY(source_id, agent)
        );

        CREATE TABLE IF NOT EXISTS limit_windows (
          source_id TEXT NOT NULL,
          provider TEXT NOT NULL,
          window TEXT NOT NULL,
          used_percent REAL NOT NULL,
          remaining_percent REAL NOT NULL,
          reset_at TEXT NOT NULL,
          window_duration_minutes INTEGER NOT NULL,
          source_type TEXT NOT NULL,
          confidence TEXT NOT NULL,
          status TEXT NOT NULL,
          observed_at TEXT NOT NULL,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          PRIMARY KEY(source_id, provider, window)
        );

        CREATE INDEX IF NOT EXISTS idx_source_accuracy_status
          ON source_accuracy(accuracy_status, source_id, agent);
        """
    )
    _ensure_column(conn, "usage_daily", "raw_json", "TEXT")
    _ensure_column(conn, "usage_daily_models", "raw_json", "TEXT")
    _ensure_limit_windows_schema(conn)
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_usage_hourly_facts_window
          ON usage_hourly_facts(window_start, window_end);
        CREATE INDEX IF NOT EXISTS idx_usage_hourly_facts_account
          ON usage_hourly_facts(ai_provider, ai_account_id, window_start);
        CREATE INDEX IF NOT EXISTS idx_usage_hourly_facts_machine_user
          ON usage_hourly_facts(machine_id, os_user, window_start);
        CREATE INDEX IF NOT EXISTS idx_usage_hourly_facts_agent
          ON usage_hourly_facts(agent, window_start);
        CREATE INDEX IF NOT EXISTS idx_usage_hourly_facts_source
          ON usage_hourly_facts(source_id, window_start);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_hourly_facts_unique_hour
          ON usage_hourly_facts(
            source_id, agent, client, window_start, window_end,
            ai_provider, ai_account_id, attribution_confidence, provenance
          );
        """
    )



def _insert_run(conn: sqlite3.Connection, collected_at: str, timezone: str, status: str) -> int:
    cursor = conn.execute(
        "INSERT INTO collection_runs (collected_at, timezone, collector_version, status) VALUES (?, ?, ?, ?)",
        (collected_at, timezone, "0.1.0", status),
    )
    return int(cursor.lastrowid)


def _insert_source_report(conn: sqlite3.Connection, run_id: int, report: Dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO source_reports (
          run_id, source_id, report_type, command, status, ccusage_version,
          first_period, last_period, error_type, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            report["source_id"],
            report["report_type"],
            report["command"],
            report["status"],
            report.get("ccusage_version"),
            report.get("first_period"),
            report.get("last_period"),
            report.get("error_type"),
            report.get("error_message"),
        ),
    )


def _upsert_source_identity(conn: sqlite3.Connection, identity: Dict[str, Any], collected_at: str) -> None:
    conn.execute(
        """
        INSERT INTO source_identities (
          source_id, host, machine, os_user, platform, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
          host=excluded.host,
          machine=excluded.machine,
          os_user=excluded.os_user,
          platform=excluded.platform,
          last_seen_at=excluded.last_seen_at
        """,
        (
            identity["source_id"],
            identity.get("host"),
            identity.get("machine"),
            identity.get("os_user"),
            identity.get("platform"),
            collected_at,
            collected_at,
        ),
    )


def _upsert_item(conn: sqlite3.Connection, item: UsageItem, collected_at: str) -> None:
    conn.execute(
        """
        INSERT INTO usage_daily (
          source_id, date, agent, input_tokens, output_tokens,
          cache_creation_tokens, cache_read_tokens, total_tokens, total_cost,
          metadata_json, raw_json, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, date, agent) DO UPDATE SET
          input_tokens=excluded.input_tokens,
          output_tokens=excluded.output_tokens,
          cache_creation_tokens=excluded.cache_creation_tokens,
          cache_read_tokens=excluded.cache_read_tokens,
          total_tokens=excluded.total_tokens,
          total_cost=excluded.total_cost,
          metadata_json=excluded.metadata_json,
          raw_json=excluded.raw_json,
          last_seen_at=excluded.last_seen_at
        """,
        (
            item.source_id,
            item.date,
            item.agent,
            item.input_tokens,
            item.output_tokens,
            item.cache_creation_tokens,
            item.cache_read_tokens,
            item.total_tokens,
            item.total_cost,
            json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
            json.dumps(item.metadata.get("ccusage_row"), ensure_ascii=False, sort_keys=True)
            if isinstance(item.metadata.get("ccusage_row"), dict)
            else None,
            collected_at,
            collected_at,
        ),
    )
    for model in item.model_breakdowns:
        conn.execute(
            """
            INSERT INTO usage_daily_models (
              source_id, date, agent, model_name, input_tokens, output_tokens,
              cache_creation_tokens, cache_read_tokens, total_tokens, cost,
              raw_json, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, date, agent, model_name) DO UPDATE SET
              input_tokens=excluded.input_tokens,
              output_tokens=excluded.output_tokens,
              cache_creation_tokens=excluded.cache_creation_tokens,
              cache_read_tokens=excluded.cache_read_tokens,
              total_tokens=excluded.total_tokens,
              cost=excluded.cost,
              raw_json=excluded.raw_json,
              last_seen_at=excluded.last_seen_at
            """,
            (
                item.source_id,
                item.date,
                item.agent,
                model["model_name"],
                model["input_tokens"],
                model["output_tokens"],
                model["cache_creation_tokens"],
                model["cache_read_tokens"],
                model["total_tokens"],
                model["cost"],
                json.dumps(model.get("raw"), ensure_ascii=False, sort_keys=True)
                if isinstance(model.get("raw"), dict)
                else None,
                collected_at,
                collected_at,
            ),
        )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_limit_windows_schema(conn: sqlite3.Connection) -> None:
    columns = [row for row in conn.execute("PRAGMA table_info(limit_windows)")]
    column_names = [row[1] for row in columns]
    pk_columns = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
    if column_names and column_names[0] == "source_id" and pk_columns == ["source_id", "provider", "window"]:
        return

    conn.execute("ALTER TABLE limit_windows RENAME TO limit_windows_old")
    conn.executescript(
        """
        CREATE TABLE limit_windows (
          source_id TEXT NOT NULL,
          provider TEXT NOT NULL,
          window TEXT NOT NULL,
          used_percent REAL NOT NULL,
          remaining_percent REAL NOT NULL,
          reset_at TEXT NOT NULL,
          window_duration_minutes INTEGER NOT NULL,
          source_type TEXT NOT NULL,
          confidence TEXT NOT NULL,
          status TEXT NOT NULL,
          observed_at TEXT NOT NULL,
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          PRIMARY KEY(source_id, provider, window)
        );
        """
    )
    old_columns = {row[1] for row in conn.execute("PRAGMA table_info(limit_windows_old)")}
    source_expr = "source_id" if "source_id" in old_columns else "provider"
    conn.execute(
        f"""
        INSERT OR REPLACE INTO limit_windows (
          source_id, provider, window, used_percent, remaining_percent, reset_at,
          window_duration_minutes, source_type, confidence, status, observed_at,
          first_seen_at, last_seen_at
        )
        SELECT COALESCE(NULLIF({source_expr}, ''), provider), provider, window,
               used_percent, remaining_percent, reset_at, window_duration_minutes,
               source_type, confidence, status, observed_at, first_seen_at, last_seen_at
        FROM limit_windows_old
        ORDER BY julianday(observed_at) ASC, observed_at ASC
        """
    )
    conn.execute("DROP TABLE limit_windows_old")


def _upsert_hourly_item(conn: sqlite3.Connection, item: UsageHourlyItem, collected_at: str) -> None:
    conn.execute(
        """
        INSERT INTO usage_hourly (
          source_id, hour, agent, input_tokens, output_tokens,
          cache_creation_tokens, cache_read_tokens, total_tokens, total_cost,
          metadata_json, raw_json, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, hour, agent) DO UPDATE SET
          input_tokens=excluded.input_tokens,
          output_tokens=excluded.output_tokens,
          cache_creation_tokens=excluded.cache_creation_tokens,
          cache_read_tokens=excluded.cache_read_tokens,
          total_tokens=excluded.total_tokens,
          total_cost=excluded.total_cost,
          metadata_json=excluded.metadata_json,
          raw_json=excluded.raw_json,
          last_seen_at=excluded.last_seen_at
        """,
        (
            item.source_id,
            item.hour,
            item.agent,
            item.input_tokens,
            item.output_tokens,
            item.cache_creation_tokens,
            item.cache_read_tokens,
            item.total_tokens,
            item.total_cost,
            json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
            json.dumps(item.metadata.get("ccusage_session_row"), ensure_ascii=False, sort_keys=True)
            if isinstance(item.metadata.get("ccusage_session_row"), dict)
            else None,
            collected_at,
            collected_at,
        ),
    )


def _upsert_hourly_fact(conn: sqlite3.Connection, fact: UsageHourlyFact, collected_at: str) -> None:
    existing = conn.execute(
        """
        SELECT fact_id
        FROM usage_hourly_facts
        WHERE source_id = ?
          AND agent = ?
          AND client = ?
          AND window_start = ?
          AND window_end = ?
          AND ai_provider = ?
          AND ai_account_id = ?
          AND attribution_confidence = ?
          AND provenance = ?
        """,
        (
            fact.source_id,
            fact.agent,
            fact.client,
            fact.window_start,
            fact.window_end,
            fact.ai_provider,
            fact.ai_account_id,
            fact.attribution_confidence,
            fact.provenance,
        ),
    ).fetchone()
    previous_fact_id = str(existing[0]) if existing else None
    conn.execute(
        """
        INSERT INTO machines (
          machine_id, machine_name, host, platform, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(machine_id) DO UPDATE SET
          machine_name=excluded.machine_name,
          host=excluded.host,
          platform=excluded.platform,
          last_seen_at=excluded.last_seen_at
        """,
        (fact.machine_id, fact.machine_name, fact.host, fact.platform, collected_at, collected_at),
    )
    conn.execute(
        """
        INSERT INTO os_identities (
          machine_id, os_user, display_name, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(machine_id, os_user) DO UPDATE SET
          display_name=excluded.display_name,
          last_seen_at=excluded.last_seen_at
        """,
        (fact.machine_id, fact.os_user, f"{fact.machine_name} · {fact.os_user}", collected_at, collected_at),
    )
    conn.execute(
        """
        INSERT INTO ai_accounts (
          provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(provider, account_id) DO UPDATE SET
          account_label=excluded.account_label,
          display_name=excluded.display_name,
          subscription=excluded.subscription,
          last_seen_at=excluded.last_seen_at
        """,
        (
            fact.ai_provider,
            fact.ai_account_id,
            fact.ai_account_label,
            fact.ai_account_display_name,
            fact.ai_account_subscription,
            collected_at,
            collected_at,
        ),
    )
    conn.execute(
        """
        INSERT INTO usage_hourly_facts (
          fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id,
          agent, client, window_start, window_end, timezone,
          input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
          reasoning_output_tokens, total_tokens, total_cost, event_count, session_count,
          attribution_confidence, provenance, account_evidence_json, metadata_json,
          first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(
          source_id, agent, client, window_start, window_end,
          ai_provider, ai_account_id, attribution_confidence, provenance
        ) DO UPDATE SET
          fact_id=excluded.fact_id,
          source_id=excluded.source_id,
          machine_id=excluded.machine_id,
          os_user=excluded.os_user,
          ai_provider=excluded.ai_provider,
          ai_account_id=excluded.ai_account_id,
          agent=excluded.agent,
          client=excluded.client,
          window_start=excluded.window_start,
          window_end=excluded.window_end,
          timezone=excluded.timezone,
          input_tokens=excluded.input_tokens,
          output_tokens=excluded.output_tokens,
          cache_creation_tokens=excluded.cache_creation_tokens,
          cache_read_tokens=excluded.cache_read_tokens,
          reasoning_output_tokens=excluded.reasoning_output_tokens,
          total_tokens=excluded.total_tokens,
          total_cost=excluded.total_cost,
          event_count=excluded.event_count,
          session_count=excluded.session_count,
          attribution_confidence=excluded.attribution_confidence,
          provenance=excluded.provenance,
          account_evidence_json=excluded.account_evidence_json,
          metadata_json=excluded.metadata_json,
          last_seen_at=excluded.last_seen_at
        """,
        (
            fact.fact_id,
            fact.source_id,
            fact.machine_id,
            fact.os_user,
            fact.ai_provider,
            fact.ai_account_id,
            fact.agent,
            fact.client,
            fact.window_start,
            fact.window_end,
            fact.timezone,
            fact.input_tokens,
            fact.output_tokens,
            fact.cache_creation_tokens,
            fact.cache_read_tokens,
            fact.reasoning_output_tokens,
            fact.total_tokens,
            fact.total_cost,
            fact.event_count,
            fact.session_count,
            fact.attribution_confidence,
            fact.provenance,
            json.dumps(fact.account_evidence, ensure_ascii=False, sort_keys=True),
            json.dumps(fact.metadata, ensure_ascii=False, sort_keys=True),
            collected_at,
            collected_at,
        ),
    )
    for fact_id in {previous_fact_id, fact.fact_id}:
        if fact_id:
            conn.execute("DELETE FROM usage_hourly_models WHERE fact_id = ?", (fact_id,))
    for model in fact.model_breakdowns:
        model_name = str(model.get("model") or model.get("model_name") or "unknown")
        conn.execute(
            """
            INSERT INTO usage_hourly_models (
              fact_id, model, input_tokens, output_tokens, cache_creation_tokens,
              cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost,
              metadata_json, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact.fact_id,
                model_name,
                int(model.get("input_tokens") or 0),
                int(model.get("output_tokens") or 0),
                int(model.get("cache_creation_tokens") or 0),
                int(model.get("cache_read_tokens") or 0),
                int(model.get("reasoning_output_tokens") or 0),
                int(model.get("total_tokens") or 0),
                float(model["total_cost"]) if model.get("total_cost") is not None else None,
                json.dumps(model, ensure_ascii=False, sort_keys=True),
                collected_at,
                collected_at,
            ),
        )


def _delete_replaced_codex_hourly_rows(conn: sqlite3.Connection, hourly_items: list[UsageHourlyItem]) -> None:
    affected = {
        (item.source_id, item.hour[:10])
        for item in hourly_items
        if item.metadata.get("provenance") == "mswusage_codex_token_count" and _is_codex_agent(item.agent)
    }
    for source_id, day in affected:
        conn.execute(
            """
            DELETE FROM usage_hourly
            WHERE source_id = ?
              AND substr(hour, 1, 10) = ?
              AND (
                lower(agent) LIKE '%codex%'
                OR lower(agent) LIKE '%gpt%'
                OR lower(agent) LIKE '%openai%'
              )
            """,
            (source_id, day),
        )


def _is_codex_agent(agent: Any) -> bool:
    raw = str(agent or "").lower()
    return "codex" in raw or "gpt" in raw or "openai" in raw


def _upsert_block_item(conn: sqlite3.Connection, item: UsageBlockItem, collected_at: str) -> None:
    conn.execute(
        """
        INSERT INTO usage_blocks (
          source_id, start_time, end_time, agent, input_tokens, output_tokens,
          cache_creation_tokens, cache_read_tokens, total_tokens, total_cost,
          metadata_json, raw_json, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, start_time, end_time, agent) DO UPDATE SET
          input_tokens=excluded.input_tokens,
          output_tokens=excluded.output_tokens,
          cache_creation_tokens=excluded.cache_creation_tokens,
          cache_read_tokens=excluded.cache_read_tokens,
          total_tokens=excluded.total_tokens,
          total_cost=excluded.total_cost,
          metadata_json=excluded.metadata_json,
          raw_json=excluded.raw_json,
          last_seen_at=excluded.last_seen_at
        """,
        (
            item.source_id,
            item.start_time,
            item.end_time,
            item.agent,
            item.input_tokens,
            item.output_tokens,
            item.cache_creation_tokens,
            item.cache_read_tokens,
            item.total_tokens,
            item.total_cost,
            json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
            json.dumps(item.metadata.get("ccusage_block_row"), ensure_ascii=False, sort_keys=True)
            if isinstance(item.metadata.get("ccusage_block_row"), dict)
            else None,
            collected_at,
            collected_at,
        ),
    )


def _upsert_limit_window(conn: sqlite3.Connection, window: LimitWindow, seen_at: str) -> None:
    source_id = window.source_id or window.provider
    if window.status != "provider_failed":
        conn.execute(
            """
            DELETE FROM limit_windows
            WHERE source_id = ?
              AND provider = ?
              AND source_type = 'provider_runtime'
              AND status = 'provider_failed'
              AND julianday(observed_at) < julianday(?)
            """,
            (source_id, window.provider, window.observed_at),
        )
    conn.execute(
        """
        INSERT INTO limit_windows (
          source_id, provider, window, used_percent, remaining_percent, reset_at,
          window_duration_minutes, source_type, confidence, status, observed_at,
          first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, provider, window) DO UPDATE SET
          used_percent=excluded.used_percent,
          remaining_percent=excluded.remaining_percent,
          reset_at=excluded.reset_at,
          window_duration_minutes=excluded.window_duration_minutes,
          source_type=excluded.source_type,
          confidence=excluded.confidence,
          status=excluded.status,
          observed_at=excluded.observed_at,
          last_seen_at=excluded.last_seen_at
        WHERE julianday(excluded.observed_at) >= julianday(limit_windows.observed_at)
        """,
        (
            source_id,
            window.provider,
            window.window,
            window.used_percent,
            window.remaining_percent,
            window.reset_at,
            window.window_duration_minutes,
            window.source_type,
            window.confidence,
            window.status,
            window.observed_at,
            seen_at,
            seen_at,
        ),
    )


def _safe_error(message: str) -> str:
    msg = message or ""
    msg = msg.replace("\n", " ")
    # 脱敏常见敏感路径如 /Users/xxx 或 /home/xxx
    import re
    msg = re.sub(r'/Users/[a-zA-Z0-9_\-\.]+/', '/Users/<user>/', msg)
    msg = re.sub(r'/home/[a-zA-Z0-9_\-\.]+/', '/home/<user>/', msg)
    # 脱敏 token
    msg = re.sub(r'(?i)token[a-zA-Z0-9_\-\.\s]*?[:=\s]\s*[a-zA-Z0-9_\-\.]+', 'token=***', msg)
    msg = re.sub(r'(?i)bearer\s+[a-zA-Z0-9_\-\.]+', 'bearer ***', msg)
    return msg[:500]
