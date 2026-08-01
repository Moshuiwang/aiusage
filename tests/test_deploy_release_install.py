from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
