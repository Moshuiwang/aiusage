from __future__ import annotations

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "cloudflare" / "migrations"
MIGRATION_SQL = MIGRATIONS_DIR / "0001_initial_schema.sql"
LIMIT_STABLE_KEY_MIGRATION_SQL = MIGRATIONS_DIR / "0003_limit_window_stable_key.sql"
COLLECTOR_VERSION_MIGRATION_SQL = (
    MIGRATIONS_DIR / "0007_source_report_states_collector_version.sql"
)
REJECTED_INGEST_MIGRATION_SQL = (
    MIGRATIONS_DIR / "0009_rejected_ingest_attempts.sql"
)

# The source_report_states layout as it exists on a database already migrated to
# 0006. Deliberately spelled out instead of replayed from 0001/0004: 0001 was
# amended to create collector_version for the fresh-install path, so replaying
# the current chain can never reproduce the deployed pre-0007 table. Production
# D1 is on this 10-column shape *with rows in it*, and that is the only path
# where 0007 does real work.
LEGACY_SOURCE_REPORT_STATES_DDL = """
CREATE TABLE source_report_states (
  source_id TEXT PRIMARY KEY,
  collected_at TEXT NOT NULL,
  report_type TEXT NOT NULL,
  command TEXT NOT NULL,
  status TEXT NOT NULL,
  ccusage_version TEXT,
  first_period TEXT,
  last_period TEXT,
  error_type TEXT,
  error_message TEXT
);
"""

LEGACY_SOURCE_REPORT_STATES_ROWS = [
    # Happy path: every optional column populated.
    (
        "linux-biai-wang",
        "2026-07-31T09:00:00+08:00",
        "daily",
        "ccusage daily --json",
        "ok",
        "15.9.7",
        "2026-06-01",
        "2026-07-31",
        None,
        None,
    ),
    # Failure path: ccusage_version/periods NULL, error columns populated.
    (
        "mac-air-wangzhipeng",
        "2026-07-31T09:05:00+08:00",
        "limits",
        "mswusage-codex limits --json",
        "provider_failed",
        None,
        None,
        None,
        "timeout",
        "provider timed out after 30s",
    ),
]
D1_ONLY_TABLE_COLUMNS = {
    "source_report_states": [
        ("source_id", "TEXT", 0, None, 1),
        ("collected_at", "TEXT", 1, None, 0),
        ("report_type", "TEXT", 1, None, 0),
        ("command", "TEXT", 1, None, 0),
        ("status", "TEXT", 1, None, 0),
        ("ccusage_version", "TEXT", 0, None, 0),
        ("first_period", "TEXT", 0, None, 0),
        ("last_period", "TEXT", 0, None, 0),
        ("error_type", "TEXT", 0, None, 0),
        ("error_message", "TEXT", 0, None, 0),
        # Last position is not cosmetic: SQLite `ALTER TABLE ... ADD COLUMN`
        # can only append, so any other position would make the fresh-install
        # path (0001 CREATE TABLE) and the incremental path (later migration)
        # disagree on column order.
        ("collector_version", "TEXT", 0, None, 0),
    ],
}


# Fresh-install schema, deliberately spelled out (#74: replaces the deleted
# `storage_sqlite._ensure_schema` mirror test). The literal *is* the guard: any
# schema change must edit this snapshot in the same reviewable diff, otherwise
# a column added, dropped or retyped in 0001 lands silently. Regenerating this
# block from 0001 and comparing would be circular and guard nothing.
# `usage_blocks` is absent on purpose: #91 stopped collection, no reader or
# writer remains on either side, and 0008 drops the table from deployed D1.
FRESH_INSTALL_TABLE_COLUMNS = {
    "ai_accounts": [
        ('provider', 'TEXT', 1, None, 1),
        ('account_id', 'TEXT', 1, None, 2),
        ('account_label', 'TEXT', 1, None, 0),
        ('display_name', 'TEXT', 0, None, 0),
        ('subscription', 'TEXT', 0, None, 0),
        ('first_seen_at', 'TEXT', 1, None, 0),
        ('last_seen_at', 'TEXT', 1, None, 0),
    ],
    "collection_runs": [
        ('id', 'INTEGER', 0, None, 1),
        ('collected_at', 'TEXT', 1, None, 0),
        ('timezone', 'TEXT', 1, None, 0),
        ('collector_version', 'TEXT', 0, None, 0),
        ('status', 'TEXT', 1, None, 0),
    ],
    "limit_windows": [
        ('source_id', 'TEXT', 1, None, 1),
        ('provider', 'TEXT', 1, None, 2),
        ('window', 'TEXT', 1, None, 3),
        ('used_percent', 'REAL', 1, None, 0),
        ('remaining_percent', 'REAL', 1, None, 0),
        ('reset_at', 'TEXT', 1, None, 0),
        ('window_duration_minutes', 'INTEGER', 1, None, 0),
        ('source_type', 'TEXT', 1, None, 0),
        ('confidence', 'TEXT', 1, None, 0),
        ('status', 'TEXT', 1, None, 0),
        ('observed_at', 'TEXT', 1, None, 0),
        ('first_seen_at', 'TEXT', 1, None, 0),
        ('last_seen_at', 'TEXT', 1, None, 0),
    ],
    "machines": [
        ('machine_id', 'TEXT', 0, None, 1),
        ('machine_name', 'TEXT', 1, None, 0),
        ('host', 'TEXT', 0, None, 0),
        ('platform', 'TEXT', 1, None, 0),
        ('first_seen_at', 'TEXT', 1, None, 0),
        ('last_seen_at', 'TEXT', 1, None, 0),
    ],
    "os_identities": [
        ('machine_id', 'TEXT', 1, None, 1),
        ('os_user', 'TEXT', 1, None, 2),
        ('display_name', 'TEXT', 1, None, 0),
        ('first_seen_at', 'TEXT', 1, None, 0),
        ('last_seen_at', 'TEXT', 1, None, 0),
    ],
    "rejected_ingest_attempts": [
        ('source_id_claimed', 'TEXT', 1, None, 1),
        ('error_type', 'TEXT', 1, None, 2),
        ('path', 'TEXT', 1, None, 0),
        ('day', 'TEXT', 1, None, 3),
        ('first_seen_at', 'TEXT', 1, None, 0),
        ('last_seen_at', 'TEXT', 1, None, 0),
        ('count', 'INTEGER', 1, '1', 0),
    ],
    "source_accuracy": [
        ('source_id', 'TEXT', 1, None, 1),
        ('agent', 'TEXT', 1, None, 2),
        ('provenance', 'TEXT', 1, None, 0),
        ('collector_version', 'TEXT', 0, None, 0),
        ('parser_schema_version', 'INTEGER', 0, None, 0),
        ('mode', 'TEXT', 1, None, 0),
        ('lookback_hours', 'REAL', 0, None, 0),
        ('coverage_start', 'TEXT', 0, None, 0),
        ('coverage_end', 'TEXT', 0, None, 0),
        ('report_digest', 'TEXT', 0, None, 0),
        ('facts_digest', 'TEXT', 0, None, 0),
        ('scan_complete', 'INTEGER', 1, '0', 0),
        ('read_errors', 'INTEGER', 1, '0', 0),
        ('unresolved_mismatch', 'INTEGER', 1, '0', 0),
        ('matching_full_scans', 'INTEGER', 1, '0', 0),
        ('accuracy_status', 'TEXT', 1, None, 0),
        ('verified_at', 'TEXT', 0, None, 0),
        ('metadata_json', 'TEXT', 0, None, 0),
        ('observed_at', 'TEXT', 1, None, 0),
        ('first_seen_at', 'TEXT', 1, None, 0),
        ('last_seen_at', 'TEXT', 1, None, 0),
    ],
    "source_identities": [
        ('source_id', 'TEXT', 0, None, 1),
        ('host', 'TEXT', 0, None, 0),
        ('machine', 'TEXT', 0, None, 0),
        ('os_user', 'TEXT', 0, None, 0),
        ('platform', 'TEXT', 0, None, 0),
        ('first_seen_at', 'TEXT', 1, None, 0),
        ('last_seen_at', 'TEXT', 1, None, 0),
    ],
    "source_report_states": [
        ('source_id', 'TEXT', 0, None, 1),
        ('collected_at', 'TEXT', 1, None, 0),
        ('report_type', 'TEXT', 1, None, 0),
        ('command', 'TEXT', 1, None, 0),
        ('status', 'TEXT', 1, None, 0),
        ('ccusage_version', 'TEXT', 0, None, 0),
        ('first_period', 'TEXT', 0, None, 0),
        ('last_period', 'TEXT', 0, None, 0),
        ('error_type', 'TEXT', 0, None, 0),
        ('error_message', 'TEXT', 0, None, 0),
        ('collector_version', 'TEXT', 0, None, 0),
    ],
    "source_reports": [
        ('id', 'INTEGER', 0, None, 1),
        ('run_id', 'INTEGER', 1, None, 0),
        ('source_id', 'TEXT', 1, None, 0),
        ('report_type', 'TEXT', 1, None, 0),
        ('command', 'TEXT', 1, None, 0),
        ('status', 'TEXT', 1, None, 0),
        ('ccusage_version', 'TEXT', 0, None, 0),
        ('first_period', 'TEXT', 0, None, 0),
        ('last_period', 'TEXT', 0, None, 0),
        ('error_type', 'TEXT', 0, None, 0),
        ('error_message', 'TEXT', 0, None, 0),
    ],
    "usage_daily": [
        ('source_id', 'TEXT', 1, None, 1),
        ('date', 'TEXT', 1, None, 2),
        ('agent', 'TEXT', 1, None, 3),
        ('input_tokens', 'INTEGER', 1, '0', 0),
        ('output_tokens', 'INTEGER', 1, '0', 0),
        ('cache_creation_tokens', 'INTEGER', 1, '0', 0),
        ('cache_read_tokens', 'INTEGER', 1, '0', 0),
        ('total_tokens', 'INTEGER', 1, '0', 0),
        ('total_cost', 'REAL', 0, None, 0),
        ('metadata_json', 'TEXT', 0, None, 0),
        ('raw_json', 'TEXT', 0, None, 0),
        ('first_seen_at', 'TEXT', 1, None, 0),
        ('last_seen_at', 'TEXT', 1, None, 0),
    ],
    "usage_daily_models": [
        ('source_id', 'TEXT', 1, None, 1),
        ('date', 'TEXT', 1, None, 2),
        ('agent', 'TEXT', 1, None, 3),
        ('model_name', 'TEXT', 1, None, 4),
        ('input_tokens', 'INTEGER', 1, '0', 0),
        ('output_tokens', 'INTEGER', 1, '0', 0),
        ('cache_creation_tokens', 'INTEGER', 1, '0', 0),
        ('cache_read_tokens', 'INTEGER', 1, '0', 0),
        ('total_tokens', 'INTEGER', 1, '0', 0),
        ('cost', 'REAL', 0, None, 0),
        ('raw_json', 'TEXT', 0, None, 0),
        ('first_seen_at', 'TEXT', 1, None, 0),
        ('last_seen_at', 'TEXT', 1, None, 0),
    ],
    "usage_daily_rollups": [
        ('date', 'TEXT', 1, None, 1),
        ('bucket_start', 'TEXT', 1, None, 0),
        ('bucket_end', 'TEXT', 1, None, 0),
        ('source_id', 'TEXT', 1, None, 2),
        ('machine_id', 'TEXT', 1, None, 3),
        ('os_user', 'TEXT', 1, None, 4),
        ('ai_provider', 'TEXT', 1, None, 5),
        ('ai_account_id', 'TEXT', 1, None, 6),
        ('agent', 'TEXT', 1, None, 7),
        ('client', 'TEXT', 1, None, 8),
        ('attribution_confidence', 'TEXT', 1, None, 9),
        ('provenance', 'TEXT', 1, None, 10),
        ('input_tokens', 'INTEGER', 1, None, 0),
        ('output_tokens', 'INTEGER', 1, None, 0),
        ('cache_creation_tokens', 'INTEGER', 1, None, 0),
        ('cache_read_tokens', 'INTEGER', 1, None, 0),
        ('reasoning_output_tokens', 'INTEGER', 1, None, 0),
        ('total_tokens', 'INTEGER', 1, None, 0),
        ('event_count', 'INTEGER', 1, None, 0),
        ('session_count', 'INTEGER', 1, None, 0),
        ('fact_count', 'INTEGER', 1, None, 0),
    ],
    "usage_reconciliation_ranges": [
        ('source_id', 'TEXT', 1, None, 1),
        ('agent', 'TEXT', 1, None, 2),
        ('provenance', 'TEXT', 1, None, 3),
        ('coverage_start', 'TEXT', 1, None, 4),
        ('coverage_end', 'TEXT', 1, None, 5),
        ('observed_at', 'TEXT', 1, None, 0),
    ],
    "usage_rollup_dirty_days": [('date', 'TEXT', 1, None, 1)],
    "usage_fact_revisions": [
        ('source_id', 'TEXT', 1, None, 1),
        ('agent', 'TEXT', 1, None, 2),
        ('client', 'TEXT', 1, None, 3),
        ('window_start', 'TEXT', 1, None, 4),
        ('window_end', 'TEXT', 1, None, 5),
        ('ai_provider', 'TEXT', 1, None, 6),
        ('ai_account_id', 'TEXT', 1, None, 7),
        ('attribution_confidence', 'TEXT', 1, None, 8),
        ('provenance', 'TEXT', 1, None, 9),
        ('observed_at', 'TEXT', 1, None, 0),
    ],
    "usage_hourly": [
        ('source_id', 'TEXT', 1, None, 1),
        ('hour', 'TEXT', 1, None, 2),
        ('agent', 'TEXT', 1, None, 3),
        ('input_tokens', 'INTEGER', 1, '0', 0),
        ('output_tokens', 'INTEGER', 1, '0', 0),
        ('cache_creation_tokens', 'INTEGER', 1, '0', 0),
        ('cache_read_tokens', 'INTEGER', 1, '0', 0),
        ('total_tokens', 'INTEGER', 1, '0', 0),
        ('total_cost', 'REAL', 0, None, 0),
        ('metadata_json', 'TEXT', 0, None, 0),
        ('raw_json', 'TEXT', 0, None, 0),
        ('first_seen_at', 'TEXT', 1, None, 0),
        ('last_seen_at', 'TEXT', 1, None, 0),
    ],
    "usage_hourly_facts": [
        ('fact_id', 'TEXT', 0, None, 1),
        ('source_id', 'TEXT', 1, None, 0),
        ('machine_id', 'TEXT', 1, None, 0),
        ('os_user', 'TEXT', 1, None, 0),
        ('ai_provider', 'TEXT', 1, None, 0),
        ('ai_account_id', 'TEXT', 1, None, 0),
        ('agent', 'TEXT', 1, None, 0),
        ('client', 'TEXT', 0, None, 0),
        ('window_start', 'TEXT', 1, None, 0),
        ('window_end', 'TEXT', 1, None, 0),
        ('timezone', 'TEXT', 1, None, 0),
        ('input_tokens', 'INTEGER', 1, '0', 0),
        ('output_tokens', 'INTEGER', 1, '0', 0),
        ('cache_creation_tokens', 'INTEGER', 1, '0', 0),
        ('cache_read_tokens', 'INTEGER', 1, '0', 0),
        ('reasoning_output_tokens', 'INTEGER', 1, '0', 0),
        ('total_tokens', 'INTEGER', 1, '0', 0),
        ('total_cost', 'REAL', 0, None, 0),
        ('event_count', 'INTEGER', 1, '0', 0),
        ('session_count', 'INTEGER', 1, '0', 0),
        ('attribution_confidence', 'TEXT', 1, None, 0),
        ('provenance', 'TEXT', 1, None, 0),
        ('account_evidence_json', 'TEXT', 0, None, 0),
        ('metadata_json', 'TEXT', 0, None, 0),
        ('first_seen_at', 'TEXT', 1, None, 0),
        ('last_seen_at', 'TEXT', 1, None, 0),
    ],
    "usage_hourly_models": [
        ('fact_id', 'TEXT', 1, None, 1),
        ('model', 'TEXT', 1, None, 2),
        ('input_tokens', 'INTEGER', 1, '0', 0),
        ('output_tokens', 'INTEGER', 1, '0', 0),
        ('cache_creation_tokens', 'INTEGER', 1, '0', 0),
        ('cache_read_tokens', 'INTEGER', 1, '0', 0),
        ('reasoning_output_tokens', 'INTEGER', 1, '0', 0),
        ('total_tokens', 'INTEGER', 1, '0', 0),
        ('total_cost', 'REAL', 0, None, 0),
        ('metadata_json', 'TEXT', 0, None, 0),
        ('first_seen_at', 'TEXT', 1, None, 0),
        ('last_seen_at', 'TEXT', 1, None, 0),
    ],
    "usage_hourly_rollups": [
        ('bucket_start', 'TEXT', 1, None, 1),
        ('bucket_end', 'TEXT', 1, None, 0),
        ('source_id', 'TEXT', 1, None, 2),
        ('machine_id', 'TEXT', 1, None, 3),
        ('os_user', 'TEXT', 1, None, 4),
        ('ai_provider', 'TEXT', 1, None, 5),
        ('ai_account_id', 'TEXT', 1, None, 6),
        ('agent', 'TEXT', 1, None, 7),
        ('client', 'TEXT', 1, None, 8),
        ('attribution_confidence', 'TEXT', 1, None, 9),
        ('provenance', 'TEXT', 1, None, 10),
        ('input_tokens', 'INTEGER', 1, None, 0),
        ('output_tokens', 'INTEGER', 1, None, 0),
        ('cache_creation_tokens', 'INTEGER', 1, None, 0),
        ('cache_read_tokens', 'INTEGER', 1, None, 0),
        ('reasoning_output_tokens', 'INTEGER', 1, None, 0),
        ('total_tokens', 'INTEGER', 1, None, 0),
        ('event_count', 'INTEGER', 1, None, 0),
        ('session_count', 'INTEGER', 1, None, 0),
        ('fact_count', 'INTEGER', 1, None, 0),
    ],
}

FRESH_INSTALL_CREATED_INDEXES = {
    "ai_accounts": {
    },
    "collection_runs": {
        "idx_collection_runs_collected_at": (0, 0, ('collected_at',)),
    },
    "limit_windows": {
    },
    "machines": {
    },
    "os_identities": {
    },
    "rejected_ingest_attempts": {
        "idx_rejected_ingest_attempts_last_seen": (0, 0, ('last_seen_at',)),
    },
    "source_accuracy": {
        "idx_source_accuracy_status": (0, 0, ('accuracy_status', 'source_id', 'agent')),
    },
    "source_identities": {
    },
    "source_report_states": {
    },
    "source_reports": {
        "idx_source_reports_run_id": (0, 0, ('run_id',)),
    },
    "usage_daily": {
    },
    "usage_daily_models": {
    },
    "usage_daily_rollups": {
        "idx_usage_daily_rollups_date": (0, 0, ('date',)),
    },
    "usage_fact_revisions": {},
    "usage_reconciliation_ranges": {},
    "usage_rollup_dirty_days": {},
    "usage_hourly": {
    },
    "usage_hourly_facts": {
        "idx_usage_hourly_facts_account": (0, 0, ('ai_provider', 'ai_account_id', 'window_start')),
        "idx_usage_hourly_facts_agent": (0, 0, ('agent', 'window_start')),
        "idx_usage_hourly_facts_machine_user": (0, 0, ('machine_id', 'os_user', 'window_start')),
        "idx_usage_hourly_facts_source": (0, 0, ('source_id', 'window_start')),
        "idx_usage_hourly_facts_unique_hour": (1, 0, ('source_id', 'agent', 'client', 'window_start', 'window_end', 'ai_provider', 'ai_account_id', 'attribution_confidence', 'provenance')),
        "idx_usage_hourly_facts_window": (0, 0, ('window_start', 'window_end')),
    },
    "usage_hourly_models": {
    },
    "usage_hourly_rollups": {
        "idx_usage_hourly_rollups_bucket": (0, 0, ('bucket_start',)),
    },
}


def _all_migration_files() -> list[Path]:
    """Every migration in apply order. Deliberately discovered, not listed:
    a new migration must be covered by the parity test without editing it."""
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


CREATE_INDEX_RE = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


def _declared_index_names(migration: Path) -> list[str]:
    return CREATE_INDEX_RE.findall(migration.read_text(encoding="utf-8"))


def _index_definitions(conn: sqlite3.Connection) -> dict[str, tuple]:
    """Every explicit index in the database, keyed by name, carrying the table it
    sits on plus its definition. Table is part of the value on purpose: index
    names are global in SQLite, so an index recreated on the wrong table keeps
    its name and only the table changes."""
    definitions = {}
    for name, table in conn.execute(
        "SELECT name, tbl_name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
    ).fetchall():
        definitions[name] = (table, _created_indexes(conn, table)[name])
    return definitions


def _user_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [row[0] for row in rows]


def _table_columns(conn: sqlite3.Connection, table: str) -> list[tuple]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [
        (
            row[1],  # name
            row[2].upper(),  # type
            row[3],  # notnull
            row[4],  # default
            row[5],  # pk order
        )
        for row in rows
    ]


def _created_indexes(conn: sqlite3.Connection, table: str) -> dict[str, tuple]:
    """Explicit `CREATE INDEX` results for one table, keyed by name and carrying
    the *definition* (unique flag, partial flag, indexed columns) -- not just the
    name. A name-only comparison would wave through an index recreated on the
    wrong columns or without UNIQUE, which is exactly the shape of drift that
    hurts (same name, different behaviour)."""
    indexes = {}
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        name = row[1]
        origin = row[3]
        if origin != "c":
            continue
        partial = row[4] if len(row) > 4 else 0
        columns = tuple(
            info[2]
            for info in conn.execute(f"PRAGMA index_info({name})").fetchall()
        )
        indexes[name] = (row[2], partial, columns)
    return indexes


def _auto_indexes(conn: sqlite3.Connection, table: str) -> dict[str, tuple]:
    """Indexes SQLite created implicitly (origin 'pk'/'u'), i.e. the ones a table
    rebuild can silently drop without any CREATE INDEX statement going missing."""
    indexes = {}
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        name = row[1]
        origin = row[3]
        if origin == "c":
            continue
        columns = tuple(
            info[2]
            for info in conn.execute(f"PRAGMA index_info({name})").fetchall()
        )
        indexes[name] = (origin, row[2], columns)
    return indexes


class TestD1SchemaMigration(unittest.TestCase):
    maxDiff = None

    def test_fresh_install_schema_matches_declared_snapshot(self) -> None:
        """0001 落成的表、列与显式索引必须逐项等于声明的快照（#74 自立 schema 守卫）。

        接替已删除的 `storage_sqlite._ensure_schema` 镜像比对：比对基准从「另一份
        实现」换成「本文件里的显式字面量」，列名、类型、NOT NULL、默认值、主键
        位次、索引定义任何一项漂移都会红，且修复必须同时改快照——schema 变更
        从此必须是同一个 diff 里看得见的两处改动。
        """
        self.assertTrue(MIGRATION_SQL.exists(), f"Missing migration: {MIGRATION_SQL}")

        with sqlite3.connect(":memory:") as conn:
            conn.executescript(MIGRATION_SQL.read_text(encoding="utf-8"))
            actual_tables = _user_tables(conn)
            actual_columns = {table: _table_columns(conn, table) for table in actual_tables}
            actual_indexes = {table: _created_indexes(conn, table) for table in actual_tables}

        self.assertEqual(actual_tables, sorted(FRESH_INSTALL_TABLE_COLUMNS))
        self.assertEqual(
            actual_columns,
            {table: [tuple(col) for col in cols] for table, cols in FRESH_INSTALL_TABLE_COLUMNS.items()},
        )
        self.assertEqual(actual_indexes, FRESH_INSTALL_CREATED_INDEXES)
        # 结构下限：快照必须仍然覆盖一个真实规模的 schema，
        # 「快照被清空 + schema 被清空」不许产生同一个绿。
        self.assertGreaterEqual(len(FRESH_INSTALL_TABLE_COLUMNS), 16)
        self.assertGreaterEqual(sum(len(cols) for cols in FRESH_INSTALL_TABLE_COLUMNS.values()), 200)
        self.assertIn("usage_hourly_facts", FRESH_INSTALL_TABLE_COLUMNS)
        self.assertNotIn(
            "usage_blocks",
            FRESH_INSTALL_TABLE_COLUMNS,
            "usage_blocks 已随 #74 删除（#91 停采后零读零写）；谁要复活它必须走新决策",
        )

    def test_full_migration_chain_matches_fresh_schema(self) -> None:
        """A brand-new D1 gets 0001 alone in this repo's fresh-install path, while a
        deployed D1 walks 0001 -> ... -> latest. Both must land on identical column
        layouts *and* identical indexes, otherwise an added column or index silently
        exists in one shape only.

        Indexes are asserted here rather than in a parallel test on purpose: it is
        one invariant ("both install paths converge on the same schema"), the two
        databases are already built here, and a second test would have to duplicate
        the chain replay and the D1-only exclusions -- duplication that drifts the
        moment someone updates one copy and not the other."""
        migrations = _all_migration_files()
        self.assertEqual(migrations[0], MIGRATION_SQL)
        self.assertGreater(len(migrations), 1)

        with sqlite3.connect(":memory:") as fresh_conn:
            fresh_conn.executescript(MIGRATION_SQL.read_text(encoding="utf-8"))
            fresh_tables = _user_tables(fresh_conn)
            fresh_columns = {table: _table_columns(fresh_conn, table) for table in fresh_tables}
            fresh_indexes = {table: _created_indexes(fresh_conn, table) for table in fresh_tables}

        with sqlite3.connect(":memory:") as chain_conn:
            for migration in migrations:
                chain_conn.executescript(migration.read_text(encoding="utf-8"))
            chain_tables = _user_tables(chain_conn)
            chain_columns = {table: _table_columns(chain_conn, table) for table in chain_tables}
            chain_indexes = {table: _created_indexes(chain_conn, table) for table in chain_tables}

        self.assertEqual(chain_tables, fresh_tables)
        self.assertEqual(chain_columns, fresh_columns)
        self.assertEqual(
            chain_indexes,
            fresh_indexes,
            "index sets diverge between the fresh-install path (0001 alone) and the "
            "migration chain; a later migration's CREATE INDEX was never backfilled "
            "into 0001 (or was backfilled onto different columns)",
        )
        for table, expected_columns in D1_ONLY_TABLE_COLUMNS.items():
            self.assertEqual(chain_columns[table], expected_columns)

    def test_rejected_ingest_migration_matches_fresh_schema_on_its_real_upgrade_path(self) -> None:
        """0009 must create the same table as cumulative 0001 when the table is absent.

        The full-chain test cannot prove this: current 0001 already creates the table,
        so 0009's IF NOT EXISTS path is a no-op there. Apply 0009 to an empty legacy
        database and compare columns, PK auto-index and explicit indexes independently.
        """
        self.assertTrue(
            REJECTED_INGEST_MIGRATION_SQL.exists(),
            f"Missing migration: {REJECTED_INGEST_MIGRATION_SQL}",
        )

        with sqlite3.connect(":memory:") as fresh_conn:
            fresh_conn.executescript(MIGRATION_SQL.read_text(encoding="utf-8"))
            fresh_columns = _table_columns(fresh_conn, "rejected_ingest_attempts")
            fresh_indexes = _created_indexes(fresh_conn, "rejected_ingest_attempts")
            fresh_auto_indexes = _auto_indexes(fresh_conn, "rejected_ingest_attempts")

        with sqlite3.connect(":memory:") as upgraded_conn:
            upgraded_conn.executescript(
                REJECTED_INGEST_MIGRATION_SQL.read_text(encoding="utf-8")
            )
            upgraded_tables = _user_tables(upgraded_conn)
            upgraded_columns = _table_columns(upgraded_conn, "rejected_ingest_attempts")
            upgraded_indexes = _created_indexes(upgraded_conn, "rejected_ingest_attempts")
            upgraded_auto_indexes = _auto_indexes(upgraded_conn, "rejected_ingest_attempts")

        self.assertEqual(upgraded_tables, ["rejected_ingest_attempts"])
        self.assertEqual(upgraded_columns, fresh_columns)
        self.assertEqual(
            upgraded_columns,
            FRESH_INSTALL_TABLE_COLUMNS["rejected_ingest_attempts"],
        )
        self.assertEqual(upgraded_indexes, fresh_indexes)
        self.assertEqual(
            upgraded_indexes,
            FRESH_INSTALL_CREATED_INDEXES["rejected_ingest_attempts"],
        )
        self.assertEqual(upgraded_auto_indexes, fresh_auto_indexes)
        self.assertEqual(
            list(upgraded_auto_indexes.values()),
            [("pk", 1, ("source_id_claimed", "error_type", "day"))],
        )

    def test_fact_revisions_upgrade_backfills_rows_without_rewinding_existing_watermarks(self) -> None:
        migration = (MIGRATIONS_DIR / "0010_fact_revisions.sql").read_text(encoding="utf-8")
        with sqlite3.connect(":memory:") as conn:
            conn.executescript(MIGRATION_SQL.read_text(encoding="utf-8"))
            for hour, amount in (("10", 100), ("11", 200)):
                conn.execute("""
                    INSERT INTO usage_hourly_facts (
                        fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id,
                        agent, client, window_start, window_end, timezone, total_tokens,
                        attribution_confidence, provenance, first_seen_at, last_seen_at
                    ) VALUES (?, 'upgrade-device', 'machine', 'tester', 'openai', 'account',
                              'codex', 'codex', ?, ?, 'Asia/Shanghai', ?,
                              'unconfirmed_local_source', 'local-ledger', ?, ?)
                """, (f"fact-{hour}", f"2026-07-12T{hour}:00:00+08:00", f"2026-07-12T{hour}:59:59+08:00",
                      amount, "2026-07-18T01:00:00+00:00", "2026-07-18T01:03:00+00:00"))
            before = conn.execute("SELECT * FROM usage_hourly_facts ORDER BY fact_id").fetchall()
            self.assertEqual(len(before), 2)
            conn.execute("DROP TABLE usage_fact_revisions")
            conn.executescript(migration)
            self.assertEqual(_table_columns(conn, "usage_fact_revisions"), FRESH_INSTALL_TABLE_COLUMNS["usage_fact_revisions"])
            self.assertEqual(conn.execute("SELECT observed_at FROM usage_fact_revisions ORDER BY window_start").fetchall(),
                             [("2026-07-18T01:03:00+00:00",)] * 2)
            conn.execute("UPDATE usage_fact_revisions SET observed_at = '2026-07-18T01:09:00+00:00'")
            conn.executescript(migration)
            self.assertEqual(conn.execute("SELECT observed_at FROM usage_fact_revisions ORDER BY window_start").fetchall(),
                             [("2026-07-18T01:09:00+00:00",)] * 2)
            self.assertEqual(conn.execute("SELECT * FROM usage_hourly_facts ORDER BY fact_id").fetchall(), before)

    def test_projection_recovery_upgrade_matches_schema_and_tracks_only_usage_changes(self) -> None:
        migration = (MIGRATIONS_DIR / "0011_reconciliation_and_projection_recovery.sql").read_text(encoding="utf-8")
        trigger_names = ["usage_rollup_dirty_insert", "usage_rollup_dirty_update", "usage_rollup_dirty_delete"]
        with sqlite3.connect(":memory:") as conn:
            conn.executescript(MIGRATION_SQL.read_text(encoding="utf-8"))
            expected_triggers = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY name").fetchall()
            self.assertEqual([row[0] for row in expected_triggers], sorted(trigger_names))
            for name in trigger_names:
                conn.execute(f"DROP TRIGGER {name}")
            conn.execute("DROP TABLE usage_rollup_dirty_days")
            conn.execute("DROP TABLE usage_reconciliation_ranges")
            conn.execute("""
                INSERT INTO usage_hourly_facts (
                    fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id,
                    agent, client, window_start, window_end, timezone, total_tokens,
                    attribution_confidence, provenance, first_seen_at, last_seen_at
                ) VALUES ('fact', 'source', 'machine', 'tester', 'openai', 'account',
                          'codex', 'codex', '2026-07-11T17:00:00+00:00', '2026-07-11T18:00:00+00:00',
                          'Asia/Shanghai', 100, 'observed', 'local-ledger', '2026-07-18T01:00:00Z', '2026-07-18T01:00:00Z')
            """)
            conn.execute("""
                INSERT INTO source_accuracy (source_id, agent, provenance, mode, coverage_start, coverage_end,
                    scan_complete, read_errors, unresolved_mismatch, matching_full_scans, accuracy_status,
                    observed_at, first_seen_at, last_seen_at)
                VALUES ('source', 'codex', 'local-ledger', 'full-rescan', '2026-07-12T00:00:00+08:00',
                        '2026-07-13T00:00:00+08:00', 1, 0, 0, 2, 'verified',
                        '2026-07-18T01:04:00Z', '2026-07-18T01:04:00Z', '2026-07-18T01:04:00Z')
            """)
            conn.executescript(migration)
            for table in ("usage_rollup_dirty_days", "usage_reconciliation_ranges"):
                self.assertEqual(_table_columns(conn, table), FRESH_INSTALL_TABLE_COLUMNS[table])
            self.assertEqual(conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY name").fetchall(), expected_triggers)
            self.assertEqual(conn.execute("SELECT date FROM usage_rollup_dirty_days").fetchall(), [("2026-07-12",)])
            self.assertEqual(conn.execute("SELECT observed_at FROM usage_reconciliation_ranges").fetchall(), [("2026-07-18T01:04:00Z",)])
            conn.execute("UPDATE usage_reconciliation_ranges SET observed_at = '2026-07-18T01:09:00Z'")
            conn.executescript(migration)
            self.assertEqual(conn.execute("SELECT observed_at FROM usage_reconciliation_ranges").fetchall(), [("2026-07-18T01:09:00Z",)])
            conn.execute("DELETE FROM usage_rollup_dirty_days")
            conn.execute("UPDATE usage_hourly_facts SET last_seen_at = '2026-07-18T01:10:00Z'")
            self.assertEqual(conn.execute("SELECT date FROM usage_rollup_dirty_days").fetchall(), [])
            conn.execute("UPDATE usage_hourly_facts SET total_tokens = 200")
            self.assertEqual(conn.execute("SELECT date FROM usage_rollup_dirty_days").fetchall(), [("2026-07-12",)])
            conn.execute("DELETE FROM usage_rollup_dirty_days")
            conn.execute("UPDATE usage_hourly_facts SET window_start = '2026-07-12T17:00:00Z'")
            self.assertEqual(conn.execute("SELECT date FROM usage_rollup_dirty_days ORDER BY date").fetchall(), [("2026-07-12",), ("2026-07-13",)])
            conn.execute("DELETE FROM usage_rollup_dirty_days")
            conn.execute("DELETE FROM usage_hourly_facts")
            self.assertEqual(conn.execute("SELECT date FROM usage_rollup_dirty_days").fetchall(), [("2026-07-13",)])

    def test_backfilled_indexes_match_their_owning_migration(self) -> None:
        """Every index a later migration declares must already exist in a 0001-only
        database, with the definition that migration itself produces.

        This is deliberately independent of the two-path parity test above, which
        cannot see this class of bug: later migrations use CREATE INDEX IF NOT
        EXISTS, and the chain replays 0001 first, so a wrong backfill in 0001 is
        inherited by the chain and both paths agree on the same wrong index.
        (Proven by mutation: renaming the indexed column in 0001 leaves the parity
        test green.) It is also independent of the deleted
        storage_sqlite.py mirror (#74), so the invariant rests on nothing but
        the migrations themselves.

        Method: build from 0001 alone, drop the indexes the migration owns, replay
        that migration, and compare -- the owning migration is the source of truth
        for its own indexes, nothing here is hand-written."""
        migrations = _all_migration_files()
        checked = 0

        for migration in migrations[1:]:
            declared = _declared_index_names(migration)
            if not declared:
                continue
            checked += len(declared)
            with self.subTest(migration=migration.name):
                with sqlite3.connect(":memory:") as conn:
                    conn.executescript(MIGRATION_SQL.read_text(encoding="utf-8"))
                    fresh = _index_definitions(conn)
                    missing = [name for name in declared if name not in fresh]
                    self.assertEqual(
                        missing,
                        [],
                        f"{migration.name} creates these indexes but 0001 does not: "
                        f"{missing}. A database created by 0001 alone (this repo's "
                        f"fresh-install path) would never get them.",
                    )

                    for name in declared:
                        conn.execute(f"DROP INDEX {name}")
                    conn.executescript(migration.read_text(encoding="utf-8"))
                    replayed = _index_definitions(conn)

                for name in declared:
                    self.assertIn(name, replayed, f"{migration.name} did not recreate {name}")
                    self.assertEqual(
                        fresh[name],
                        replayed[name],
                        f"0001 backfilled {name} with a different definition than "
                        f"{migration.name} creates (table/unique/partial/columns)",
                    )

        # Guards the guard: if the regex ever stops matching, this test would pass
        # by checking nothing at all. Counts what was declared, not what passed, so
        # a real backfill failure above shows up as one failure and not two.
        self.assertGreaterEqual(checked, 5)

    def _legacy_db_with_rows(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.executescript(LEGACY_SOURCE_REPORT_STATES_DDL)
        conn.executemany(
            "INSERT INTO source_report_states VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            LEGACY_SOURCE_REPORT_STATES_ROWS,
        )
        self.assertEqual(
            len(_table_columns(conn, "source_report_states")),
            10,
            "fixture must start from the deployed pre-0007 layout",
        )
        return conn

    def test_collector_version_migration_upgrades_deployed_table_without_data_loss(self) -> None:
        """The path 0007 actually exists for: a database already on 0006, holding
        rows, in the 10-column shape. The full-chain test cannot cover this because
        0001 now creates collector_version itself, so there 0007 is only an
        equivalent recreate. Here it must really append the column -- and because
        0007 rebuilds (CREATE v2 / INSERT SELECT / DROP / RENAME) rather than
        ALTER TABLE ADD COLUMN, every existing row and the PK auto-index are at
        risk of being silently dropped."""
        self.assertTrue(
            COLLECTOR_VERSION_MIGRATION_SQL.exists(),
            f"Missing migration: {COLLECTOR_VERSION_MIGRATION_SQL}",
        )

        with self._legacy_db_with_rows() as conn:
            before_rows = conn.execute(
                "SELECT * FROM source_report_states ORDER BY source_id"
            ).fetchall()
            before_auto_indexes = _auto_indexes(conn, "source_report_states")

            conn.executescript(
                COLLECTOR_VERSION_MIGRATION_SQL.read_text(encoding="utf-8")
            )

            after_columns = _table_columns(conn, "source_report_states")
            after_rows = conn.execute(
                "SELECT * FROM source_report_states ORDER BY source_id"
            ).fetchall()
            after_auto_indexes = _auto_indexes(conn, "source_report_states")
            leftover_tables = _user_tables(conn)

        # Column appended, and appended LAST -- ADD COLUMN can only append, so any
        # other position would fork the fresh-install layout from this one.
        self.assertEqual(len(after_columns), 11)
        self.assertEqual(after_columns[-1], ("collector_version", "TEXT", 0, None, 0))
        self.assertEqual(after_columns, D1_ONLY_TABLE_COLUMNS["source_report_states"])

        # Every pre-existing row survives the rebuild, field for field, including
        # the NULL/non-NULL mix; only the new trailing NULL is added.
        self.assertEqual(len(after_rows), len(LEGACY_SOURCE_REPORT_STATES_ROWS))
        self.assertEqual(
            [row[:10] for row in after_rows],
            list(before_rows),
        )
        self.assertEqual(
            sorted(row[:10] for row in after_rows),
            sorted(LEGACY_SOURCE_REPORT_STATES_ROWS),
        )

        # Existing rows carry no collector_version: 0007's INSERT ... SELECT only
        # copies the 10 legacy columns, so backfill happens on the next ingest.
        self.assertEqual([row[10] for row in after_rows], [None, None])

        # The PK auto-index must come back with the rebuilt table.
        self.assertEqual(after_auto_indexes, before_auto_indexes)
        self.assertEqual(
            after_auto_indexes,
            {"sqlite_autoindex_source_report_states_1": ("pk", 1, ("source_id",))},
        )

        # The scratch table must not outlive the migration.
        self.assertEqual(leftover_tables, ["source_report_states"])

    def test_collector_version_migration_rerun_keeps_schema_but_resets_collector_version(self) -> None:
        """Characterization of re-running 0007 by hand on an already-upgraded
        database: structurally repeatable, NOT value-preserving.

        The layout stays identical and nothing errors, but the INSERT ... SELECT
        lists the 10 legacy columns only, so a second run copies those across and
        leaves collector_version NULL again -- silently discarding every version
        already recorded. Harmless under `wrangler d1 migrations apply` (an
        applied migration is never replayed); a data hazard for anyone running
        the file manually.

        This defect is deliberately accepted rather than fixed. The obvious fix,
        `INSERT INTO ..._v2 SELECT *, NULL`, aborts a re-run instead of wiping
        data -- but it breaks the fresh-install path: 0001 already creates the
        11-column table, so replaying 0001..0007 on a brand new D1 would feed 12
        values into 11 columns and fail the whole deploy (proven by
        test_full_migration_chain_matches_fresh_schema going red when
        that variant was tried). Supporting both real deployment paths requires
        the explicit column list.

        Locked in so the property cannot change unnoticed. If 0007 is ever made
        value-preserving, this expectation must be updated deliberately -- and
        the fresh-install path must be re-verified."""
        with self._legacy_db_with_rows() as conn:
            migration_sql = COLLECTOR_VERSION_MIGRATION_SQL.read_text(encoding="utf-8")
            conn.executescript(migration_sql)
            conn.execute(
                "UPDATE source_report_states SET collector_version = ? WHERE source_id = ?",
                ("2.4.0", "linux-biai-wang"),
            )
            first_columns = _table_columns(conn, "source_report_states")

            conn.executescript(migration_sql)

            second_columns = _table_columns(conn, "source_report_states")
            rows = conn.execute(
                "SELECT * FROM source_report_states ORDER BY source_id"
            ).fetchall()
            auto_indexes = _auto_indexes(conn, "source_report_states")
            leftover_tables = _user_tables(conn)

        self.assertEqual(second_columns, first_columns)
        self.assertEqual(second_columns, D1_ONLY_TABLE_COLUMNS["source_report_states"])
        self.assertEqual(
            sorted(row[:10] for row in rows),
            sorted(LEGACY_SOURCE_REPORT_STATES_ROWS),
        )
        # The '2.4.0' written above is gone: this is the accepted data hazard.
        self.assertEqual([row[10] for row in rows], [None, None])
        self.assertEqual(
            auto_indexes,
            {"sqlite_autoindex_source_report_states_1": ("pk", 1, ("source_id",))},
        )
        self.assertEqual(leftover_tables, ["source_report_states"])

    def test_limit_window_migration_keeps_latest_row_for_stable_key(self) -> None:
        with sqlite3.connect(":memory:") as conn:
            conn.executescript(MIGRATION_SQL.read_text(encoding="utf-8").replace(
                "PRIMARY KEY(source_id, provider, window)",
                "PRIMARY KEY(source_id, provider, source_type, window)",
            ))
            rows = [
                ("linux-biai-wang", "claude", "week", 20, 80, "2026-07-20T00:00:00+08:00", 10080,
                 "official_cli", "observed", "ok", "2026-07-18T10:00:00+08:00", "a", "a"),
                ("linux-biai-wang", "claude", "week", 21, 79, "2026-07-20T00:00:00+08:00", 10080,
                 "oauth_usage_api", "observed", "ok", "2026-07-18T03:00:00+00:00", "b", "b"),
            ]
            conn.executemany("INSERT INTO limit_windows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            conn.executescript(LIMIT_STABLE_KEY_MIGRATION_SQL.read_text(encoding="utf-8"))
            actual = conn.execute(
                "SELECT source_type, used_percent FROM limit_windows"
            ).fetchall()
            pk_columns = [
                row[1] for row in sorted(conn.execute("PRAGMA table_info(limit_windows)"), key=lambda row: row[5]) if row[5]
            ]

        self.assertEqual(actual, [("oauth_usage_api", 21.0)])
        self.assertEqual(pk_columns, ["source_id", "provider", "window"])
