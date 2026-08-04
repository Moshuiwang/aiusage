"""采集端定时任务单元模板的唯一生成入口（Issue #57）。

模板必须由代码生成，不允许在仓库里手工维护第二份：手工维护正是
「timer 模板漂移」和「已启用但不会再触发」这两个部署事故的来源。

`tests/test_deploy_units.py` 把仓库里已提交的模板与本模块的输出逐字节比对，
所以改模板只有一条路：改这里，然后

    python3 -m ai_usage_widget.deploy_units --write

重新生成 `deploy/` 下的文件。
"""

from __future__ import annotations

import argparse
import plistlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple
from xml.sax.saxutils import escape as _xml_escape


UNIT_PREFIX = "ai-usage-pusher"
LAUNCHD_LABEL_PREFIX = "com.chunbai.aiusage.pusher"
ENV_FILE_VARIABLE = "AI_USAGE_ENV_FILE"

TIMER_TEMPLATE_PATH = "deploy/systemd-user/ai-usage-pusher.timer"
CALENDAR_DROP_IN_PATH = "deploy/systemd/ai-usage-pusher-calendar.conf"

_DROP_IN_COMMENT = (
    "# An empty monotonic directive clears every inherited time trigger. Add the\n"
    "# calendar trigger after it, and keep Unit= in the existing base timer so each\n"
    "# BIAI collector retains its own service mapping.\n"
)


@dataclass(frozen=True)
class CollectorUnitSpec:
    """一台采集端的单元参数。所有模板都从这里渲染，不接受手工改文件。"""

    source_id: str
    release_dir: str = "/opt/ai-usage/current"
    config_path: str = "/opt/ai-usage/config/device.json"
    env_file: str = "/opt/ai-usage/secrets/ingest.env"
    lock_file: str = "/opt/ai-usage/run/pusher.lock"
    python_executable: str = "/usr/bin/python3"
    on_calendar: str = "*:0/30"
    persistent: bool = True
    accuracy: str = "1min"
    randomized_delay: str = "2min"
    timeout_seconds: int = 120
    description: str = ""

    @property
    def unit_basename(self) -> str:
        # 同 basename 的 timer/service 由 systemd 自动配对，
        # 因此模板永远不写 Unit=，避免 drop-in 覆盖时把配对改错。
        return f"{UNIT_PREFIX}-{self.source_id}" if self.source_id else UNIT_PREFIX

    @property
    def timer_name(self) -> str:
        return f"{self.unit_basename}.timer"

    @property
    def service_name(self) -> str:
        return f"{self.unit_basename}.service"

    @property
    def launchd_label(self) -> str:
        return f"{LAUNCHD_LABEL_PREFIX}.{self.source_id}" if self.source_id else LAUNCHD_LABEL_PREFIX

    @property
    def windows_task_name(self) -> str:
        # Task Scheduler 任务名与 systemd basename 同源，三个 OS 用同一套命名。
        return self.unit_basename

    @property
    def python_path(self) -> str:
        return str(Path(self.release_dir) / "src")

    @property
    def timer_description(self) -> str:
        return self.description or f"Run AI Usage Pusher ({self.source_id})"

    @property
    def service_description(self) -> str:
        return self.description or f"AI Usage Pusher ({self.source_id})"

    def exec_argv(self) -> List[str]:
        return [
            self.python_executable,
            "-m",
            "ai_usage_widget.cli",
            "push",
            "--config",
            self.config_path,
            "--lock-file",
            self.lock_file,
        ]


def _timer_trigger_lines(spec: CollectorUnitSpec) -> List[str]:
    lines = [f"OnCalendar={spec.on_calendar}"]
    if spec.persistent:
        # Persistent=true 让设备关机/休眠期间错过的触发在下次启动时补跑。
        lines.append("Persistent=true")
    lines.append(f"AccuracySec={spec.accuracy}")
    lines.append(f"RandomizedDelaySec={spec.randomized_delay}")
    return lines


def render_timer_unit(spec: CollectorUnitSpec) -> str:
    body = "\n".join(_timer_trigger_lines(spec))
    return (
        "[Unit]\n"
        f"Description={spec.timer_description}\n"
        "\n"
        "[Timer]\n"
        f"{body}\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )


def render_calendar_drop_in(spec: CollectorUnitSpec) -> str:
    body = "\n".join(_timer_trigger_lines(spec))
    return "[Timer]\n" + _DROP_IN_COMMENT + "OnUnitActiveSec=\n" + f"{body}\n"


def render_service_unit(spec: CollectorUnitSpec) -> str:
    exec_start = " ".join(spec.exec_argv())
    return (
        "[Unit]\n"
        f"Description={spec.service_description}\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"WorkingDirectory={spec.release_dir}\n"
        f"Environment=PYTHONPATH={spec.python_path}\n"
        f"EnvironmentFile={spec.env_file}\n"
        f"ExecStart={exec_start}\n"
        f"TimeoutStartSec={spec.timeout_seconds}\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def render_launchd_plist(spec: CollectorUnitSpec) -> bytes:
    """launchd 侧对应物。

    launchd 没有 `Persistent=`，等价机制是 `StartCalendarInterval`：
    设备休眠期间错过的触发会在唤醒后补跑，`RunAtLoad` 保证开机即跑一次。
    环境变量里只放 PYTHONPATH 和 env 文件路径，**绝不写入 token 值**。
    """

    payload = {
        "Label": spec.launchd_label,
        "ProgramArguments": spec.exec_argv(),
        "StartCalendarInterval": _launchd_calendar_intervals(spec.on_calendar),
        "RunAtLoad": bool(spec.persistent),
        "WorkingDirectory": spec.release_dir,
        "EnvironmentVariables": {
            "PYTHONPATH": spec.python_path,
            ENV_FILE_VARIABLE: spec.env_file,
        },
        "StandardOutPath": str(Path(spec.release_dir).parent / "logs" / f"{spec.unit_basename}.stdout.log"),
        "StandardErrorPath": str(Path(spec.release_dir).parent / "logs" / f"{spec.unit_basename}.stderr.log"),
    }
    return plistlib.dumps(payload, sort_keys=False)


def _parse_minute_schedule(on_calendar: str) -> Tuple[int, int]:
    """把 systemd 的 `*:0/30` 解析成（起始分钟, 步长分钟）；步长非法时按每小时一次处理。"""

    _, _, minute_spec = on_calendar.partition(":")
    minute_spec = minute_spec or "0"
    start_text, _, step_text = minute_spec.partition("/")
    try:
        start = int(start_text)
    except ValueError:
        start = 0
    try:
        step = int(step_text) if step_text else 60
    except ValueError:
        step = 60
    if step <= 0 or step > 60:
        step = 60
    return start % 60, step


def _launchd_calendar_intervals(on_calendar: str) -> List[Dict[str, int]]:
    """把 systemd 的 `*:0/30` 之类的表达式翻译成 launchd 的 Minute 列表。"""

    start, step = _parse_minute_schedule(on_calendar)
    return [{"Minute": minute} for minute in range(start, 60, step)]


WINDOWS_TASK_NAMESPACE = "http://schemas.microsoft.com/windows/2004/02/mit/task"

# StartBoundary 用固定历史日期：渲染必须是纯函数（同参数逐字节相同），
# 才能沿用「模板与生成结果逐字节比对」的防漂移口径。
_WINDOWS_START_BOUNDARY_DATE = "2026-01-01"


def render_windows_task_xml(spec: CollectorUnitSpec) -> str:
    """Windows Task Scheduler 侧对应物（第三个 OS，#124）。

    - 周期语义与 systemd/launchd 同源：`*:0/30` → 每日 CalendarTrigger + PT30M 重复。
    - `StartWhenAvailable` 是 `Persistent=` / `RunAtLoad` 的对应物：错过的触发在
      开机或唤醒后补跑。
    - Task Scheduler 的 XML 没有环境变量字段，PYTHONPATH 与 env 文件路径经
      cmd.exe 的 `set` 注入命令行——与另两个 OS 相同，**绝不写入 token 值**。
    - 导入方式：`schtasks /Create /TN <windows_task_name> /XML <file>`，
      文件需以 UTF-16 编码写盘（与 XML 声明一致）。
    """

    start, step = _parse_minute_schedule(spec.on_calendar)
    exec_command = " ".join(_windows_quote(part) for part in spec.exec_argv())
    arguments = (
        f'/c set "PYTHONPATH={spec.python_path}" && '
        f'set "{ENV_FILE_VARIABLE}={spec.env_file}" && '
        f"{exec_command}"
    )
    catch_up = "true" if spec.persistent else "false"
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        f'<Task version="1.2" xmlns="{WINDOWS_TASK_NAMESPACE}">\n'
        "  <RegistrationInfo>\n"
        f"    <Description>{_xml_escape(spec.service_description)}</Description>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        "    <CalendarTrigger>\n"
        "      <Repetition>\n"
        f"        <Interval>PT{step}M</Interval>\n"
        "        <Duration>P1D</Duration>\n"
        "        <StopAtDurationEnd>false</StopAtDurationEnd>\n"
        "      </Repetition>\n"
        f"      <StartBoundary>{_WINDOWS_START_BOUNDARY_DATE}T00:{start:02d}:00</StartBoundary>\n"
        "      <Enabled>true</Enabled>\n"
        "      <ScheduleByDay>\n"
        "        <DaysInterval>1</DaysInterval>\n"
        "      </ScheduleByDay>\n"
        "    </CalendarTrigger>\n"
        "  </Triggers>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        f"    <StartWhenAvailable>{catch_up}</StartWhenAvailable>\n"
        f"    <ExecutionTimeLimit>PT{spec.timeout_seconds}S</ExecutionTimeLimit>\n"
        "  </Settings>\n"
        "  <Actions>\n"
        "    <Exec>\n"
        "      <Command>cmd.exe</Command>\n"
        f"      <Arguments>{_xml_escape(arguments)}</Arguments>\n"
        f"      <WorkingDirectory>{_xml_escape(spec.release_dir)}</WorkingDirectory>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )


def _windows_quote(part: str) -> str:
    """cmd.exe 参数引号保护：Windows 路径带空格是常态（如 C:\\Program Files\\...）。"""

    return f'"{part}"' if (" " in part or "\t" in part) else part


def write_windows_task_xml(spec: CollectorUnitSpec, target: Path) -> None:
    """按声明的编码（UTF-16）写盘，供 `schtasks /Create /XML` 导入。

    渲染结果的 XML 声明是 UTF-16，用其他编码写盘会被 schtasks 判为 malformed。
    """

    target.write_text(render_windows_task_xml(spec), encoding="utf-16")


def repository_template_spec() -> CollectorUnitSpec:
    """仓库里共享模板对应的参数（不绑定具体 source_id）。"""

    return CollectorUnitSpec(source_id="", description="Run AI Usage Pusher every 30 minutes")


def render_repository_templates() -> Dict[str, str]:
    """仓库里已提交的部署模板 → 生成内容。测试用它逐字节比对，禁止手工漂移。"""

    spec = repository_template_spec()
    return {
        TIMER_TEMPLATE_PATH: render_timer_unit(spec),
        CALENDAR_DROP_IN_PATH: render_calendar_drop_in(spec),
    }


def write_repository_templates(root: Path) -> List[str]:
    written = []
    for relative_path, content in render_repository_templates().items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.read_text(encoding="utf-8") != content:
            target.write_text(content, encoding="utf-8")
            written.append(relative_path)
    return written


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ai_usage_widget.deploy_units")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--write", action="store_true", help="把生成结果写回 deploy/")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not args.write:
        drifted = [
            relative_path
            for relative_path, content in render_repository_templates().items()
            if not (root / relative_path).exists()
            or (root / relative_path).read_text(encoding="utf-8") != content
        ]
        for relative_path in drifted:
            print(f"drift: {relative_path}", file=sys.stderr)
        return 1 if drifted else 0

    for relative_path in write_repository_templates(root):
        print(f"wrote: {relative_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
