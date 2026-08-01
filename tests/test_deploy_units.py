from __future__ import annotations

import plistlib
import unittest
from pathlib import Path

from ai_usage_widget import deploy_units


ROOT = Path(__file__).resolve().parents[1]


def _sample_spec() -> "deploy_units.CollectorUnitSpec":
    return deploy_units.CollectorUnitSpec(
        source_id="linux-biai-wangzp",
        release_dir="/opt/ai-usage/current",
        config_path="/opt/ai-usage/config/device.json",
        env_file="/opt/ai-usage/secrets/ingest.env",
        lock_file="/opt/ai-usage/run/pusher.lock",
        python_executable="/usr/bin/python3",
        on_calendar="*:0/30",
        timeout_seconds=120,
    )


class RepositoryTemplateGenerationTests(unittest.TestCase):
    """Issue #57 第 4 条：模板由代码生成，仓库里的文件不能手工漂移。"""

    def test_every_committed_deploy_template_equals_generated_output(self) -> None:
        rendered = deploy_units.render_repository_templates()

        self.assertIn("deploy/systemd-user/ai-usage-pusher.timer", rendered)
        self.assertIn("deploy/systemd/ai-usage-pusher-calendar.conf", rendered)
        for relative_path, content in rendered.items():
            with self.subTest(path=relative_path):
                committed = (ROOT / relative_path).read_text(encoding="utf-8")
                self.assertEqual(
                    committed,
                    content,
                    f"{relative_path} 与代码生成结果不一致，"
                    f"请运行 python3 -m ai_usage_widget.deploy_units --write 重新生成",
                )

    def test_rendering_is_deterministic(self) -> None:
        first = deploy_units.render_repository_templates()
        second = deploy_units.render_repository_templates()

        self.assertEqual(first, second)


class SystemdTimerTemplateTests(unittest.TestCase):
    def test_timer_supports_persistent_catch_up(self) -> None:
        timer = deploy_units.render_timer_unit(_sample_spec())

        self.assertIn("Persistent=true", timer)
        self.assertIn("OnCalendar=*:0/30", timer)
        self.assertIn("[Install]\nWantedBy=timers.target\n", timer)

    def test_persistent_can_be_switched_off_without_editing_the_file_by_hand(self) -> None:
        spec = deploy_units.CollectorUnitSpec(
            **{**_sample_spec().__dict__, "persistent": False}
        )

        timer = deploy_units.render_timer_unit(spec)

        self.assertNotIn("Persistent=", timer)
        self.assertIn("OnCalendar=*:0/30", timer)

    def test_timer_never_emits_a_monotonic_trigger_or_unit_override(self) -> None:
        timer = deploy_units.render_timer_unit(_sample_spec())

        self.assertNotIn("OnUnitActiveSec", timer)
        self.assertNotRegex(timer, r"(?m)^Unit=")

    def test_calendar_drop_in_clears_inherited_monotonic_trigger_first(self) -> None:
        drop_in = deploy_units.render_calendar_drop_in(_sample_spec())

        self.assertLess(drop_in.index("OnUnitActiveSec=\n"), drop_in.index("OnCalendar=*:0/30"))
        self.assertIn("Persistent=true", drop_in)
        self.assertNotRegex(drop_in, r"(?m)^Unit=")


class SystemdServiceTemplateTests(unittest.TestCase):
    def test_service_pins_release_dir_pythonpath_and_python_executable(self) -> None:
        spec = _sample_spec()

        service = deploy_units.render_service_unit(spec)

        self.assertIn("WorkingDirectory=/opt/ai-usage/current\n", service)
        self.assertIn("Environment=PYTHONPATH=/opt/ai-usage/current/src\n", service)
        self.assertIn("EnvironmentFile=/opt/ai-usage/secrets/ingest.env\n", service)
        self.assertIn(
            "ExecStart=/usr/bin/python3 -m ai_usage_widget.cli push "
            "--config /opt/ai-usage/config/device.json "
            "--lock-file /opt/ai-usage/run/pusher.lock\n",
            service,
        )
        self.assertIn("Type=oneshot\n", service)

    def test_unit_names_derive_from_source_id_and_pair_by_basename(self) -> None:
        spec = _sample_spec()

        self.assertEqual(spec.timer_name, "ai-usage-pusher-linux-biai-wangzp.timer")
        self.assertEqual(spec.service_name, "ai-usage-pusher-linux-biai-wangzp.service")
        self.assertEqual(
            spec.timer_name.removesuffix(".timer"),
            spec.service_name.removesuffix(".service"),
        )


class LaunchdTemplateTests(unittest.TestCase):
    def test_launchd_plist_mirrors_the_systemd_calendar_and_catch_up(self) -> None:
        payload = plistlib.loads(deploy_units.render_launchd_plist(_sample_spec()))

        self.assertEqual(payload["Label"], "com.chunbai.aiusage.pusher.linux-biai-wangzp")
        self.assertEqual(payload["StartCalendarInterval"], [{"Minute": 0}, {"Minute": 30}])
        self.assertTrue(payload["RunAtLoad"])
        self.assertEqual(payload["WorkingDirectory"], "/opt/ai-usage/current")
        self.assertEqual(
            payload["EnvironmentVariables"]["PYTHONPATH"], "/opt/ai-usage/current/src"
        )
        self.assertEqual(
            payload["ProgramArguments"],
            [
                "/usr/bin/python3",
                "-m",
                "ai_usage_widget.cli",
                "push",
                "--config",
                "/opt/ai-usage/config/device.json",
                "--lock-file",
                "/opt/ai-usage/run/pusher.lock",
            ],
        )

    def test_launchd_plist_never_embeds_a_token_value(self) -> None:
        payload = plistlib.loads(deploy_units.render_launchd_plist(_sample_spec()))

        serialized = str(payload)
        self.assertNotIn("Bearer", serialized)
        self.assertEqual(
            sorted(payload["EnvironmentVariables"]),
            ["AI_USAGE_ENV_FILE", "PYTHONPATH"],
        )


if __name__ == "__main__":
    unittest.main()
