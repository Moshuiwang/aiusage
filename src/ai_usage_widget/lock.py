from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


class LockAlreadyHeld(RuntimeError):
    pass


class FileLock:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._fd: Optional[int] = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self._fd, str(os.getpid()).encode("utf-8"))
        except FileExistsError as exc:
            raise LockAlreadyHeld(f"lock already held: {self.path}") from exc

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()
