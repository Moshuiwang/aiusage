from __future__ import annotations

import os
import plistlib
import stat
import tempfile
import unittest
from pathlib import Path

from ai_usage_widget.limits_scheduler import LimitsSchedulerConfig, install_limits_scheduler


class TestLimitsScheduler(unittest.TestCase):
    def test_dry_run_returns_plan_without_writing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            config = LimitsSchedulerConfig(
                repo_dir=base / "repo",
                limits_config=base / "repo/config/limits.local.json",
                url="https://aiusage.chunbai.com/ingest-limits",
                token_env_file=base / "state/limits-push.env",
                runner_path=base / "bin/limits-push",
                plist_path=base / "LaunchAgents/com.chunbai.aiusage.limits-push.plist",
                log_dir=base / "logs",
                lock_file=base / "state/limits-push.lock",
            )

            result = install_limits_scheduler(config, env={"AI_USAGE_INGEST_TOKEN": "secret-token"}, dry_run=True)

            self.assertTrue(result["success"])
            self.assertTrue(result["dry_run"])
            self.assertFalse(config.runner_path.exists())
            self.assertFalse(config.plist_path.exists())
            self.assertFalse(config.token_env_file.exists())
            self.assertNotIn("secret-token", str(result))

    def test_install_writes_runner_plist_logs_and_0600_env_file_without_token_in_plist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            repo_dir = base / "repo"
            repo_dir.mkdir()
            config = LimitsSchedulerConfig(
                repo_dir=repo_dir,
                limits_config=repo_dir / "config/limits.local.json",
                url="https://aiusage.chunbai.com/ingest-limits",
                token_env_file=base / "state/limits-push.env",
                runner_path=base / "bin/limits-push",
                plist_path=base / "LaunchAgents/com.chunbai.aiusage.limits-push.plist",
                log_dir=base / "logs",
                lock_file=base / "state/limits-push.lock",
                interval_seconds=1800,
                python_executable="/usr/bin/python3",
            )

            result = install_limits_scheduler(config, env={"AI_USAGE_INGEST_TOKEN": "secret-token"}, dry_run=False)

            self.assertTrue(result["success"])
            self.assertFalse(result["dry_run"])
            self.assertTrue(config.runner_path.exists())
            self.assertTrue(config.plist_path.exists())
            self.assertTrue(config.log_dir.exists())
            self.assertEqual(stat.S_IMODE(config.token_env_file.stat().st_mode), 0o600)
            self.assertIn("AI_USAGE_INGEST_TOKEN=", config.token_env_file.read_text(encoding="utf-8"))

            plist_text = config.plist_path.read_text(encoding="utf-8")
            runner_text = config.runner_path.read_text(encoding="utf-8")
            self.assertNotIn("secret-token", plist_text)
            self.assertNotIn("secret-token", runner_text)
            self.assertIn(str(config.token_env_file), runner_text)
            self.assertIn("push-limits", runner_text)
            self.assertIn("--lock-file", runner_text)
            self.assertIn(str(config.lock_file), runner_text)

            with config.plist_path.open("rb") as handle:
                plist = plistlib.load(handle)
            self.assertEqual(plist["Label"], "com.chunbai.aiusage.limits-push")
            self.assertEqual(plist["StartInterval"], 1800)
            self.assertEqual(plist["ProgramArguments"], ["/bin/zsh", str(config.runner_path)])
            self.assertEqual(plist["StandardOutPath"], str(config.log_dir / "limits-push.stdout.log"))
            self.assertEqual(plist["StandardErrorPath"], str(config.log_dir / "limits-push.stderr.log"))

    def test_install_can_activate_and_verify_the_launch_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            repo_dir = base / "repo"
            repo_dir.mkdir()
            config = LimitsSchedulerConfig(
                repo_dir=repo_dir,
                limits_config=repo_dir / "config/limits.local.json",
                url="https://aiusage.chunbai.com/ingest-limits",
                token_env_file=base / "state/limits-push.env",
                runner_path=base / "bin/limits-push",
                plist_path=base / "LaunchAgents/com.chunbai.aiusage.limits-push.plist",
                log_dir=base / "logs",
                lock_file=base / "state/limits-push.lock",
            )
            calls: list[list[str]] = []
            responses = iter([1, 0, 0, 0])

            def runner(argv):
                calls.append(list(argv))
                return next(responses)

            result = install_limits_scheduler(
                config,
                env={"AI_USAGE_INGEST_TOKEN": "secret-token"},
                activate=True,
                command_runner=runner,
            )

            self.assertTrue(result["success"])
            self.assertTrue(result["activation"]["performed"])
            self.assertTrue(result["activation"]["verified"])
            self.assertEqual(calls[1][0:2], ["launchctl", "bootstrap"])
            self.assertEqual(calls[2][0:2], ["launchctl", "kickstart"])


if __name__ == "__main__":
    unittest.main()
