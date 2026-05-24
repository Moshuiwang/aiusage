from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .models import CommandResult, UsageItem


def write_sqlite(
    path: str,
    collected_at: str,
    timezone: str,
    run_status: str,
    source_reports: List[Dict[str, Any]],
    items: Iterable[UsageItem],
) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        _ensure_schema(conn)
        run_id = _insert_run(conn, collected_at, timezone, run_status)
        for report in source_reports:
            _insert_source_report(conn, run_id, report)
        for item in items:
            _upsert_item(conn, item, collected_at)


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
          first_seen_at TEXT NOT NULL,
          last_seen_at TEXT NOT NULL,
          PRIMARY KEY(source_id, date, agent, model_name)
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


def _upsert_item(conn: sqlite3.Connection, item: UsageItem, collected_at: str) -> None:
    conn.execute(
        """
        INSERT INTO usage_daily (
          source_id, date, agent, input_tokens, output_tokens,
          cache_creation_tokens, cache_read_tokens, total_tokens, total_cost,
          metadata_json, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, date, agent) DO UPDATE SET
          input_tokens=excluded.input_tokens,
          output_tokens=excluded.output_tokens,
          cache_creation_tokens=excluded.cache_creation_tokens,
          cache_read_tokens=excluded.cache_read_tokens,
          total_tokens=excluded.total_tokens,
          total_cost=excluded.total_cost,
          metadata_json=excluded.metadata_json,
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
              first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, date, agent, model_name) DO UPDATE SET
              input_tokens=excluded.input_tokens,
              output_tokens=excluded.output_tokens,
              cache_creation_tokens=excluded.cache_creation_tokens,
              cache_read_tokens=excluded.cache_read_tokens,
              total_tokens=excluded.total_tokens,
              cost=excluded.cost,
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
                collected_at,
                collected_at,
            ),
        )


def _safe_error(message: str) -> str:
    return (message or "").replace("\n", " ")[:500]

