from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None  # type: ignore


def period_bounds(date_str: str, period: str) -> tuple[str, Optional[str], str]:
    period_id = period if period in {"today", "week", "month", "all"} else "today"
    end = datetime.strptime(date_str, "%Y-%m-%d").date()
    if period_id == "today":
        start = end
    elif period_id == "week":
        start = end - timedelta(days=6)
    elif period_id == "month":
        start = end - timedelta(days=29)
    else:
        start = None
    return period_id, start.isoformat() if start else None, end.isoformat()


def date_axis(start_date: Optional[str], end_date: str, rows: list[Any]) -> list[str]:
    if start_date is None:
        return sorted({row[1] for row in rows})
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    days = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def hour_axis(ref_time: datetime, date_str: str) -> list[str]:
    day = datetime.strptime(date_str, "%Y-%m-%d")
    start_hour = day.replace(tzinfo=ref_time.tzinfo)
    return [(start_hour + timedelta(hours=i)).isoformat(timespec="seconds") for i in range(24)]


def parse_datetime(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def zoneinfo(timezone_str: str):
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(timezone_str)
    except Exception:
        return None
