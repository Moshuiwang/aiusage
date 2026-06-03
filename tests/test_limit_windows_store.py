from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from ai_usage_widget.limits import LimitWindow
from ai_usage_widget.storage_sqlite import write_limit_windows


class TestLimitWindowsStore(unittest.TestCase):
    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")

    def tearDown(self) -> None:
        os.close(self.db_fd)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_limit_windows_upsert_by_provider_source_type_and_window(self) -> None:
        first = LimitWindow(
            provider="codex",
            window="week",
            used_percent=37.5,
            remaining_percent=62.5,
            reset_at="2026-06-08T00:00:00+08:00",
            window_duration_minutes=10080,
            observed_at="2026-06-03T10:00:00+08:00",
            source_type="runtime_api",
            confidence="observed",
            status="ok",
        )
        updated = LimitWindow(
            provider="codex",
            window="week",
            used_percent=42.0,
            remaining_percent=58.0,
            reset_at="2026-06-08T01:00:00+08:00",
            window_duration_minutes=10080,
            observed_at="2026-06-03T10:05:00+08:00",
            source_type="runtime_api",
            confidence="observed",
            status="ok",
        )

        write_limit_windows(self.db_path, [first], seen_at="2026-06-03T10:00:00+08:00")
        write_limit_windows(self.db_path, [updated], seen_at="2026-06-03T10:05:00+08:00")

        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT count(*) FROM limit_windows").fetchone()[0]
            row = conn.execute(
                """
                SELECT used_percent, remaining_percent, reset_at, first_seen_at, last_seen_at
                FROM limit_windows
                WHERE provider='codex' AND source_type='runtime_api' AND window='week'
                """
            ).fetchone()

        self.assertEqual(count, 1)
        self.assertEqual(row[0], 42.0)
        self.assertEqual(row[1], 58.0)
        self.assertEqual(row[2], "2026-06-08T01:00:00+08:00")
        self.assertEqual(row[3], "2026-06-03T10:00:00+08:00")
        self.assertEqual(row[4], "2026-06-03T10:05:00+08:00")

    def test_limit_windows_preserve_confidence_and_source_type(self) -> None:
        window = LimitWindow(
            provider="claude",
            source_id="claude-main",
            window="session",
            used_percent=68.0,
            remaining_percent=32.0,
            reset_at="2026-06-03T15:30:00+08:00",
            window_duration_minutes=300,
            observed_at="2026-06-03T10:01:00+08:00",
            source_type="official_cli",
            confidence="observed",
            status="ok",
        )

        write_limit_windows(self.db_path, [window], seen_at="2026-06-03T10:01:00+08:00")

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT source_id, provider, window, source_type, confidence, status FROM limit_windows"
            ).fetchone()

        self.assertEqual(row, ("claude-main", "claude", "session", "official_cli", "observed", "ok"))

    def test_limit_windows_keep_multiple_accounts_for_same_provider(self) -> None:
        first = LimitWindow(
            provider="claude",
            source_id="claude-main",
            window="session",
            used_percent=68.0,
            remaining_percent=32.0,
            reset_at="2026-06-03T15:30:00+08:00",
            window_duration_minutes=300,
            observed_at="2026-06-03T10:01:00+08:00",
            source_type="official_cli",
            confidence="observed",
            status="ok",
        )
        second = LimitWindow(
            provider="claude",
            source_id="claude-w",
            window="session",
            used_percent=12.0,
            remaining_percent=88.0,
            reset_at="2026-06-03T16:30:00+08:00",
            window_duration_minutes=300,
            observed_at="2026-06-03T10:02:00+08:00",
            source_type="official_cli",
            confidence="observed",
            status="ok",
        )

        write_limit_windows(self.db_path, [first, second], seen_at="2026-06-03T10:02:00+08:00")

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT source_id, provider, window, used_percent
                FROM limit_windows
                ORDER BY source_id
                """
            ).fetchall()

        self.assertEqual(rows, [
            ("claude-main", "claude", "session", 68.0),
            ("claude-w", "claude", "session", 12.0),
        ])

    def test_success_window_clears_prior_provider_failed_placeholder_for_same_account(self) -> None:
        failed = LimitWindow(
            provider="claude",
            source_id="claude-main",
            window="unknown",
            used_percent=0,
            remaining_percent=0,
            reset_at="2026-06-03T10:00:00+08:00",
            window_duration_minutes=0,
            observed_at="2026-06-03T10:00:00+08:00",
            source_type="provider_runtime",
            confidence="missing",
            status="provider_failed",
        )
        recovered = LimitWindow(
            provider="claude",
            source_id="claude-main",
            window="session",
            used_percent=12,
            remaining_percent=88,
            reset_at="2026-06-03T15:00:00+08:00",
            window_duration_minutes=300,
            observed_at="2026-06-03T10:05:00+08:00",
            source_type="active_limits_cache",
            confidence="observed",
            status="ok",
        )

        write_limit_windows(self.db_path, [failed], seen_at="2026-06-03T10:00:00+08:00")
        write_limit_windows(self.db_path, [recovered], seen_at="2026-06-03T10:05:00+08:00")

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT source_id, provider, window, source_type, status
                FROM limit_windows
                ORDER BY source_type
                """
            ).fetchall()

        self.assertEqual(rows, [
            ("claude-main", "claude", "session", "active_limits_cache", "ok"),
        ])

    def test_limit_windows_write_without_usage_rows(self) -> None:
        window = LimitWindow(
            provider="codex",
            window="session",
            used_percent=41.2,
            remaining_percent=58.8,
            reset_at="2026-06-03T14:00:00+08:00",
            window_duration_minutes=300,
            observed_at="2026-06-03T09:30:00+08:00",
            source_type="runtime_api",
            confidence="observed",
            status="ok",
        )

        write_limit_windows(self.db_path, [window], seen_at="2026-06-03T09:30:00+08:00")

        with sqlite3.connect(self.db_path) as conn:
            usage_count = conn.execute("SELECT count(*) FROM usage_daily").fetchone()[0]
            limits_count = conn.execute("SELECT count(*) FROM limit_windows").fetchone()[0]
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]

        self.assertEqual(usage_count, 0)
        self.assertEqual(limits_count, 1)
        self.assertEqual(journal_mode.lower(), "wal")
        self.assertEqual(busy_timeout, 5000)

    def test_limit_windows_schema_does_not_store_secrets_or_raw_provider_response(self) -> None:
        write_limit_windows(self.db_path, [], seen_at="2026-06-03T09:30:00+08:00")

        with sqlite3.connect(self.db_path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(limit_windows)")}

        self.assertNotIn("token", columns)
        self.assertNotIn("cookie", columns)
        self.assertNotIn("raw_json", columns)
        self.assertNotIn("raw_response", columns)


if __name__ == "__main__":
    unittest.main()
