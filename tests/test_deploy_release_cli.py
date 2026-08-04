from __future__ import annotations

import io
import json
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from ai_usage_widget import cli, deploy_release


class CollectorInstallCliTests(unittest.TestCase):
    """Issue #57 顶层验收第 1 条：安装和回滚必须通过命令可达，不要求手改 timer。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)

        self.root = base / "deploy-root"
        self.unit_dir = base / "systemd-user"
        self.source_dir = base / "repo" / "src"
        (self.source_dir / "ai_usage_widget").mkdir(parents=True)
        (self.source_dir / "ai_usage_widget" / "__init__.py").write_text("", encoding="utf-8")

        self.seed_config = base / "device.seed.json"
        self.seed_config.write_text(
            json.dumps(
                {
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
            ),
            encoding="utf-8",
        )
        self.commands: list[list[str]] = []

    def _runner(self, argv):
        self.commands.append(list(argv))
        return 0

    def _seed_env_file(self) -> None:
        """摆好 ingest token 的 env 文件。

        #144 起它是激活 timer 的前置条件，但**不能放进 setUp**：dry-run 用例要断言
        「一个文件都不碰」，预建 root 会把那条断言废掉。所以按用例显式调用。
        """
        (self.root / "secrets").mkdir(parents=True, exist_ok=True)
        (self.root / "secrets" / "ingest.env").write_text("# managed by ops\n", encoding="utf-8")

    def _install_argv(self, version: str = "2026.08.01-1", revision: str = "06fa591") -> list[str]:
        return [
            "install-collector",
            "--root", str(self.root),
            "--unit-dir", str(self.unit_dir),
            "--source-dir", str(self.source_dir),
            "--version", version,
            "--revision", revision,
            "--source-id", "linux-biai-wangzp",
            "--device-config", str(self.seed_config),
        ]

    def _run(self, argv: list[str]) -> tuple[int, dict]:
        buffer = io.StringIO()
        with mock.patch.object(deploy_release, "default_command_runner", self._runner):
            with redirect_stdout(buffer):
                code = cli.main(argv)
        return code, json.loads(buffer.getvalue())

    def test_install_collector_installs_a_versioned_release_and_enables_the_timer(self) -> None:
        self._seed_env_file()
        code, payload = self._run(self._install_argv())

        self.assertEqual(code, 0)
        self.assertTrue(payload["success"])
        self.assertTrue((self.root / "releases" / "2026.08.01-1" / "release.json").exists())
        self.assertTrue((self.root / "current").is_symlink())
        self.assertEqual(
            sorted(path.name for path in self.unit_dir.iterdir()),
            [
                "ai-usage-pusher-linux-biai-wangzp.service",
                "ai-usage-pusher-linux-biai-wangzp.timer",
            ],
        )
        self.assertIn(
            ["systemctl", "--user", "enable", "--now", "ai-usage-pusher-linux-biai-wangzp.timer"],
            self.commands,
        )

    def test_running_install_collector_twice_is_idempotent(self) -> None:
        self._seed_env_file()
        self._run(self._install_argv())
        _, second = self._run(self._install_argv())

        self.assertTrue(second["success"])
        self.assertFalse(second["changed"])
        self.assertEqual(
            sorted(path.name for path in self.unit_dir.glob("*.timer")),
            ["ai-usage-pusher-linux-biai-wangzp.timer"],
        )

    def test_dry_run_touches_nothing(self) -> None:
        code, payload = self._run(self._install_argv() + ["--dry-run"])

        self.assertEqual(code, 0)
        self.assertTrue(payload["dry_run"])
        self.assertFalse(self.root.exists())
        self.assertFalse(self.unit_dir.exists())
        self.assertEqual(self.commands, [])

    def test_install_collector_passes_the_timer_scope_through(self) -> None:
        self._seed_env_file()
        self._run(self._install_argv() + ["--timer-scope", "system"])

        self.assertIn(["systemctl", "--system", "daemon-reload"], self.commands)

    def test_rollback_collector_restores_the_previous_release(self) -> None:
        self._seed_env_file()
        self._run(self._install_argv())
        self._run(self._install_argv(version="2026.08.02-1", revision="abc1234"))

        code, payload = self._run(
            [
                "rollback-collector",
                "--root", str(self.root),
                "--unit-dir", str(self.unit_dir),
            ]
        )

        self.assertEqual(code, 0)
        self.assertEqual(payload["rolled_back_to"], "2026.08.01-1")
        self.assertEqual(os.readlink(self.root / "current"), "releases/2026.08.01-1")

    def test_rollback_collector_without_a_previous_release_fails_loudly(self) -> None:
        self._seed_env_file()
        self._run(self._install_argv())

        code, payload = self._run(
            [
                "rollback-collector",
                "--root", str(self.root),
                "--unit-dir", str(self.unit_dir),
            ]
        )

        self.assertEqual(code, 1)
        self.assertFalse(payload["success"])

    def test_install_collector_rejects_an_invalid_seed_device_config(self) -> None:
        self.seed_config.write_text(json.dumps({"source_id": "x"}), encoding="utf-8")

        code, payload = self._run(self._install_argv())

        self.assertEqual(code, 1)
        self.assertFalse(payload["success"])


class CredentialFilePermissionTests(unittest.TestCase):
    """P2：放 ingest token 的目录和用户配置不能用默认 umask。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.root = base / "deploy-root"
        self.unit_dir = base / "systemd-user"
        self.source_dir = base / "repo" / "src"
        (self.source_dir / "ai_usage_widget").mkdir(parents=True)
        (self.source_dir / "ai_usage_widget" / "__init__.py").write_text("", encoding="utf-8")

    def _install(self):
        from ai_usage_widget import deploy_units

        plan = deploy_release.ReleasePlan(
            root=self.root,
            unit_dir=self.unit_dir,
            source_dir=self.source_dir,
            version="2026.08.01-1",
            revision="06fa591",
            installed_at="2026-08-01T00:00:00+00:00",
            unit_spec=deploy_units.CollectorUnitSpec(
                source_id="linux-biai-wangzp",
                release_dir=str(self.root / "current"),
                config_path=str(self.root / "config" / "device.json"),
                env_file=str(self.root / "secrets" / "ingest.env"),
                lock_file=str(self.root / "run" / "pusher.lock"),
            ),
            device_config={
                "schema_version": 1,
                "source_id": "linux-biai-wangzp",
                "machine": "biai-collector-01",
                "os_user": "wangzp",
                "platform": "linux",
                "timezone": "Asia/Shanghai",
                "server_url": "https://aiusage.example.invalid/ingest",
                "token_env": "AI_USAGE_INGEST_TOKEN",
            },
        )
        return deploy_release.install_release(plan, command_runner=lambda argv: 0)

    def _mode(self, path: Path) -> int:
        return stat.S_IMODE(path.lstat().st_mode)

    def test_secrets_directory_is_owner_only(self) -> None:
        self._install()

        self.assertEqual(self._mode(self.root / "secrets"), 0o700)

    def test_device_config_is_not_world_readable(self) -> None:
        self._install()

        self.assertEqual(self._mode(self.root / "config" / "device.json"), 0o600)

    def test_reinstall_does_not_loosen_permissions(self) -> None:
        self._install()
        self._install()

        self.assertEqual(self._mode(self.root / "secrets"), 0o700)
        self.assertEqual(self._mode(self.root / "config" / "device.json"), 0o600)


if __name__ == "__main__":
    unittest.main()
