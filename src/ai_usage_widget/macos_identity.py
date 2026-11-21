"""Resolve the system's stable Mac hostname without a DNS lookup."""

from __future__ import annotations

from ipaddress import ip_address
import re
import subprocess
import sys


def is_ip_literal(value: str) -> bool:
    try:
        ip_address(value)
    except ValueError:
        return False
    return True


def macos_local_hostname() -> str | None:
    if sys.platform != "darwin":
        return None
    try:
        result = subprocess.run(
            ["/usr/sbin/scutil", "--get", "LocalHostName"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    name = result.stdout.strip()
    if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", name):
        return name
    return None
