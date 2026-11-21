from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from ai_usage_widget.limits_doctor import run_limits_doctor


class TestLimitsDoctor(unittest.TestCase):
    def test_antigravity_reports_local_readiness_without_credentials_or_rpc(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as config:
            json.dump({
                "timezone": "Asia/Shanghai",
                "providers": [{"provider": "antigravity", "source_id": "local"}],
            }, config)
            config.flush()
            with patch("subprocess.check_output", side_effect=[
                "42 /Applications/Antigravity.app/language_server_mac --csrf_token sample-secret",
                "p42\nn127.0.0.1:59999\n",
            ]), patch("urllib.request.OpenerDirector.open") as open_rpc:
                report = run_limits_doctor(config.name)

        self.assertTrue(report["success"])
        self.assertEqual(report["providers"][0]["source_id"], "local")
        self.assertEqual(report["providers"][0]["checks"][0]["name"], "antigravity.language_server")
        self.assertNotIn("sample-secret", json.dumps(report))
        open_rpc.assert_not_called()

    def test_antigravity_reports_not_running_without_claiming_readiness(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as config:
            json.dump({"timezone": "Asia/Shanghai", "providers": [{"provider": "antigravity"}]}, config)
            config.flush()
            with patch("subprocess.check_output", return_value=""):
                report = run_limits_doctor(config.name)

        self.assertFalse(report["success"])
        self.assertEqual(report["providers"][0]["checks"][0]["status"], "not_running")

    def test_missing_config_path_returns_json_failure(self) -> None:
        report = run_limits_doctor(None, command_resolver=lambda _: None)

        self.assertFalse(report["success"])
        self.assertTrue(report["doctor"])
        self.assertEqual(report["checks"][0]["name"], "limits_config")
        self.assertEqual(report["checks"][0]["status"], "missing")

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
