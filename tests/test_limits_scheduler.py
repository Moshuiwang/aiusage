from __future__ import annotations

import os
import plistlib
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_usage_widget.limits_scheduler import LimitsSchedulerConfig, install_limits_scheduler


def _prepare_source(repo: Path) -> None:
    shutil.copytree(
        Path(__file__).resolve().parents[1] / "src" / "ai_usage_widget",
        repo / "src" / "ai_usage_widget",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (repo / "config").mkdir()
    (repo / "config/limits.local.json").write_text('{"providers": []}', encoding="utf-8")


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
            _prepare_source(repo_dir)
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
            _prepare_source(repo_dir)
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
                runtime = config.token_env_file.parent / "runtime"
                self.assertTrue((runtime / "src/ai_usage_widget/cli.py").is_file())
                self.assertTrue((runtime / "src/ai_usage_widget/__init__.py").is_file())
                self.assertEqual(
                    (runtime / "limits.local.json").read_bytes(), config.limits_config.read_bytes()
                )
                self.assertTrue(config.token_env_file.is_file())
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


class TestLimitsSchedulerPreflight(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.repo = base / "repo"
        _prepare_source(self.repo)
        self.config = LimitsSchedulerConfig(
            repo_dir=self.repo,
            limits_config=self.repo / "config/limits.local.json",
            url="https://aiusage.example.invalid/ingest-limits",
            token_env_file=base / "state/limits-push.env",
            runner_path=base / "bin/limits-push",
            plist_path=base / "LaunchAgents/limits-push.plist",
            log_dir=base / "logs",
            lock_file=base / "state/limits-push.lock",
        )
        # 已部署内容必须保留，不能先覆盖再报缺源文件。
        self.config.token_env_file.parent.mkdir()
        self.config.token_env_file.write_text("original-env", encoding="utf-8")
        self.config.runner_path.parent.mkdir()
        self.config.runner_path.write_text("original-runner", encoding="utf-8")

    def _assert_rejected_without_writes_or_activation(self, expected: str) -> None:
        before_env = self.config.token_env_file.read_bytes()
        before_runner = self.config.runner_path.read_bytes()
        with patch("ai_usage_widget.limits_scheduler.ensure_agent_loaded") as activate:
            with self.assertRaisesRegex(ValueError, expected):
                install_limits_scheduler(
                    self.config, env={"AI_USAGE_INGEST_TOKEN": "fixture-token"}, activate=True
                )
        activate.assert_not_called()
        self.assertEqual(self.config.token_env_file.read_bytes(), before_env)
        self.assertEqual(self.config.runner_path.read_bytes(), before_runner)
        self.assertFalse(self.config.plist_path.exists())

    def test_missing_limits_config_blocks_install_before_any_write_or_activation(self) -> None:
        self.config.limits_config.unlink()
        self._assert_rejected_without_writes_or_activation("limits_config")

    def test_directory_cannot_substitute_for_limits_config(self) -> None:
        self.config.limits_config.unlink()
        self.config.limits_config.mkdir()
        self._assert_rejected_without_writes_or_activation("limits_config")

    def test_missing_source_package_blocks_install(self) -> None:
        shutil.rmtree(self.repo / "src" / "ai_usage_widget")
        self._assert_rejected_without_writes_or_activation("source")

    def test_source_package_without_cli_entrypoint_blocks_install(self) -> None:
        (self.repo / "src" / "ai_usage_widget" / "cli.py").unlink()
        self._assert_rejected_without_writes_or_activation("source")

    def test_source_package_without_init_blocks_install(self) -> None:
        (self.repo / "src" / "ai_usage_widget" / "__init__.py").unlink()
        self._assert_rejected_without_writes_or_activation("source")


if __name__ == "__main__":
    unittest.main()
