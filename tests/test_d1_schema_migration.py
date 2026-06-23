from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai_usage_widget.storage_sqlite import _ensure_schema


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_SQL = REPO_ROOT / "cloudflare" / "migrations" / "0001_initial_schema.sql"


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
