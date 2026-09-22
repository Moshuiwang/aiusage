from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ai_usage_widget import deploy_release, deploy_units


class ReleaseInstallIdempotencyTests(unittest.TestCase):
    """Issue #57 第 3 条：安装/升级幂等，连续两次不产生重复 timer、重复来源或覆盖配置。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)

        self.root = base / "deploy-root"
        self.unit_dir = base / "systemd-user"
        self.source_dir = base / "repo" / "src"
        (self.source_dir / "ai_usage_widget").mkdir(parents=True)
        (self.source_dir / "ai_usage_widget" / "__init__.py").write_text("", encoding="utf-8")
        (self.source_dir / "ai_usage_widget" / "cli.py").write_text(
            "def main():\n    return 0\n", encoding="utf-8"
        )
        (self.source_dir / "ai_usage_widget" / "__pycache__").mkdir()
        (self.source_dir / "ai_usage_widget" / "__pycache__" / "cli.pyc").write_bytes(b"stale")

        # ingest token 的 env 文件由运维单独放置，不由 install 生成；#144 起它是
        # 激活前置条件（缺了就不许 enable timer），所以这里得先摆好。内容只是占位，
        # 真实 token 永远不进仓库。
        (self.root / "secrets").mkdir(parents=True)
        (self.root / "secrets" / "ingest.env").write_text("# managed by ops\n", encoding="utf-8")

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

    def _runner(self, argv):
        self.commands.append(list(argv))
        return 0

    def _plan(self, version: str = "2026.08.01-1", revision: str = "06fa591") -> "deploy_release.ReleasePlan":
        return deploy_release.ReleasePlan(
            root=self.root,
            unit_dir=self.unit_dir,
            source_dir=self.source_dir,
            version=version,
            revision=revision,
            installed_at="2026-08-01T00:00:00+00:00",
            unit_spec=deploy_units.CollectorUnitSpec(
                source_id="linux-biai-wangzp",
                release_dir=str(self.root / "current"),
                config_path=str(self.root / "config" / "device.json"),
                env_file=str(self.root / "secrets" / "ingest.env"),
                lock_file=str(self.root / "run" / "pusher.lock"),
            ),
            device_config=self.device_config,
        )

    def _install(self, **kwargs):
        return deploy_release.install_release(
            self._plan(**kwargs), command_runner=self._runner
        )

    def _state(self) -> dict:
        """本测试对「状态」的定义：两棵目录树里每个条目的类型、内容哈希和 mtime。"""
        state: dict[str, tuple] = {}
        for base in (self.root, self.unit_dir):
            for path in sorted(base.rglob("*")):
                key = str(path)
                if path.is_symlink():
                    state[key] = ("symlink", os.readlink(path))
                elif path.is_dir():
                    state[key] = ("dir",)
                else:
                    state[key] = (
                        "file",
                        hashlib.sha256(path.read_bytes()).hexdigest(),
                        path.lstat().st_mtime_ns,
                    )
        return state

    def _config_path(self) -> Path:
        return self.root / "config" / "device.json"

    def _timer_files(self) -> list[str]:
        return sorted(path.name for path in self.unit_dir.glob("*.timer"))

    def _enabled_units(self) -> list[str]:
        enabled = []
        for argv in self.commands:
            if "enable" in argv:
                enabled.extend(item for item in argv if item.endswith(".timer"))
        return enabled

    def test_first_install_creates_versioned_release_current_link_and_units(self) -> None:
        result = self._install()

        self.assertTrue(result["success"])
        self.assertTrue(result["changed"])
        release_dir = self.root / "releases" / "2026.08.01-1"
        manifest = json.loads((release_dir / "release.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["version"], "2026.08.01-1")
        self.assertEqual(manifest["revision"], "06fa591")
        self.assertTrue((release_dir / "src" / "ai_usage_widget" / "cli.py").exists())
        self.assertFalse((release_dir / "src" / "ai_usage_widget" / "__pycache__").exists())
        self.assertTrue((self.root / "current").is_symlink())
        self.assertEqual(
            (self.root / "current").resolve(), release_dir.resolve()
        )
        self.assertEqual(self._timer_files(), ["ai-usage-pusher-linux-biai-wangzp.timer"])
        self.assertTrue((self.unit_dir / "ai-usage-pusher-linux-biai-wangzp.service").exists())

    def test_missing_source_entrypoint_never_switches_or_activates_release(self) -> None:
        self._install()
        before = self._state()
        commands_before = list(self.commands)
        for name in ("cli.py", "__init__.py"):
            with self.subTest(name=name):
                entrypoint = self.source_dir / "ai_usage_widget" / name
                original = entrypoint.read_bytes()
                entrypoint.unlink()
                try:
                    with self.assertRaisesRegex(ValueError, "source entrypoint"):
                        self._install(version="2026.08.02-1", revision="new-revision")
                    self.assertEqual(self._state(), before)
                    self.assertEqual(self.commands, commands_before)
                finally:
                    entrypoint.write_bytes(original)

    def test_install_refuses_a_unit_that_points_outside_the_managed_current_link(self) -> None:
        plan = self._plan()
        plan = replace(plan, unit_spec=replace(plan.unit_spec, release_dir=str(self.root / "stale")))
        before = self._state()

        with self.assertRaisesRegex(ValueError, "release_dir.*current"):
            deploy_release.install_release(plan, command_runner=self._runner)

        self.assertEqual(self._state(), before)
        self.assertEqual(self.commands, [])

    def test_running_install_twice_leaves_identical_state(self) -> None:
        self._install()
        after_first = self._state()

        second = self._install()

        self.assertTrue(second["success"])
        self.assertFalse(second["changed"])
        self.assertEqual(self._state(), after_first)

    def test_second_install_does_not_create_or_enable_a_second_timer(self) -> None:
        self._install()
        self._install()

        self.assertEqual(self._timer_files(), ["ai-usage-pusher-linux-biai-wangzp.timer"])
        self.assertEqual(set(self._enabled_units()), {"ai-usage-pusher-linux-biai-wangzp.timer"})

    def test_install_never_overwrites_an_existing_device_config(self) -> None:
        self._install()
        edited = json.loads(self._config_path().read_text(encoding="utf-8"))
        edited["timezone"] = "Asia/Tokyo"
        edited["operator_note"] = "用户手改过"
        self._config_path().write_text(json.dumps(edited, ensure_ascii=False), encoding="utf-8")
        before = self._config_path().read_bytes()
        before_mtime = self._config_path().lstat().st_mtime_ns

        result = self._install(version="2026.08.02-1", revision="abc1234")

        self.assertTrue(result["success"])
        self.assertFalse(result["config_created"])
        self.assertEqual(self._config_path().read_bytes(), before)
        self.assertEqual(self._config_path().lstat().st_mtime_ns, before_mtime)

    def test_upgrade_keeps_one_source_and_records_the_previous_release(self) -> None:
        self._install()
        self._install(version="2026.08.02-1", revision="abc1234")

        self.assertEqual(
            sorted(path.name for path in (self.root / "releases").iterdir()),
            ["2026.08.01-1", "2026.08.02-1"],
        )
        self.assertEqual(
            (self.root / "current").resolve(),
            (self.root / "releases" / "2026.08.02-1").resolve(),
        )
        self.assertEqual(
            (self.root / "previous").resolve(),
            (self.root / "releases" / "2026.08.01-1").resolve(),
        )
        # 来源身份只有一个：配置没被改写，timer 也只有一个。
        config = json.loads(self._config_path().read_text(encoding="utf-8"))
        self.assertEqual(config["source_id"], "linux-biai-wangzp")
        self.assertEqual(self._timer_files(), ["ai-usage-pusher-linux-biai-wangzp.timer"])

    def test_upgrade_then_reinstall_same_version_is_still_idempotent(self) -> None:
        self._install()
        self._install(version="2026.08.02-1", revision="abc1234")
        after_upgrade = self._state()

        self._install(version="2026.08.02-1", revision="abc1234")

        self.assertEqual(self._state(), after_upgrade)

    def test_reusing_a_version_with_a_different_revision_is_refused(self) -> None:
        self._install()

        with self.assertRaises(ValueError) as context:
            self._install(version="2026.08.01-1", revision="deadbee")

        self.assertIn("2026.08.01-1", str(context.exception))

    def test_unit_files_are_exactly_the_generated_templates(self) -> None:
        self._install()
        spec = self._plan().unit_spec

        timer = (self.unit_dir / spec.timer_name).read_text(encoding="utf-8")
        service = (self.unit_dir / spec.service_name).read_text(encoding="utf-8")

        self.assertEqual(timer, deploy_units.render_timer_unit(spec))
        self.assertEqual(service, deploy_units.render_service_unit(spec))


class ActivationPreflightTests(unittest.TestCase):
    """#144 第 2 条：启用/重载定时器前必须先确认单元里写的路径都真实存在。

    线上事故形态：旧 service 的 WorkingDirectory 指向已被删掉的目录，systemd
    返回 200/CHDIR，采集从此停摆，直到人工巡检才发现。检查要发生在 systemctl
    之前——单元一旦被 enable，失败就只写进 journal，没人看。
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.release = self.base / "current"
        (self.release / "src").mkdir(parents=True)
        package = self.release / "src" / "ai_usage_widget"
        package.mkdir()
        for name in ("__init__.py", "cli.py"):
            (package / name).write_bytes(
                (Path(__file__).resolve().parents[1] / "src" / "ai_usage_widget" / name).read_bytes()
            )
        self.env_file = self.base / "secrets" / "ingest.env"
        self.env_file.parent.mkdir(parents=True)
        self.env_file.write_text("# managed by ops\n", encoding="utf-8")
        self.config_path = self.base / "config" / "device.json"
        self.config_path.parent.mkdir(parents=True)
        self.config_path.write_text("{}\n", encoding="utf-8")

    def _spec(self, **overrides) -> deploy_units.CollectorUnitSpec:
        fields = {
            "source_id": "tz-wangzp",
            "release_dir": str(self.release),
            "config_path": str(self.config_path),
            "env_file": str(self.env_file),
            "lock_file": str(self.base / "run" / "pusher.lock"),
        }
        fields.update(overrides)
        return deploy_units.CollectorUnitSpec(**fields)

    def _failed_names(self, checks) -> list[str]:
        return sorted(check["name"] for check in checks if not check["ok"])

    def test_all_paths_present_passes_with_every_declared_path_checked(self) -> None:
        checks = deploy_release.preflight_unit_paths(self._spec())

        # 结构下限：四个路径和两个源码入口都必须检查，空 src 目录不能冒充可运行程序。
        self.assertEqual(
            sorted(check["name"] for check in checks),
            ["device_config", "env_file", "pythonpath", "source_cli", "source_init", "working_directory"],
        )
        self.assertEqual(self._failed_names(checks), [])
        self.assertEqual(
            {check["name"]: check["path"] for check in checks}["working_directory"],
            str(self.release),
        )

    def test_missing_working_directory_is_reported(self) -> None:
        checks = deploy_release.preflight_unit_paths(
            self._spec(release_dir=str(self.base / "releases" / "已被删掉"))
        )

        self.assertIn("working_directory", self._failed_names(checks))
        self.assertIn("pythonpath", self._failed_names(checks))

    def test_runtime_without_python_entrypoint_is_rejected(self) -> None:
        (self.release / "src" / "ai_usage_widget" / "cli.py").unlink()
        checks = deploy_release.preflight_unit_paths(self._spec())
        self.assertEqual(self._failed_names(checks), ["source_cli"])

    def test_runtime_without_package_init_is_rejected(self) -> None:
        (self.release / "src" / "ai_usage_widget" / "__init__.py").unlink()
        checks = deploy_release.preflight_unit_paths(self._spec())
        self.assertEqual(self._failed_names(checks), ["source_init"])

    def test_missing_env_file_is_reported(self) -> None:
        self.env_file.unlink()

        checks = deploy_release.preflight_unit_paths(self._spec())

        self.assertEqual(self._failed_names(checks), ["env_file"])

    def test_missing_device_config_is_reported(self) -> None:
        self.config_path.unlink()

        checks = deploy_release.preflight_unit_paths(self._spec())

        self.assertEqual(self._failed_names(checks), ["device_config"])

    def test_preflight_does_not_report_a_directory_as_a_usable_file(self) -> None:
        """EnvironmentFile 指到一个目录上，systemd 同样起不来——存在 ≠ 可用。"""
        self.env_file.unlink()
        self.env_file.mkdir()

        checks = deploy_release.preflight_unit_paths(self._spec())

        self.assertEqual(self._failed_names(checks), ["env_file"])


class InstallPreflightGateTests(unittest.TestCase):
    """预检失败时，install 必须停在 systemctl 之前——一条命令都不许跑。"""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.root = base / "deploy-root"
        self.unit_dir = base / "systemd-user"
        self.source_dir = base / "repo" / "src"
        (self.source_dir / "ai_usage_widget").mkdir(parents=True)
        (self.source_dir / "ai_usage_widget" / "__init__.py").write_text("", encoding="utf-8")
        (self.source_dir / "ai_usage_widget" / "cli.py").write_bytes(
            (Path(__file__).resolve().parents[1] / "src" / "ai_usage_widget" / "cli.py").read_bytes()
        )
        self.commands: list[list[str]] = []

    def _runner(self, argv):
        self.commands.append(list(argv))
        return 0

    def _install(self):
        plan = deploy_release.ReleasePlan(
            root=self.root,
            unit_dir=self.unit_dir,
            source_dir=self.source_dir,
            version="2026.08.04-1",
            revision="06fa591",
            installed_at="2026-08-04T00:00:00+00:00",
            unit_spec=deploy_units.CollectorUnitSpec(
                source_id="tz-wangzp",
                release_dir=str(self.root / "current"),
                config_path=str(self.root / "config" / "device.json"),
                env_file=str(self.root / "secrets" / "ingest.env"),
                lock_file=str(self.root / "run" / "pusher.lock"),
            ),
            device_config={
                "schema_version": 1,
                "source_id": "tz-wangzp",
                "host": "aiusage.example.invalid",
                "machine": "biai-collector-01",
                "os_user": "wangzp",
                "platform": "linux",
                "timezone": "Asia/Shanghai",
                "server_url": "https://aiusage.example.invalid/ingest",
                "token_env": "AI_USAGE_INGEST_TOKEN",
            },
        )
        return deploy_release.install_release(plan, command_runner=self._runner)

    def test_install_without_env_file_never_reloads_or_enables_the_timer(self) -> None:
        result = self._install()

        self.assertFalse(result["success"])
        self.assertEqual(self.commands, [])
        self.assertFalse(result["rolled_back"])
        self.assertEqual(
            sorted(check["name"] for check in result["preflight"] if not check["ok"]),
            ["env_file"],
        )

    def test_install_proceeds_once_the_env_file_exists(self) -> None:
        """门禁不是把安装堵死：补齐缺失文件后重跑，幂等地完成激活。"""
        self._install()
        env_file = self.root / "secrets" / "ingest.env"
        env_file.write_text("# managed by ops\n", encoding="utf-8")

        result = self._install()

        self.assertTrue(result["success"])
        self.assertIn(
            ["systemctl", "--user", "enable", "--now", "ai-usage-pusher-tz-wangzp.timer"],
            self.commands,
        )


if __name__ == "__main__":
    unittest.main()
