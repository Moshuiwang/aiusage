from __future__ import annotations

from typing import Any, Dict, Iterable, List


def build_mobile_summary(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    summary = _dict(snapshot.get("summary"))
    trend = _dict(snapshot.get("trend"))
    source_status = _list(snapshot.get("source_status"))
    groups = _dict(snapshot.get("groups"))
    items = _list(snapshot.get("items"))
    limits = _list(snapshot.get("limits"))

    cache_tokens = _int(summary.get("cache_creation_tokens")) + _int(summary.get("cache_read_tokens"))
    total_tokens = _int(summary.get("total_tokens"))

    windows = [_limit_window(row) for row in limits if isinstance(row, dict)]
    return {
        "schema_version": 1,
        "client": "ios",
        "generated_at": snapshot.get("generated_at"),
        "timezone": snapshot.get("timezone"),
        "period": {
            "id": summary.get("period") or "today",
            "date": summary.get("date"),
            "start_date": summary.get("start_date"),
            "end_date": summary.get("end_date"),
            "total_tokens": total_tokens,
            "input_tokens": _int(summary.get("input_tokens")),
            "output_tokens": _int(summary.get("output_tokens")),
            "cache_tokens": cache_tokens,
            "cache_ratio": _ratio(cache_tokens, total_tokens),
            "machine": summary.get("machine"),
            "account": summary.get("account"),
        },
        "trend": _mobile_trend(trend),
        "sources": [_mobile_source(row) for row in source_status if isinstance(row, dict)],
        "breakdown": {
            "by_machine": _group_rows(_list(groups.get("by_machine"))),
            "by_os_user": _os_user_rows(_list(groups.get("by_machine")), items),
            "by_agent": _agent_rows(items),
            "by_model": _model_rows(items),
            "by_date": _date_rows(items),
        },
        "limits": {
            "observed_count": sum(1 for row in windows if row.get("confidence") == "observed"),
            "total_count": len(windows),
            "windows": windows,
        },
    }


def _mobile_trend(trend: Dict[str, Any]) -> Dict[str, Any]:
    points = []
    for row in _list(trend.get("points")):
        if not isinstance(row, dict):
            continue
        bucket = row.get("hour") or row.get("date")
        total_tokens = _int(row.get("total_tokens"))
        cache_tokens = _int(row.get("cache_tokens"))
        points.append({
            "bucket": bucket,
            "label": _trend_label(bucket, trend.get("granularity")),
            "tokens": total_tokens,
            "input_tokens": _int(row.get("input_tokens")),
            "output_tokens": _int(row.get("output_tokens")),
            "cache_tokens": cache_tokens,
            "cache_ratio": _ratio(cache_tokens, total_tokens),
        })
    return {
        "period": trend.get("period"),
        "granularity": trend.get("granularity"),
        "start_date": trend.get("start_date"),
        "end_date": trend.get("end_date"),
        "points": points,
    }


def _mobile_source(row: Dict[str, Any]) -> Dict[str, Any]:
    machine = row.get("machine") or row.get("host") or row.get("source_id")
    os_user = row.get("os_user") or row.get("account")
    observed_at = row.get("observed_at")
    return {
        "source_id": row.get("source_id"),
        "machine": machine,
        "os_user": os_user,
        "platform": row.get("platform"),
        "display_name": row.get("display_name") or _display_name(machine, os_user),
        "status": row.get("status") or "unknown",
        "last_observed_at": observed_at,
        "last_pushed_at": observed_at,
        "error_message": row.get("error_message"),
    }


def _limit_window(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source_id": row.get("source_id"),
        "provider": row.get("provider"),
        "window": row.get("window"),
        "used_percent": _number(row.get("used_percent")),
        "remaining_percent": _number(row.get("remaining_percent")),
        "reset_at": row.get("reset_at"),
        "window_duration_minutes": _int(row.get("window_duration_minutes")),
        "observed_at": row.get("observed_at"),
        "source_type": row.get("source_type"),
        "confidence": row.get("confidence") or "unknown",
        "status": row.get("status") or "unknown",
        "official": bool(row.get("official")),
    }


def _group_rows(rows: List[Any]) -> List[Dict[str, Any]]:
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = row.get("display_name") or row.get("name")
        total_tokens = _int(row.get("total_tokens"))
        source_ids = set(str(source_id) for source_id in _list(row.get("source_ids")))
        contributions: Dict[str, int] = {}
        for user in _list(row.get("users")):
            if not isinstance(user, dict):
                continue
            source_ids.update(str(source_id) for source_id in _list(user.get("source_ids")))
            _add_contribution(contributions, _list(user.get("source_ids")), _int(user.get("total_tokens")))
        if not contributions:
            _add_contribution(contributions, _list(row.get("source_ids")), total_tokens)
        result.append({
            "id": row.get("name") or label,
            "label": label,
            "tokens": total_tokens,
            "source_ids": sorted(source_ids),
            "contributions": _contribution_rows(contributions),
        })
    return _sort_rows(result)


def _os_user_rows(machine_rows: List[Any], items: List[Any]) -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for machine in machine_rows:
        if not isinstance(machine, dict):
            continue
        for user in _list(machine.get("users")):
            if not isinstance(user, dict):
                continue
            label = user.get("account") or "unknown"
            entry = rows.setdefault(str(label), {
                "id": label,
                "label": label,
                "tokens": 0,
                "source_ids": set(),
                "contributions": {},
            })
            entry["tokens"] += _int(user.get("total_tokens"))
            entry["source_ids"].update(str(source_id) for source_id in _list(user.get("source_ids")))
            _add_contribution(entry["contributions"], _list(user.get("source_ids")), _int(user.get("total_tokens")))

    if not rows:
        for item in items:
            if not isinstance(item, dict):
                continue
            label = item.get("account") or "unknown"
            entry = rows.setdefault(str(label), {
                "id": label,
                "label": label,
                "tokens": 0,
                "source_ids": set(),
                "contributions": {},
            })
            entry["tokens"] += _int(item.get("total_tokens"))
            if item.get("source_id"):
                entry["source_ids"].add(str(item["source_id"]))
                _add_contribution(entry["contributions"], [item["source_id"]], _int(item.get("total_tokens")))

    normalized = []
    for row in rows.values():
        normalized.append({
            "id": row["id"],
            "label": row["label"],
            "tokens": row["tokens"],
            "source_ids": sorted(row["source_ids"]),
            "contributions": _contribution_rows(row["contributions"]),
        })
    return _sort_rows(normalized)


def _agent_rows(items: List[Any]) -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        label = item.get("agent") or "unknown"
        entry = rows.setdefault(str(label), {
            "id": label,
            "label": label,
            "tokens": 0,
            "source_ids": set(),
            "contributions": {},
        })
        entry["tokens"] += _int(item.get("total_tokens"))
        if item.get("source_id"):
            entry["source_ids"].add(str(item["source_id"]))
            _add_contribution(entry["contributions"], [item["source_id"]], _int(item.get("total_tokens")))

    return _sort_rows([
        {
            "id": str(row["id"]),
            "label": str(row["label"]),
            "tokens": row["tokens"],
            "source_ids": sorted(row["source_ids"]),
            "contributions": _contribution_rows(row["contributions"]),
        }
        for row in rows.values()
    ])


def _model_rows(items: List[Any]) -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        for model in _list(item.get("model_breakdowns")):
            if not isinstance(model, dict):
                continue
            label = model.get("model_name") or "unknown"
            entry = rows.setdefault(str(label), {
                "id": label,
                "label": label,
                "tokens": 0,
                "source_ids": set(),
                "contributions": {},
            })
            entry["tokens"] += _int(model.get("total_tokens"))
            if item.get("source_id"):
                entry["source_ids"].add(str(item["source_id"]))
                _add_contribution(entry["contributions"], [item["source_id"]], _int(model.get("total_tokens")))
    return _sort_rows([
        {
            "id": str(row["id"]),
            "label": str(row["label"]),
            "tokens": row["tokens"],
            "source_ids": sorted(row["source_ids"]),
            "contributions": _contribution_rows(row["contributions"]),
        }
        for row in rows.values()
    ])


def _date_rows(items: List[Any]) -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        label = item.get("date") or "unknown"
        entry = rows.setdefault(str(label), {
            "id": label,
            "label": label,
            "tokens": 0,
            "source_ids": set(),
            "contributions": {},
        })
        entry["tokens"] += _int(item.get("total_tokens"))
        if item.get("source_id"):
            entry["source_ids"].add(str(item["source_id"]))
            _add_contribution(entry["contributions"], [item["source_id"]], _int(item.get("total_tokens")))
    return sorted(
        [
            {
                "id": str(row["id"]),
                "label": str(row["label"]),
                "tokens": row["tokens"],
                "source_ids": sorted(row["source_ids"]),
                "contributions": _contribution_rows(row["contributions"]),
            }
            for row in rows.values()
        ],
        key=lambda row: row["label"],
    )


def _add_contribution(contributions: Dict[str, int], source_ids: List[Any], tokens: int) -> None:
    normalized = [str(source_id) for source_id in source_ids if source_id]
    if not normalized:
        return
    if len(normalized) == 1:
        contributions[normalized[0]] = contributions.get(normalized[0], 0) + tokens
        return
    for source_id in normalized:
        contributions[source_id] = contributions.get(source_id, 0) + tokens


def _contribution_rows(contributions: Dict[str, int]) -> List[Dict[str, Any]]:
    return [
        {"source_id": source_id, "tokens": tokens}
        for source_id, tokens in sorted(contributions.items())
    ]


def _sort_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda row: (-_int(row.get("tokens")), str(row.get("label") or "")))


def _trend_label(bucket: Any, granularity: Any) -> str:
    if not isinstance(bucket, str):
        return ""
    if granularity == "hour" and "T" in bucket:
        return bucket.split("T", 1)[1][:5]
    return bucket


def _display_name(machine: Any, os_user: Any) -> str:
    if machine and os_user:
        return f"{machine} · {os_user}"
    return str(machine or os_user or "unknown-source")


def _ratio(part: int, total: int) -> int:
    if total <= 0:
        return 0
    return round((part / total) * 100)


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(round(value))
    return 0


def _number(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []
