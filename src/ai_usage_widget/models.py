from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class CommandResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    duration_ms: int = 0
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    command: str = ""

    @property
    def ok(self) -> bool:
        return self.error_type is None and self.exit_code == 0
