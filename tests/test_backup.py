from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest

from ai_usage_widget.backup import backup_sqlite


class TestSQLiteBackup(unittest.TestCase):
    def test_backup_sqlite_uses_integrity_check_and_creates_copy(self) -> None:
        db_fd, db_path = tempfile.mkstemp(suffix=".sqlite")
        backup_dir = tempfile.mkdtemp()
        os.close(db_fd)
        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE usage_daily (id INTEGER PRIMARY KEY, total_tokens INTEGER)")
                conn.execute("INSERT INTO usage_daily (total_tokens) VALUES (123)")

            result = backup_sqlite(db_path, backup_dir, timestamp="2026-06-02T12-00-00")

            self.assertTrue(result["success"])
            self.assertTrue(os.path.exists(result["backup_path"]))
            self.assertIn("2026-06-02T12-00-00", os.path.basename(result["backup_path"]))
            with sqlite3.connect(result["backup_path"]) as conn:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                count = conn.execute("SELECT count(*) FROM usage_daily").fetchone()[0]
            self.assertEqual(integrity, "ok")
            self.assertEqual(count, 1)
        finally:
            for root, _, files in os.walk(backup_dir, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                os.rmdir(root)
            if os.path.exists(db_path):
                os.remove(db_path)


if __name__ == "__main__":
    unittest.main()
