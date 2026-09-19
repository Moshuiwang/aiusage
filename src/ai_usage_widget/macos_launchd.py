"""用于 macOS 用户会话的 LaunchAgent 注册与启动。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence


CommandRunner = Callable[[Sequence[str]], int]


class LaunchdActivationError(RuntimeError):
    """LaunchAgent 无法注册、启动或回读确认。"""


def default_command_runner(argv: Sequence[str]) -> int:  # pragma: no cover - 真实系统路径
    return subprocess.run(list(argv), check=False).returncode


def ensure_agent_loaded(
    plist_path: Path,
    label: str,
    *,
    user_id: Optional[int] = None,
    command_runner: Optional[CommandRunner] = None,
) -> Dict[str, object]:
    """确保 LaunchAgent 在当前用户会话中已注册，并立即运行一次。

    `~/Library/LaunchAgents` 中有 plist 只代表文件存在；当前登录会话仍可能没有
    对应服务。这里先回读服务，缺失时 bootstrap，随后 kickstart，并再次回读。
    所有命令都使用 argv 传参，避免把路径或配置内容拼进 shell。
    """

    if not label.strip():
        raise ValueError("launchd label is required")
    path = Path(plist_path).expanduser()
    uid = os.getuid() if user_id is None else user_id
    domain = f"gui/{uid}"
    target = f"{domain}/{label}"
    runner = command_runner or default_command_runner
    commands = []

    print_command = ["launchctl", "print", target]
    commands.append(print_command)
    loaded = runner(print_command) == 0
    bootstrapped = False

    if not loaded:
        bootstrap_command = ["launchctl", "bootstrap", domain, str(path)]
        commands.append(bootstrap_command)
        code = runner(bootstrap_command)
        if code != 0:
            raise LaunchdActivationError(
                f"launchctl bootstrap failed for {label}: exit {code}"
            )
        bootstrapped = True

    kickstart_command = ["launchctl", "kickstart", "-k", target]
    commands.append(kickstart_command)
    code = runner(kickstart_command)
    if code != 0:
        raise LaunchdActivationError(
            f"launchctl kickstart failed for {label}: exit {code}"
        )

    verify_command = ["launchctl", "print", target]
    commands.append(verify_command)
    code = runner(verify_command)
    if code != 0:
        raise LaunchdActivationError(
            f"launchctl verification failed for {label}: exit {code}"
        )

    return {
        "success": True,
        "domain": domain,
        "label": label,
        "plist_path": str(path),
        "bootstrapped": bootstrapped,
        "kickstarted": True,
        "verified": True,
        "commands": commands,
    }
