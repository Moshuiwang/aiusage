from __future__ import annotations

import json
import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ai_usage_widget import cli
from ai_usage_widget.limits import parse_limit_window


FIXTURES = Path(__file__).parent / "fixtures"


class TestCliLimits(unittest.TestCase):
    def setUp(self) -> None:
        self.default_now = patch(
            "ai_usage_widget.limits_runtime._default_now",
            return_value="2026-06-03T10:02:00+08:00",
        )
        self.default_now.start()

    def tearDown(self) -> None:
        self.default_now.stop()

    def test_collect_limits_fixture_collects_without_local_persistence(self) -> None:
        """PM-2（#74）：collect-limits 只采集并打印，不再写本地 SQLite。

        原先这里断言 limit_windows 表落库两行；落库已停止（#72 后零读取方，
        云端 D1 是唯一正本），等价强度改为钉死 JSON 输出的采集结果，
        并断言默认库路径不再被创建。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = os.getcwd()
            os.chdir(tmpdir)
            stdout = io.StringIO()
            try:
                with redirect_stdout(stdout):
                    code = cli.main([
                        "collect-limits",
                        "--provider-fixture",
                        str(FIXTURES / "limits_runtime_fixture.json"),
                    ])
            finally:
                os.chdir(cwd)

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["success"])
            self.assertEqual(payload["windows_collected"], 2)
            self.assertEqual(
                [(item["provider"], item["status"], item["windows_collected"]) for item in payload["providers"]],
                [("claude", "ok", 1), ("codex", "ok", 1)],
            )
            self.assertNotIn("windows_written", stdout.getvalue())
            # 旧默认路径 data/usage.sqlite 不再被创建；整个工作目录零文件副作用。
            self.assertEqual(os.listdir(tmpdir), [])

    def test_collect_limits_rejects_removed_sqlite_flag(self) -> None:
        """`--sqlite` 已随 PM-2 摘除；还在用旧旗标的调用要显式失败，不许静默忽略。"""
        with self.assertRaises(SystemExit) as ctx:
            cli.main([
                "collect-limits",
                "--provider-fixture",
                str(FIXTURES / "limits_runtime_fixture.json"),
                "--sqlite",
                "ignored.sqlite",
            ])
        self.assertEqual(ctx.exception.code, 2)

    def test_collect_limits_reports_runtime_error(self) -> None:
        class BrokenRuntime:
            def __init__(self, **kwargs) -> None:
                pass

            def collect(self, **kwargs):
                raise ValueError("unsupported limits provider: gemini")

        with patch.object(cli, "LimitsRuntime", BrokenRuntime):
            code = cli.main(["collect-limits", "--provider", "gemini"])

        self.assertEqual(code, 1)

    def test_collect_limits_rejects_empty_provider_set(self) -> None:
        code = cli.main(["collect-limits"])

        self.assertEqual(code, 1)

    def test_collect_limits_codex_requires_explicit_auth_file(self) -> None:
        code = cli.main(["collect-limits", "--provider", "codex"])

        self.assertEqual(code, 1)

    def test_collect_limits_codex_rpc_enables_explicit_provider(self) -> None:
        class FakeCodexRPCProvider:
            def __init__(self, **kwargs) -> None:
                pass

            def collect(self):
                return [
                    parse_limit_window(
                        {
                            "provider": "codex",
                            "window": "session",
                            "used_percent": 10,
                            "remaining_percent": 90,
                            "reset_at": "2026-06-03T14:30:00+08:00",
                            "window_duration_minutes": 300,
                            "observed_at": "2026-06-03T09:31:00+08:00",
                            "source_type": "cli_rpc",
                            "confidence": "observed",
                            "status": "ok",
                        }
                    )
                ]

        with patch.object(cli, "CodexAppServerRPCProvider", FakeCodexRPCProvider):
            code = cli.main([
                "collect-limits",
                "--provider",
                "codex",
                "--codex-rpc",
            ])

        self.assertEqual(code, 0)

    def test_collect_limits_claude_requires_explicit_auth_file_and_usage_url(self) -> None:
        code = cli.main(["collect-limits", "--provider", "claude"])

        self.assertEqual(code, 1)

    def test_collect_limits_claude_cli_enables_explicit_provider(self) -> None:
        class FakeClaudeCliProvider:
            def __init__(self, **kwargs) -> None:
                pass

            def collect(self):
                return [
                    parse_limit_window(
                        {
                            "provider": "claude",
                            "window": "session",
                            "used_percent": 20,
                            "remaining_percent": 80,
                            "reset_at": "2026-06-03T15:30:00+08:00",
                            "window_duration_minutes": 300,
                            "observed_at": "2026-06-03T10:01:00+08:00",
                            "source_type": "official_cli",
                            "confidence": "observed",
                            "status": "ok",
                        }
                    )
                ]

        with patch.object(cli, "ClaudeCliUsageProvider", FakeClaudeCliProvider):
            code = cli.main([
                "collect-limits",
                "--provider",
                "claude",
                "--claude-cli",
            ])

        self.assertEqual(code, 0)

    def test_collect_limits_uses_limits_config_with_fake_provider(self) -> None:
        class FakeClaudeCliProvider:
            def __init__(self, **kwargs) -> None:
                pass

            def collect(self):
                return [
                    parse_limit_window(
                        {
                            "provider": "claude",
                            "window": "session",
                            "used_percent": 20,
                            "remaining_percent": 80,
                            "reset_at": "2026-06-03T15:30:00+08:00",
                            "window_duration_minutes": 300,
                            "observed_at": "2026-06-03T10:01:00+08:00",
                            "source_type": "official_cli",
                            "confidence": "observed",
                            "status": "ok",
                        }
                    )
                ]

        db_fd, db_path = tempfile.mkstemp(suffix=".sqlite")
        config_fd, config_path = tempfile.mkstemp(suffix=".json")
        os.close(db_fd)
        os.close(config_fd)
        try:
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "timezone": "Asia/Shanghai",
                        "sqlite": db_path,
                        "latest": "/tmp/ai-usage-widget-limits-latest.json",
                        "providers": [{"provider": "claude", "cli": True}],
                    },
                    handle,
                )

            with patch.object(cli, "ClaudeCliUsageProvider", FakeClaudeCliProvider):
                code = cli.main([
                    "collect-limits",
                    "--limits-config",
                    config_path,
                ])
        finally:
            for path in [db_path, config_path]:
                if os.path.exists(path):
                    os.remove(path)

        self.assertEqual(code, 0)

    def test_collect_limits_check_config_outputs_redacted_plan(self) -> None:
        config_fd, config_path = tempfile.mkstemp(suffix=".json")
        os.close(config_fd)
        try:
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "timezone": "Asia/Shanghai",
                        "sqlite": "data/usage.sqlite",
                        "latest": "data/latest.json",
                        "providers": [
                            {
                                "provider": "codex",
                                "auth_file": "/Users/me/.codex/auth.json",
                                "rpc": True,
                                "rpc_sock": "/tmp/codex.sock",
                            }
                        ],
                    },
                    handle,
                )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = cli.main([
                    "collect-limits",
                    "--limits-config",
                    config_path,
                    "--check-config",
                ])
        finally:
            if os.path.exists(config_path):
                os.remove(config_path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["success"])
        self.assertTrue(payload["check_config"])
        self.assertTrue(payload["providers"][0]["has_auth_file"])
        self.assertNotIn("/Users/me", stdout.getvalue())
        self.assertNotIn("/tmp/codex.sock", stdout.getvalue())

    def test_collect_limits_check_config_redacts_cli_env_values(self) -> None:
        config_fd, config_path = tempfile.mkstemp(suffix=".json")
        os.close(config_fd)
        try:
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "timezone": "Asia/Shanghai",
                        "providers": [
                            {
                                "provider": "claude",
                                "source_id": "claude-w",
                                "cli": True,
                                "env": {"CLAUDE_CONFIG_DIR": "/Users/me/.claudew"},
                            }
                        ],
                    },
                    handle,
                )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = cli.main([
                    "collect-limits",
                    "--limits-config",
                    config_path,
                    "--check-config",
                ])
        finally:
            if os.path.exists(config_path):
                os.remove(config_path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["providers"][0]["source_id"], "claude-w")
        self.assertEqual(payload["providers"][0]["env_keys"], ["CLAUDE_CONFIG_DIR"])
        self.assertNotIn("/Users/me", stdout.getvalue())

    def test_collect_limits_check_config_requires_limits_config(self) -> None:
        code = cli.main(["collect-limits", "--check-config"])

        self.assertEqual(code, 1)

    def test_collect_limits_doctor_without_config_outputs_json_failure(self) -> None:
        stdout = io.StringIO()

        with redirect_stdout(stdout):
            code = cli.main(["collect-limits", "--doctor"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(payload["success"])
        self.assertTrue(payload["doctor"])
        self.assertEqual(payload["checks"][0]["status"], "missing")

    def test_collect_limits_doctor_outputs_redacted_readiness_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            auth_path = os.path.join(tmpdir, "codex-auth.json")
            sqlite_path = os.path.join(tmpdir, "usage.sqlite")
            latest_path = os.path.join(tmpdir, "latest.json")
            config_path = os.path.join(tmpdir, "limits.local.json")
            with open(auth_path, "w", encoding="utf-8") as handle:
                handle.write("{}")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "timezone": "Asia/Shanghai",
                        "sqlite": sqlite_path,
                        "latest": latest_path,
                        "providers": [
                            {
                                "provider": "codex",
                                "auth_file": auth_path,
                            }
                        ],
                    },
                    handle,
                )

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = cli.main([
                    "collect-limits",
                    "--limits-config",
                    config_path,
                    "--doctor",
                ])

            output = stdout.getvalue()
            payload = json.loads(output)
            self.assertEqual(code, 0)
            self.assertTrue(payload["success"])
            self.assertTrue(payload["providers"][0]["ready"])
            self.assertFalse(os.path.exists(sqlite_path))
            self.assertFalse(os.path.exists(latest_path))
            self.assertNotIn(tmpdir, output)

    def test_push_limits_fixture_posts_windows(self) -> None:
        calls = []

        def fake_push_limits(url, token, payload, timeout=10.0):
            calls.append((url, token, payload, timeout))
            return {"success": True, "windows_written": len(payload["windows"])}

        stdout = io.StringIO()
        with patch.object(cli, "push_limits_payload", fake_push_limits), redirect_stdout(stdout):
            code = cli.main([
                "push-limits",
                "--provider-fixture",
                str(FIXTURES / "limits_runtime_fixture.json"),
                "--url",
                "https://example.test/ingest-limits",
                "--token-env",
                "AI_USAGE_TEST_PUSH_TOKEN",
            ])

        self.assertEqual(code, 1)
        self.assertEqual(calls, [])

        with patch.dict(os.environ, {"AI_USAGE_TEST_PUSH_TOKEN": "secret-token"}):
            stdout = io.StringIO()
            with patch.object(cli, "push_limits_payload", fake_push_limits), redirect_stdout(stdout):
                code = cli.main([
                    "push-limits",
                    "--provider-fixture",
                    str(FIXTURES / "limits_runtime_fixture.json"),
                    "--url",
                    "https://example.test/ingest-limits",
                    "--token-env",
                    "AI_USAGE_TEST_PUSH_TOKEN",
                ])

        output = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(output["success"])
        self.assertEqual(output["windows_written"], 2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "https://example.test/ingest-limits")
        self.assertEqual(calls[0][1], "secret-token")
        self.assertEqual({row["source_id"] for row in calls[0][2]["windows"]}, {"claude", "codex"})

    def test_push_limits_dry_run_does_not_post(self) -> None:
        stdout = io.StringIO()
        with patch.object(cli, "push_limits_payload") as push_mock, redirect_stdout(stdout):
            code = cli.main([
                "push-limits",
                "--provider-fixture",
                str(FIXTURES / "limits_runtime_fixture.json"),
                "--url",
                "https://example.test/ingest-limits",
                "--dry-run",
            ])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["success"])
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["windows_collected"], 2)
        push_mock.assert_not_called()

    def test_push_limits_rejects_existing_lock_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = os.path.join(tmpdir, "limits-push.lock")
            with open(lock_path, "w", encoding="utf-8") as handle:
                handle.write("already-running")

            code = cli.main([
                "push-limits",
                "--provider-fixture",
                str(FIXTURES / "limits_runtime_fixture.json"),
                "--url",
                "https://example.test/ingest-limits",
                "--dry-run",
                "--lock-file",
                lock_path,
            ])

        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
