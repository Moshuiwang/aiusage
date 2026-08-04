from __future__ import annotations

import plistlib
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
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


_TASK_NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


class WindowsTaskTemplateTests(unittest.TestCase):
    """#124：Windows Task Scheduler 是第三个 OS 的定时单元，同样只许代码生成。"""

    def _xml(self, spec: "deploy_units.CollectorUnitSpec | None" = None) -> str:
        self.assertTrue(
            hasattr(deploy_units, "render_windows_task_xml"),
            "Windows Task Scheduler 渲染器缺失（render_windows_task_xml）",
        )
        return deploy_units.render_windows_task_xml(spec or _sample_spec())

    def test_windows_task_mirrors_calendar_command_and_workdir(self) -> None:
        root = ET.fromstring(self._xml())

        interval = root.findtext(
            "t:Triggers/t:CalendarTrigger/t:Repetition/t:Interval", namespaces=_TASK_NS
        )
        self.assertEqual(interval, "PT30M")
        start_boundary = root.findtext(
            "t:Triggers/t:CalendarTrigger/t:StartBoundary", namespaces=_TASK_NS
        )
        self.assertTrue(
            str(start_boundary).endswith("T00:00:00"),
            f"StartBoundary 应从 on_calendar 的起始分钟推导，实际 {start_boundary}",
        )
        self.assertEqual(
            root.findtext("t:Actions/t:Exec/t:WorkingDirectory", namespaces=_TASK_NS),
            "/opt/ai-usage/current",
        )
        self.assertEqual(
            root.findtext("t:Actions/t:Exec/t:Command", namespaces=_TASK_NS), "cmd.exe"
        )
        arguments = str(root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=_TASK_NS))
        self.assertIn(
            "/usr/bin/python3 -m ai_usage_widget.cli push "
            "--config /opt/ai-usage/config/device.json "
            "--lock-file /opt/ai-usage/run/pusher.lock",
            arguments,
        )
        self.assertIn("PYTHONPATH=/opt/ai-usage/current/src", arguments)
        self.assertIn("AI_USAGE_ENV_FILE=/opt/ai-usage/secrets/ingest.env", arguments)

    def test_windows_task_supports_catch_up_and_timeout(self) -> None:
        root = ET.fromstring(self._xml())

        self.assertEqual(
            root.findtext("t:Settings/t:StartWhenAvailable", namespaces=_TASK_NS), "true"
        )
        self.assertEqual(
            root.findtext("t:Settings/t:ExecutionTimeLimit", namespaces=_TASK_NS), "PT120S"
        )

    def test_windows_persistent_off_disables_catch_up(self) -> None:
        spec = deploy_units.CollectorUnitSpec(
            **{**_sample_spec().__dict__, "persistent": False}
        )

        root = ET.fromstring(self._xml(spec))

        self.assertEqual(
            root.findtext("t:Settings/t:StartWhenAvailable", namespaces=_TASK_NS), "false"
        )

    def test_windows_task_name_derives_from_source_id(self) -> None:
        spec = _sample_spec()

        self.assertTrue(
            hasattr(spec, "windows_task_name"),
            "CollectorUnitSpec 缺少 windows_task_name（Windows 任务名派生）",
        )
        self.assertEqual(spec.windows_task_name, "ai-usage-pusher-linux-biai-wangzp")

    def test_windows_task_never_embeds_a_token_value(self) -> None:
        root = ET.fromstring(self._xml())
        arguments = str(root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=_TASK_NS))

        # 闭世界断言（对齐 launchd 的 EnvironmentVariables 全集比对）：
        # 注入的环境变量恰好这两个，多一个 set（比如有人塞 TOKEN=）就红。
        injected = re.findall(r'set "([A-Z_]+)=', arguments)
        self.assertEqual(sorted(injected), ["AI_USAGE_ENV_FILE", "PYTHONPATH"])
        self.assertIn('set "AI_USAGE_ENV_FILE=/opt/ai-usage/secrets/ingest.env"', arguments)
        self.assertNotIn("Bearer", arguments)

    def test_windows_command_quotes_paths_with_spaces(self) -> None:
        spec = deploy_units.CollectorUnitSpec(
            **{
                **_sample_spec().__dict__,
                "python_executable": r"C:\Program Files\Python\python.exe",
            }
        )

        root = ET.fromstring(self._xml(spec))
        arguments = str(root.findtext("t:Actions/t:Exec/t:Arguments", namespaces=_TASK_NS))

        self.assertIn(r'"C:\Program Files\Python\python.exe" -m ai_usage_widget.cli push', arguments)

    def test_windows_write_helper_encodes_utf16_as_declared(self) -> None:
        self.assertTrue(
            hasattr(deploy_units, "write_windows_task_xml"),
            "缺少 UTF-16 写盘入口（write_windows_task_xml）",
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "task.xml"

            deploy_units.write_windows_task_xml(_sample_spec(), target)

            raw = target.read_bytes()
            self.assertIn(raw[:2], (b"\xff\xfe", b"\xfe\xff"), "UTF-16 BOM 缺失，与 XML 声明不一致")
            root = ET.fromstring(raw.decode("utf-16"))
            self.assertTrue(root.tag.endswith("Task"))


if __name__ == "__main__":
    unittest.main()
