from __future__ import annotations

from datetime import timedelta, timezone, tzinfo

try:
    from zoneinfo import ZoneInfo as _ZoneInfo
except ModuleNotFoundError:  # pragma: no cover - exercised by Python 3.8 runtime smoke.
    _ZoneInfo = None


def get_timezone(name: str) -> tzinfo:
    if _ZoneInfo is not None:
        return _ZoneInfo(name)
    if name == "Asia/Shanghai":
        return timezone(timedelta(hours=8))
    if name in {"UTC", "Etc/UTC"}:
        return timezone.utc
    raise ValueError(f"timezone database unavailable for {name}")
