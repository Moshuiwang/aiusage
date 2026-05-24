from __future__ import annotations

import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict

from .models import CommandResult


def run_source(source: Dict[str, Any]) -> CommandResult:
    source_type = source["type"]
    if source_type == "local":
        return run_local(source)
    if source_type == "ssh":
        return run_ssh(source)
    if source_type == "file_import":
        return run_file_import(source)
    return CommandResult(error_type="unsupported_shape", error_message=f"unsupported source type: {source_type}")


def run_local(source: Dict[str, Any]) -> CommandResult:
    command = source["reports"]["daily"]["command"]
    timeout = float(source.get("timeout_seconds", 30))
    return _run_command(shlex.split(command), command, timeout, missing_tool_error="missing_tool")


def run_ssh(source: Dict[str, Any]) -> CommandResult:
    command = source["reports"]["daily"]["command"]
    timeout = float(source.get("timeout_seconds", 30))
    ssh_port = str(source.get("ssh_port", 22))
    remote = f"{source['ssh_user']}@{source['ssh_host']}"
    argv = ["ssh", "-p", ssh_port, remote, command]
    display_command = f"ssh -p {ssh_port} {remote} '<remote-command>'"
    result = _run_command(argv, display_command, timeout, missing_tool_error="ssh_failed")
    if result.exit_code == 255 and result.error_type == "command_failed":
        result.error_type = "ssh_failed"
        result.error_message = "ssh exited with code 255"
    return result


def run_file_import(source: Dict[str, Any]) -> CommandResult:
    start = time.monotonic()
    report_path = Path(source["reports"]["daily"]["path"])
    try:
        stdout = report_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return CommandResult(
            duration_ms=_duration_ms(start),
            error_type="missing_file",
            error_message=f"missing file: {report_path}",
            command=f"read {report_path}",
        )
    except OSError as exc:
        return CommandResult(
            duration_ms=_duration_ms(start),
            error_type="command_failed",
            error_message=str(exc),
            command=f"read {report_path}",
        )

    try:
        json.loads(stdout)
    except json.JSONDecodeError as exc:
        return CommandResult(
            stdout=stdout,
            duration_ms=_duration_ms(start),
            error_type="invalid_json",
            error_message=str(exc),
            command=f"read {report_path}",
        )

    return CommandResult(stdout=stdout, exit_code=0, duration_ms=_duration_ms(start), command=f"read {report_path}")


def _run_command(argv: list[str], display_command: str, timeout: float, missing_tool_error: str) -> CommandResult:
    start = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return CommandResult(
            duration_ms=_duration_ms(start),
            error_type=missing_tool_error,
            error_message=str(exc),
            command=display_command,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            duration_ms=_duration_ms(start),
            error_type="timeout",
            error_message=f"command timed out after {timeout:g}s",
            command=display_command,
        )

    error_type = None
    error_message = None
    if completed.returncode != 0:
        error_type = "command_failed"
        error_message = f"command exited with code {completed.returncode}"

    return CommandResult(
        stdout=completed.stdout,
        stderr=completed.stderr,
        exit_code=completed.returncode,
        duration_ms=_duration_ms(start),
        error_type=error_type,
        error_message=error_message,
        command=display_command,
    )


def _duration_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)

