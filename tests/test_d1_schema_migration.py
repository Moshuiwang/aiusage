from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai_usage_widget.storage_sqlite import _ensure_schema


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_SQL = REPO_ROOT / "cloudflare" / "migrations" / "0001_initial_schema.sql"
LIMIT_STABLE_KEY_MIGRATION_SQL = REPO_ROOT / "cloudflare" / "migrations" / "0003_limit_window_stable_key.sql"


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
    indexes = {}
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        name = row[1]
        origin = row[3]
        if origin != "c":
            continue
        columns = tuple(
            info[2]
            for info in conn.execute(f"PRAGMA index_info({name})").fetchall()
        )
        indexes[name] = (row[2], columns)
    return indexes


class TestD1SchemaMigration(unittest.TestCase):
    def test_initial_d1_migration_matches_sqlite_schema(self) -> None:
        self.assertTrue(MIGRATION_SQL.exists(), f"Missing migration: {MIGRATION_SQL}")

        with tempfile.TemporaryDirectory() as tmpdir:
            sqlite_path = Path(tmpdir) / "sqlite.sqlite"
            d1_path = Path(tmpdir) / "d1.sqlite"

            with sqlite3.connect(sqlite_path) as conn:
                _ensure_schema(conn)
                expected_tables = _user_tables(conn)
                expected_columns = {table: _table_columns(conn, table) for table in expected_tables}
                expected_indexes = {table: _created_indexes(conn, table) for table in expected_tables}

            with sqlite3.connect(d1_path) as conn:
                conn.executescript(MIGRATION_SQL.read_text(encoding="utf-8"))
                actual_tables = _user_tables(conn)
                actual_columns = {table: _table_columns(conn, table) for table in actual_tables}
                actual_indexes = {table: _created_indexes(conn, table) for table in actual_tables}

            self.assertEqual(actual_tables, expected_tables)
            self.assertEqual(actual_columns, expected_columns)
            self.assertEqual(actual_indexes, expected_indexes)

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
