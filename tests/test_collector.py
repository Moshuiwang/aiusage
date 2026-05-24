import json
import sqlite3
import unittest
from pathlib import Path

from ai_usage_widget.collector import collect


class CollectorTest(unittest.TestCase):
    def test_collect_file_import_writes_latest_and_sqlite(self):
        with self.subTest():
            import tempfile

            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                fixture = Path("tests/fixtures/ccusage_daily_sample.json").resolve()
                latest_path = temp_path / "latest.json"
                sqlite_path = temp_path / "usage.sqlite"
                config = {
                    "timezone": "Asia/Shanghai",
                    "sources": [
                        {
                            "source_id": "fixture",
                            "type": "file_import",
                            "enabled": True,
                            "host_label": "fixture-host",
                            "os_user": "tester",
                            "reports": {"daily": {"path": str(fixture)}},
                        }
                    ],
                }

                snapshot = collect(config, str(latest_path), str(sqlite_path))

                self.assertEqual(snapshot["source_status"], [{"source_id": "fixture", "status": "ok"}])
                saved = json.loads(latest_path.read_text(encoding="utf-8"))
                self.assertEqual(len(saved["items"]), 2)
                self.assertEqual(saved["items"][0]["machine"], "fixture-host")

                with sqlite3.connect(sqlite_path) as conn:
                    daily_count = conn.execute("SELECT COUNT(*) FROM usage_daily").fetchone()[0]
                    model_count = conn.execute("SELECT COUNT(*) FROM usage_daily_models").fetchone()[0]
                    run_status = conn.execute("SELECT status FROM collection_runs").fetchone()[0]

                self.assertEqual(daily_count, 2)
                self.assertEqual(model_count, 1)
                self.assertEqual(run_status, "ok")

    def test_collect_keeps_partial_failure_in_source_status(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fixture = Path("tests/fixtures/ccusage_daily_sample.json").resolve()
            latest_path = temp_path / "latest.json"
            sqlite_path = temp_path / "usage.sqlite"
            config = {
                "timezone": "Asia/Shanghai",
                "sources": [
                    {
                        "source_id": "ok-source",
                        "type": "file_import",
                        "enabled": True,
                        "host_label": "fixture-host",
                        "os_user": "tester",
                        "reports": {"daily": {"path": str(fixture)}},
                    },
                    {
                        "source_id": "missing-source",
                        "type": "file_import",
                        "enabled": True,
                        "host_label": "missing-host",
                        "os_user": "tester",
                        "reports": {"daily": {"path": str(temp_path / "missing.json")}},
                    },
                ],
            }

            snapshot = collect(config, str(latest_path), str(sqlite_path))

            self.assertEqual([row["status"] for row in snapshot["source_status"]], ["ok", "failed"])
            self.assertEqual(snapshot["source_status"][1]["error_type"], "missing_file")
            with sqlite3.connect(sqlite_path) as conn:
                run_status = conn.execute("SELECT status FROM collection_runs").fetchone()[0]
                report_count = conn.execute("SELECT COUNT(*) FROM source_reports").fetchone()[0]

            self.assertEqual(run_status, "partial_failed")
            self.assertEqual(report_count, 2)


if __name__ == "__main__":
    unittest.main()
