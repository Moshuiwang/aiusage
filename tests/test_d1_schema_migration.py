from __future__ import annotations

import re
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai_usage_widget.storage_sqlite import _ensure_schema


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = REPO_ROOT / "cloudflare" / "migrations"
MIGRATION_SQL = MIGRATIONS_DIR / "0001_initial_schema.sql"
LIMIT_STABLE_KEY_MIGRATION_SQL = MIGRATIONS_DIR / "0003_limit_window_stable_key.sql"
COLLECTOR_VERSION_MIGRATION_SQL = (
    MIGRATIONS_DIR / "0007_source_report_states_collector_version.sql"
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

            canonical_actual_tables = [table for table in actual_tables if table not in D1_ONLY_TABLE_COLUMNS]
            canonical_actual_columns = {
                table: columns for table, columns in actual_columns.items() if table not in D1_ONLY_TABLE_COLUMNS
            }
            canonical_actual_indexes = {
                table: indexes for table, indexes in actual_indexes.items() if table not in D1_ONLY_TABLE_COLUMNS
            }

            self.assertEqual(canonical_actual_tables, expected_tables)
            self.assertEqual(canonical_actual_columns, expected_columns)
            self.assertEqual(canonical_actual_indexes, expected_indexes)
            for table, expected_columns in D1_ONLY_TABLE_COLUMNS.items():
                self.assertIn(table, actual_tables)
                self.assertEqual(actual_columns[table], expected_columns)
                self.assertEqual(actual_indexes[table], {})

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

    def test_backfilled_indexes_match_their_owning_migration(self) -> None:
        """Every index a later migration declares must already exist in a 0001-only
        database, with the definition that migration itself produces.

        This is deliberately independent of the two-path parity test above, which
        cannot see this class of bug: later migrations use CREATE INDEX IF NOT
        EXISTS, and the chain replays 0001 first, so a wrong backfill in 0001 is
        inherited by the chain and both paths agree on the same wrong index.
        (Proven by mutation: renaming the indexed column in 0001 leaves the parity
        test green.) It is also independent of the storage_sqlite.py mirror, which
        is frozen and slated for deletion, so the invariant must not rest on it.

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
