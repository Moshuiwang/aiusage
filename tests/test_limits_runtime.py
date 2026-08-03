from __future__ import annotations

import inspect
import os
import tempfile
import unittest
from pathlib import Path

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
    def test_runtime_collects_fake_provider_windows_in_memory_only(self) -> None:
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
            timezone="Asia/Shanghai",
            providers={"codex": codex, "claude": claude},
            now_provider=lambda: "2026-06-03T10:02:00+08:00",
        ).collect(provider_names=["codex", "claude"])

        self.assertTrue(result.success)
        self.assertEqual([row.provider for row in result.provider_results], ["codex", "claude"])
        self.assertEqual([row.windows_collected for row in result.provider_results], [1, 1])
        self.assertEqual(codex.calls, 1)
        self.assertEqual(claude.calls, 1)

        # 采集结果只存在于返回值里（PM-2：本地 SQLite 落库已停止，D1 是唯一正本）。
        # 强度对齐原先的 limit_windows 行断言：字段逐项钉死，不只数个数。
        self.assertEqual(
            sorted(
                (w.provider, w.window, w.source_type, w.confidence, w.status)
                for w in result.windows
            ),
            [
                ("claude", "week", "oauth_usage_api", "observed", "ok"),
                ("codex", "session", "runtime_api", "observed", "ok"),
            ],
        )

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
            timezone="Asia/Shanghai",
            providers={"claude-main": main, "claude-w": work},
            now_provider=lambda: "2026-06-03T10:02:00+08:00",
        ).collect(provider_names=["claude-main", "claude-w"])

        self.assertTrue(result.success)
        self.assertEqual([row.provider for row in result.provider_results], ["claude-main", "claude-w"])
        self.assertEqual(main.calls, 1)
        self.assertEqual(work.calls, 1)
        self.assertEqual(
            sorted((w.source_id, w.provider, w.window, w.used_percent) for w in result.windows),
            [
                ("claude-main", "claude", "session", 20.0),
                ("claude-w", "claude", "session", 50.0),
            ],
        )

    def test_runtime_reports_failed_window_without_local_history_fallback(self) -> None:
        result = LimitsRuntime(
            timezone="Asia/Shanghai",
            providers={"codex": FailingProvider()},
            now_provider=lambda: "2026-06-03T10:02:00+08:00",
        ).collect(provider_names=["codex"])

        self.assertFalse(result.success)
        self.assertEqual(result.provider_results, [
            ProviderRuntimeResult(
                provider="codex",
                status="provider_failed",
                windows_collected=1,
                error_type="provider_failed",
            )
        ])
        # 失败如实进结果，不用本地历史兜底（官方额度红线的采集端一侧）。
        self.assertEqual(
            [(w.provider, w.window, w.source_type, w.confidence, w.status) for w in result.windows],
            [("codex", "unknown", "provider_runtime", "missing", "provider_failed")],
        )

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
            timezone="Asia/Shanghai",
            providers={"claude-main": FakeProvider([cached])},
            now_provider=lambda: "2026-06-03T10:02:00+08:00",
        ).collect(provider_names=["claude-main"])

        self.assertFalse(result.success)
        self.assertEqual(result.provider_results, [
            ProviderRuntimeResult(
                provider="claude-main",
                status="unavailable",
                windows_collected=1,
                error_type="provider_unavailable",
            )
        ])
        self.assertEqual(result.windows, [cached])

    def test_runtime_never_touches_local_sqlite(self) -> None:
        """PM-2（2026-08-03）：collect-limits 停止写本地 SQLite，云端 D1 是唯一正本。

        三层钉死，防止落库路径被「顺手」加回来：
        1. 构造面：`LimitsRuntime` 不再接受 `db_path`；
        2. 源码面：模块不得 import storage_sqlite / sqlite3；
        3. 行为面：collect 在空目录里跑完不产生任何文件。
        """
        signature = inspect.signature(LimitsRuntime.__init__)
        self.assertNotIn("db_path", signature.parameters)

        source = Path(inspect.getsourcefile(LimitsRuntime)).read_text(encoding="utf-8")
        self.assertNotIn("storage_sqlite", source)
        self.assertNotIn("sqlite3", source)

        window = LimitWindow(
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
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                result = LimitsRuntime(
                    timezone="Asia/Shanghai",
                    providers={"codex": FakeProvider([window])},
                    now_provider=lambda: "2026-06-03T10:02:00+08:00",
                ).collect(provider_names=["codex"])
            finally:
                os.chdir(cwd)
            self.assertTrue(result.success)
            self.assertEqual(os.listdir(tmpdir), [])

    def test_runtime_rejects_unknown_provider(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            LimitsRuntime(
                timezone="Asia/Shanghai",
                providers={},
                now_provider=lambda: "2026-06-03T10:02:00+08:00",
            ).collect(provider_names=["gemini"])

        self.assertIn("unsupported limits provider", str(ctx.exception))

    def test_runtime_rejects_empty_provider_list(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            LimitsRuntime(
                timezone="Asia/Shanghai",
                providers={},
                now_provider=lambda: "2026-06-03T10:02:00+08:00",
            ).collect(provider_names=[])

        self.assertIn("no limits providers enabled", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
