from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

from ai_usage_widget.limits import LimitWindow
from ai_usage_widget.limits_runtime import LimitsRuntime, ProviderRuntimeResult


class FakeProvider:
    def __init__(self, windows: list[LimitWindow]) -> None:
        self.windows = windows
        self.calls = 0

    def collect(self) -> list[LimitWindow]:
        self.calls += 1
        return self.windows


class FailingProvider:
    def collect(self) -> list[LimitWindow]:
        raise RuntimeError("provider boom with token should not be stored")


class TestLimitsRuntime(unittest.TestCase):
    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        self.out_fd, self.out_path = tempfile.mkstemp(suffix=".json")

    def tearDown(self) -> None:
        os.close(self.db_fd)
        os.close(self.out_fd)
        for path in [self.db_path, self.out_path]:
            if os.path.exists(path):
                os.remove(path)

    def test_runtime_writes_fake_provider_windows_and_rebuilds_snapshot(self) -> None:
        codex_window = LimitWindow(
            provider="codex",
            window="session",
            used_percent=41.2,
            remaining_percent=58.8,
            reset_at="2026-06-03T14:00:00+08:00",
            window_duration_minutes=300,
            observed_at="2026-06-03T10:00:00+08:00",
            source_type="runtime_api",
            confidence="observed",
            status="ok",
        )
        claude_window = LimitWindow(
            provider="claude",
            window="week",
            used_percent=31.5,
            remaining_percent=68.5,
            reset_at="2026-06-09T00:00:00+08:00",
            window_duration_minutes=10080,
            observed_at="2026-06-03T10:01:00+08:00",
            source_type="oauth_usage_api",
            confidence="observed",
            status="ok",
        )
        codex = FakeProvider([codex_window])
        claude = FakeProvider([claude_window])

        result = LimitsRuntime(
            db_path=self.db_path,
            timezone="Asia/Shanghai",
            providers={"codex": codex, "claude": claude},
            now_provider=lambda: "2026-06-03T10:02:00+08:00",
        ).collect(provider_names=["codex", "claude"])

        self.assertTrue(result.success)
        self.assertEqual(result.windows_written, 2)
        self.assertEqual([row.provider for row in result.provider_results], ["codex", "claude"])
        self.assertEqual(codex.calls, 1)
        self.assertEqual(claude.calls, 1)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT provider, window, source_type, confidence, status FROM limit_windows ORDER BY provider"
            ).fetchall()

        self.assertEqual(rows, [
            ("claude", "week", "oauth_usage_api", "observed", "ok"),
            ("codex", "session", "runtime_api", "observed", "ok"),
        ])

        # 原先这里还断言「latest.json 里能读到 limits」。那条快照重建路径依赖
        # snapshot_builder（服务端读模型），已按 #72 剪断——采集端不再重建快照，
        # 断言的对象不存在了。limit_windows 写入是本模块真正的职责，上面已断言。

    def test_runtime_collects_multiple_instances_of_same_provider(self) -> None:
        main_window = LimitWindow(
            provider="claude",
            source_id="claude-main",
            window="session",
            used_percent=20.0,
            remaining_percent=80.0,
            reset_at="2026-06-03T14:00:00+08:00",
            window_duration_minutes=300,
            observed_at="2026-06-03T10:00:00+08:00",
            source_type="official_cli",
            confidence="observed",
            status="ok",
        )
        work_window = LimitWindow(
            provider="claude",
            source_id="claude-w",
            window="session",
            used_percent=50.0,
            remaining_percent=50.0,
            reset_at="2026-06-03T15:00:00+08:00",
            window_duration_minutes=300,
            observed_at="2026-06-03T10:01:00+08:00",
            source_type="official_cli",
            confidence="observed",
            status="ok",
        )
        main = FakeProvider([main_window])
        work = FakeProvider([work_window])

        result = LimitsRuntime(
            db_path=self.db_path,
            timezone="Asia/Shanghai",
            providers={"claude-main": main, "claude-w": work},
            now_provider=lambda: "2026-06-03T10:02:00+08:00",
        ).collect(provider_names=["claude-main", "claude-w"])

        self.assertTrue(result.success)
        self.assertEqual([row.provider for row in result.provider_results], ["claude-main", "claude-w"])
        self.assertEqual(main.calls, 1)
        self.assertEqual(work.calls, 1)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT source_id, provider, window, used_percent FROM limit_windows ORDER BY source_id"
            ).fetchall()
        self.assertEqual(rows, [
            ("claude-main", "claude", "session", 20.0),
            ("claude-w", "claude", "session", 50.0),
        ])

    def test_runtime_writes_failed_window_without_local_history_fallback(self) -> None:
        result = LimitsRuntime(
            db_path=self.db_path,
            timezone="Asia/Shanghai",
            providers={"codex": FailingProvider()},
            now_provider=lambda: "2026-06-03T10:02:00+08:00",
        ).collect(provider_names=["codex"])

        self.assertFalse(result.success)
        self.assertEqual(result.provider_results, [
            ProviderRuntimeResult(provider="codex", status="provider_failed", windows_written=1, error_type="provider_failed")
        ])

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT provider, window, source_type, confidence, status FROM limit_windows"
            ).fetchone()

        self.assertEqual(row, ("codex", "unknown", "provider_runtime", "missing", "provider_failed"))

    def test_runtime_does_not_report_cached_only_provider_as_success(self) -> None:
        cached = LimitWindow(
            provider="claude",
            source_id="claude-main",
            window="week",
            used_percent=31.0,
            remaining_percent=69.0,
            reset_at="2026-06-09T00:00:00+08:00",
            window_duration_minutes=10080,
            observed_at="2026-06-03T10:00:00+08:00",
            source_type="active_limits_cache",
            confidence="estimated",
            status="unavailable",
        )

        result = LimitsRuntime(
            db_path=self.db_path,
            timezone="Asia/Shanghai",
            providers={"claude-main": FakeProvider([cached])},
            now_provider=lambda: "2026-06-03T10:02:00+08:00",
        ).collect(provider_names=["claude-main"], dry_run=True)

        self.assertFalse(result.success)
        self.assertEqual(result.provider_results, [
            ProviderRuntimeResult(
                provider="claude-main",
                status="unavailable",
                windows_written=0,
                error_type="provider_unavailable",
            )
        ])
        self.assertEqual(result.windows, [cached])

    def test_runtime_dry_run_collects_without_writing_sqlite_or_snapshot(self) -> None:
        os.close(self.db_fd)
        os.close(self.out_fd)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        if os.path.exists(self.out_path):
            os.remove(self.out_path)
        self.db_fd = os.open(os.devnull, os.O_RDONLY)
        self.out_fd = os.open(os.devnull, os.O_RDONLY)

        codex_window = LimitWindow(
            provider="codex",
            window="session",
            used_percent=41.2,
            remaining_percent=58.8,
            reset_at="2026-06-03T14:00:00+08:00",
            window_duration_minutes=300,
            observed_at="2026-06-03T10:00:00+08:00",
            source_type="runtime_api",
            confidence="observed",
            status="ok",
        )

        result = LimitsRuntime(
            db_path=self.db_path,
            timezone="Asia/Shanghai",
            providers={"codex": FakeProvider([codex_window])},
            now_provider=lambda: "2026-06-03T10:02:00+08:00",
        ).collect(provider_names=["codex"], dry_run=True)

        self.assertTrue(result.success)
        self.assertEqual(result.windows_written, 0)
        self.assertEqual(result.provider_results[0].windows_written, 0)
        self.assertFalse(os.path.exists(self.db_path))
        self.assertFalse(os.path.exists(self.out_path))

    def test_runtime_rejects_unknown_provider_without_writing(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            LimitsRuntime(
                db_path=self.db_path,
                timezone="Asia/Shanghai",
                providers={},
                now_provider=lambda: "2026-06-03T10:02:00+08:00",
            ).collect(provider_names=["gemini"])

        self.assertIn("unsupported limits provider", str(ctx.exception))
        with sqlite3.connect(self.db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        self.assertNotIn("limit_windows", tables)

    def test_runtime_rejects_empty_provider_list_without_writing(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            LimitsRuntime(
                db_path=self.db_path,
                timezone="Asia/Shanghai",
                providers={},
                now_provider=lambda: "2026-06-03T10:02:00+08:00",
            ).collect(provider_names=[])

        self.assertIn("no limits providers enabled", str(ctx.exception))
        with sqlite3.connect(self.db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        self.assertNotIn("limit_windows", tables)


if __name__ == "__main__":
    unittest.main()
