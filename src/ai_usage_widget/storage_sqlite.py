from __future__ import annotations

import json
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
        for fact in hourly_facts or []:
            _upsert_hourly_fact(conn, fact, collected_at)
        for item in block_items or []:
            _upsert_block_item(conn, item, collected_at)


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
          PRIMARY KEY(source_id, provider, source_type, window)
        );
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
    if column_names and column_names[0] == "source_id" and pk_columns == ["source_id", "provider", "source_type", "window"]:
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
          PRIMARY KEY(source_id, provider, source_type, window)
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
            """,
            (source_id, window.provider),
        )
    conn.execute(
        """
        INSERT INTO limit_windows (
          source_id, provider, window, used_percent, remaining_percent, reset_at,
          window_duration_minutes, source_type, confidence, status, observed_at,
          first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, provider, source_type, window) DO UPDATE SET
          used_percent=excluded.used_percent,
          remaining_percent=excluded.remaining_percent,
          reset_at=excluded.reset_at,
          window_duration_minutes=excluded.window_duration_minutes,
          confidence=excluded.confidence,
          status=excluded.status,
          observed_at=excluded.observed_at,
          last_seen_at=excluded.last_seen_at
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
