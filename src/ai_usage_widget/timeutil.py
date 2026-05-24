from __future__ import annotations

from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore


def now_iso(timezone_name: str) -> str:
    if ZoneInfo is None:
        return datetime.now(timezone.utc).isoformat()
    return datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")

