from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from ai_usage_widget import deploy_release, deploy_units


class ReleaseRollbackDrillTests(unittest.TestCase):
    """Issue #57 第 5 条：任一步失败可恢复到上一个 release 与 timer，且不改用户配置。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)

        self.root = base / "deploy-root"
        self.unit_dir = base / "systemd-user"
        self.source_dir = base / "repo" / "src"
        (self.source_dir / "ai_usage_widget").mkdir(parents=True)
        (self.source_dir / "ai_usage_widget" / "__init__.py").write_text("", encoding="utf-8")

        self.device_config = {
            "schema_version": 1,
            "source_id": "linux-biai-wangzp",
            "host": "aiusage.example.invalid",
            "machine": "biai-collector-01",
            "os_user": "wangzp",
            "platform": "linux",
            "timezone": "Asia/Shanghai",
            "server_url": "https://aiusage.example.invalid/ingest",
            "token_env": "AI_USAGE_INGEST_TOKEN",
        }
        self.commands: list[list[str]] = []
        self.failing_verbs: set[str] = set()

    def _runner(self, argv):
        self.commands.append(list(argv))
        if self.failing_verbs and set(argv) & self.failing_verbs:
            return 1
        return 0

    def _spec(self, on_calendar: str = "*:0/30") -> "deploy_units.CollectorUnitSpec":
        return deploy_units.CollectorUnitSpec(
            source_id="linux-biai-wangzp",
            release_dir=str(self.root / "current"),
            config_path=str(self.root / "config" / "device.json"),
            env_file=str(self.root / "secrets" / "ingest.env"),
            lock_file=str(self.root / "run" / "pusher.lock"),
            on_calendar=on_calendar,
        )

    def _install(self, version: str, revision: str, on_calendar: str = "*:0/30"):
        plan = deploy_release.ReleasePlan(
            root=self.root,
            unit_dir=self.unit_dir,
            source_dir=self.source_dir,
            version=version,
            revision=revision,
            installed_at=f"2026-08-01T00:00:00+00:00",
            unit_spec=self._spec(on_calendar),
            device_config=self.device_config,
        )
        return deploy_release.install_release(plan, command_runner=self._runner)

    def _config_path(self) -> Path:
        return self.root / "config" / "device.json"

    def _config_fingerprint(self) -> tuple:
        path = self._config_path()
        return (path.read_bytes(), path.lstat().st_mtime_ns)

    def _effective_state(self) -> dict:
        """回滚要恢复的东西：当前生效版本 + 生效的单元文件内容。"""
        state = {"current": os.readlink(self.root / "current")}
        for path in sorted(self.unit_dir.iterdir()):
            state[path.name] = path.read_text(encoding="utf-8")
        return state

    # --- 失败自动回滚 ------------------------------------------------------ #

    def test_failed_activation_rolls_back_to_the_previous_release_and_timer(self) -> None:
        self._install("2026.08.01-1", "06fa591")
        healthy_state = self._effective_state()
        self.failing_verbs = {"enable"}

        result = self._install("2026.08.02-1", "abc1234", on_calendar="*:0/15")

        self.assertFalse(result["success"])
        self.assertTrue(result["rolled_back"])
        self.assertEqual(result["rollback"]["rolled_back_to"], "2026.08.01-1")
        self.assertEqual(self._effective_state(), healthy_state)
        self.assertIn("OnCalendar=*:0/30", (self.unit_dir / self._spec().timer_name).read_text(encoding="utf-8"))

    def test_failed_activation_leaves_the_user_config_untouched(self) -> None:
        self._install("2026.08.01-1", "06fa591")
        edited = json.loads(self._config_path().read_text(encoding="utf-8"))
        edited["operator_note"] = "用户手改过"
        self._config_path().write_text(json.dumps(edited, ensure_ascii=False), encoding="utf-8")
        before = self._config_fingerprint()
        self.failing_verbs = {"enable"}

        self._install("2026.08.02-1", "abc1234", on_calendar="*:0/15")

        self.assertEqual(self._config_fingerprint(), before)

    def test_failed_first_install_without_previous_release_reports_no_rollback(self) -> None:
        self.failing_verbs = {"enable"}

        result = self._install("2026.08.01-1", "06fa591")

        self.assertFalse(result["success"])
        self.assertFalse(result["rolled_back"])
        self.assertEqual(result["error_type"], "ReleaseError")

    # --- 显式回滚 ---------------------------------------------------------- #

    def test_explicit_rollback_restores_the_previous_release_and_timer(self) -> None:
        self._install("2026.08.01-1", "06fa591")
        healthy_state = self._effective_state()
        self._install("2026.08.02-1", "abc1234", on_calendar="*:0/15")
        self.assertNotEqual(self._effective_state(), healthy_state)

        result = deploy_release.rollback_release(
            self.root, self.unit_dir, command_runner=self._runner
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["rolled_back_to"], "2026.08.01-1")
        self.assertEqual(self._effective_state(), healthy_state)
        # 两个 release 都留着，可以再滚回去。
        self.assertEqual(
            sorted(path.name for path in (self.root / "releases").iterdir()),
            ["2026.08.01-1", "2026.08.02-1"],
        )
        self.assertEqual(os.readlink(self.root / "previous"), "releases/2026.08.02-1")

    def test_explicit_rollback_does_not_touch_the_user_config(self) -> None:
        self._install("2026.08.01-1", "06fa591")
        self._install("2026.08.02-1", "abc1234", on_calendar="*:0/15")
        before = self._config_fingerprint()

        deploy_release.rollback_release(self.root, self.unit_dir, command_runner=self._runner)

        self.assertEqual(self._config_fingerprint(), before)

    def test_rollback_reloads_and_restarts_the_restored_timer(self) -> None:
        self._install("2026.08.01-1", "06fa591")
        self._install("2026.08.02-1", "abc1234", on_calendar="*:0/15")
        self.commands.clear()

        deploy_release.rollback_release(self.root, self.unit_dir, command_runner=self._runner)

        self.assertIn(["systemctl", "--user", "daemon-reload"], self.commands)
        self.assertIn(
            ["systemctl", "--user", "restart", "ai-usage-pusher-linux-biai-wangzp.timer"],
            self.commands,
        )

    def test_rollback_uses_the_timer_scope_recorded_by_the_release(self) -> None:
        plan_kwargs = dict(
            root=self.root,
            unit_dir=self.unit_dir,
            source_dir=self.source_dir,
            installed_at="2026-08-01T00:00:00+00:00",
            device_config=self.device_config,
            timer_scope="system",
        )
        deploy_release.install_release(
            deploy_release.ReleasePlan(
                version="2026.08.01-1", revision="06fa591", unit_spec=self._spec(), **plan_kwargs
            ),
            command_runner=self._runner,
        )
        deploy_release.install_release(
            deploy_release.ReleasePlan(
                version="2026.08.02-1",
                revision="abc1234",
                unit_spec=self._spec("*:0/15"),
                **plan_kwargs,
            ),
            command_runner=self._runner,
        )
        self.commands.clear()

        deploy_release.rollback_release(self.root, self.unit_dir, command_runner=self._runner)

        self.assertIn(["systemctl", "--system", "daemon-reload"], self.commands)
        self.assertIn(
            ["systemctl", "--system", "restart", "ai-usage-pusher-linux-biai-wangzp.timer"],
            self.commands,
        )
        self.assertNotIn(["systemctl", "--user", "daemon-reload"], self.commands)

    def test_install_activation_also_honours_the_timer_scope(self) -> None:
        deploy_release.install_release(
            deploy_release.ReleasePlan(
                root=self.root,
                unit_dir=self.unit_dir,
                source_dir=self.source_dir,
                version="2026.08.01-1",
                revision="06fa591",
                installed_at="2026-08-01T00:00:00+00:00",
                unit_spec=self._spec(),
                device_config=self.device_config,
                timer_scope="system",
            ),
            command_runner=self._runner,
        )

        self.assertIn(["systemctl", "--system", "daemon-reload"], self.commands)
        self.assertIn(
            ["systemctl", "--system", "enable", "--now", "ai-usage-pusher-linux-biai-wangzp.timer"],
            self.commands,
        )

    def test_rolled_back_is_not_claimed_when_the_rollback_commands_fail(self) -> None:
        self._install("2026.08.01-1", "06fa591")
        healthy_state = self._effective_state()
        # 激活和回滚的 systemctl 都失败：文件回到了旧版，但 systemd 没重新加载。
        self.failing_verbs = {"enable", "restart", "daemon-reload"}

        result = self._install("2026.08.02-1", "abc1234", on_calendar="*:0/15")

        self.assertFalse(result["success"])
        self.assertFalse(result["rolled_back"])
        self.assertTrue(result["rollback_files_restored"])
        self.assertEqual(self._effective_state(), healthy_state)

    def test_rollback_without_a_previous_release_is_refused(self) -> None:
        self._install("2026.08.01-1", "06fa591")

        with self.assertRaises(deploy_release.ReleaseError):
            deploy_release.rollback_release(
                self.root, self.unit_dir, command_runner=self._runner
            )

    def test_rollback_is_refused_when_the_previous_release_has_no_manifest(self) -> None:
        self._install("2026.08.01-1", "06fa591")
        self._install("2026.08.02-1", "abc1234", on_calendar="*:0/15")
        (self.root / "releases" / "2026.08.01-1" / "release.json").unlink()

        with self.assertRaises(deploy_release.ReleaseError):
            deploy_release.rollback_release(
                self.root, self.unit_dir, command_runner=self._runner
            )


if __name__ == "__main__":
    unittest.main()
