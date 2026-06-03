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
    def test_collect_limits_fixture_writes_sqlite_and_snapshot(self) -> None:
        db_fd, db_path = tempfile.mkstemp(suffix=".sqlite")
        out_fd, out_path = tempfile.mkstemp(suffix=".json")
        os.close(db_fd)
        os.close(out_fd)
        try:
            code = cli.main([
                "collect-limits",
                "--provider-fixture",
                str(FIXTURES / "limits_runtime_fixture.json"),
                "--sqlite",
                db_path,
                "--latest",
                out_path,
                "--date",
                "2026-06-03",
            ])

            self.assertEqual(code, 0)
            with sqlite3.connect(db_path) as conn:
                rows = conn.execute("SELECT provider, window FROM limit_windows ORDER BY provider").fetchall()
            self.assertEqual(rows, [("claude", "week"), ("codex", "session")])

            with open(out_path, encoding="utf-8") as handle:
                snapshot = json.load(handle)
            self.assertEqual(len(snapshot["limits"]), 2)
        finally:
            for path in [db_path, out_path]:
                if os.path.exists(path):
                    os.remove(path)

    def test_collect_limits_dry_run_fixture_does_not_write_sqlite_or_snapshot(self) -> None:
        db_path = tempfile.mktemp(suffix=".sqlite")
        out_path = tempfile.mktemp(suffix=".json")

        code = cli.main([
            "collect-limits",
            "--provider-fixture",
            str(FIXTURES / "limits_runtime_fixture.json"),
            "--sqlite",
            db_path,
            "--latest",
            out_path,
            "--dry-run",
        ])

        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(db_path))
        self.assertFalse(os.path.exists(out_path))

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
        code = cli.main(["collect-limits", "--no-snapshot"])

        self.assertEqual(code, 1)

    def test_collect_limits_codex_requires_explicit_auth_file(self) -> None:
        code = cli.main(["collect-limits", "--provider", "codex", "--no-snapshot"])

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

        db_fd, db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(db_fd)
        try:
            with patch.object(cli, "CodexAppServerRPCProvider", FakeCodexRPCProvider):
                code = cli.main([
                    "collect-limits",
                    "--provider",
                    "codex",
                    "--codex-rpc",
                    "--sqlite",
                    db_path,
                    "--no-snapshot",
                ])
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

        self.assertEqual(code, 0)

    def test_collect_limits_claude_requires_explicit_auth_file_and_usage_url(self) -> None:
        code = cli.main(["collect-limits", "--provider", "claude", "--no-snapshot"])

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

        db_fd, db_path = tempfile.mkstemp(suffix=".sqlite")
        os.close(db_fd)
        try:
            with patch.object(cli, "ClaudeCliUsageProvider", FakeClaudeCliProvider):
                code = cli.main([
                    "collect-limits",
                    "--provider",
                    "claude",
                    "--claude-cli",
                    "--sqlite",
                    db_path,
                    "--no-snapshot",
                ])
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

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
                    "--no-snapshot",
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

    def test_collect_limits_check_config_requires_limits_config(self) -> None:
        code = cli.main(["collect-limits", "--check-config"])

        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
