from __future__ import annotations

import json
import os
import tempfile
import unittest

from ai_usage_widget.limits_doctor import run_limits_doctor


class TestLimitsDoctor(unittest.TestCase):
    def test_missing_config_path_returns_json_failure(self) -> None:
        report = run_limits_doctor(None, command_resolver=lambda _: None)

        self.assertFalse(report["success"])
        self.assertTrue(report["doctor"])
        self.assertEqual(report["checks"][0]["name"], "limits_config")
        self.assertEqual(report["checks"][0]["status"], "missing")

    def test_missing_config_file_returns_missing_without_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_path = os.path.join(tmpdir, "limits.local.json")

            report = run_limits_doctor(missing_path, command_resolver=lambda _: None)

        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
        self.assertFalse(report["success"])
        self.assertEqual(report["checks"][0]["status"], "missing")
        self.assertNotIn(missing_path, serialized)

    def test_ready_config_redacts_paths_and_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex_auth = os.path.join(tmpdir, "codex-auth.json")
            claude_auth = os.path.join(tmpdir, "claude-auth.json")
            codex_sock = os.path.join(tmpdir, "codex.sock")
            config_path = os.path.join(tmpdir, "limits.local.json")
            for path in [codex_auth, claude_auth, codex_sock]:
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("{}")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "timezone": "Asia/Shanghai",
                        "sqlite": os.path.join(tmpdir, "usage.sqlite"),
                        "latest": os.path.join(tmpdir, "latest.json"),
                        "providers": [
                            {
                                "provider": "codex",
                                "auth_file": codex_auth,
                                "rpc": True,
                                "rpc_sock": codex_sock,
                            },
                            {
                                "provider": "claude",
                                "auth_file": claude_auth,
                                "usage_url": "https://example.invalid/usage",
                                "cli": True,
                            },
                        ],
                    },
                    handle,
                )

            report = run_limits_doctor(
                config_path,
                command_resolver=lambda name: f"/usr/bin/{name}" if name in {"codex", "claude"} else None,
            )

        serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
        self.assertTrue(report["success"])
        self.assertEqual([item["provider"] for item in report["providers"]], ["codex", "claude"])
        self.assertTrue(all(item["ready"] for item in report["providers"]))
        self.assertNotIn(tmpdir, serialized)
        self.assertNotIn("example.invalid", serialized)
        self.assertNotIn("codex.sock", serialized)

    def test_claude_cli_can_make_missing_oauth_path_non_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "limits.local.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "timezone": "Asia/Shanghai",
                        "providers": [
                            {
                                "provider": "claude",
                                "auth_file": os.path.join(tmpdir, "missing-auth.json"),
                                "usage_url": "https://example.invalid/usage",
                                "cli": True,
                            }
                        ],
                    },
                    handle,
                )

            report = run_limits_doctor(config_path, command_resolver=lambda name: "/usr/bin/claude" if name == "claude" else None)

        self.assertTrue(report["success"])
        self.assertTrue(report["providers"][0]["ready"])
        checks = {check["name"]: check for check in report["providers"][0]["checks"]}
        self.assertEqual(checks["claude.auth_file"]["status"], "missing")
        self.assertEqual(checks["claude.cli_command"]["status"], "ok")

    def test_codex_rpc_without_command_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = os.path.join(tmpdir, "limits.local.json")
            with open(config_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "timezone": "Asia/Shanghai",
                        "providers": [
                            {
                                "provider": "codex",
                                "rpc": True,
                            }
                        ],
                    },
                    handle,
                )

            report = run_limits_doctor(config_path, command_resolver=lambda _: None)

        self.assertFalse(report["success"])
        self.assertFalse(report["providers"][0]["ready"])
        checks = {check["name"]: check for check in report["providers"][0]["checks"]}
        self.assertEqual(checks["codex.rpc_command"]["status"], "missing")


if __name__ == "__main__":
    unittest.main()
