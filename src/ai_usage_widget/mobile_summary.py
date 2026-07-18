from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional


LIMIT_STALE_AFTER_MINUTES = 120


def build_mobile_summary(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    summary = _dict(snapshot.get("summary"))
    trend = _dict(snapshot.get("trend"))
    source_status = _list(snapshot.get("source_status"))
    groups = _dict(snapshot.get("groups"))
    items = _list(snapshot.get("items"))
    limits = _list(snapshot.get("limits"))
    limit_providers = _mobile_limit_providers(_list(snapshot.get("limit_status")))
    generated_at = _parse_datetime(snapshot.get("generated_at"))

    cache_tokens = _int(summary.get("cache_creation_tokens")) + _int(summary.get("cache_read_tokens"))
    total_tokens = _int(summary.get("total_tokens"))

    account_context = _account_context(snapshot.get("account_hourly"), snapshot.get("ai_accounts"))
    normalized_windows = [
        window
        for row in limits
        if isinstance(row, dict)
        for window in [_limit_window(row, account_context)]
        if _effective_limit_window(window)
    ]
    selected_sources = _selected_limit_sources(normalized_windows, limit_providers)
    provider_status = {
        str(row.get("provider") or "").lower(): str(row.get("status") or "unavailable")
        for row in limit_providers
    }
    candidate_windows = [
        window
        for window in normalized_windows
        if selected_sources.get(str(window.get("provider") or "").lower()) == str(window.get("source_id") or "")
        if provider_status.get(str(window.get("provider") or "").lower(), "ok") == "ok"
        if not _expired_short_window(window, generated_at)
    ]
    windows = [window for window in candidate_windows if not _stale_limit_window(window, generated_at)]
    by_machine = _group_rows(_list(groups.get("by_machine")))
    visible_source_ids = {
        str(source_id)
        for row in by_machine
        for source_id in _list(row.get("source_ids"))
    }
    health_source_ids = {
        str(row.get("source_id") or "")
        for row in source_status
        if isinstance(row, dict) and _is_health_issue_source(row)
    }
    mobile_source_ids = visible_source_ids | health_source_ids
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
        "sources": [
            _mobile_source(row)
            for row in source_status
            if isinstance(row, dict)
            and str(row.get("source_id") or "") in mobile_source_ids
        ],
        "breakdown": {
            "by_machine": by_machine,
            "by_os_user": _os_user_rows(_list(groups.get("by_machine")), items),
            "by_agent": _agent_rows(items),
            "by_model": _model_rows(items),
            "by_date": _date_rows(items),
        },
        "limits": {
            "observed_count": sum(
                1
                for row in windows
                if row.get("confidence") == "observed"
                and row.get("official") is True
                and row.get("status") == "ok"
            ),
            "total_count": len(windows),
            "windows": windows,
            "providers": limit_providers,
        },
        "metadata": _mobile_metadata(snapshot, windows, candidate_windows, generated_at),
    }


def _mobile_limit_providers(rows: List[Any]) -> List[Dict[str, Any]]:
    fields = ("provider", "source_id", "observed_at", "source_type", "status")
    return [
        {field: row.get(field) for field in fields}
        for row in rows
        if isinstance(row, dict) and row.get("provider") and row.get("source_id")
    ]


def _selected_limit_sources(
    windows: List[Dict[str, Any]],
    providers: List[Dict[str, Any]],
) -> Dict[str, str]:
    selected = {
        str(row.get("provider") or "").lower(): str(row.get("source_id") or "")
        for row in providers
    }
    newest: Dict[str, tuple[float, str]] = {}
    for window in windows:
        provider = str(window.get("provider") or "").lower()
        if provider in selected:
            continue
        observed = _parse_datetime(window.get("observed_at"))
        rank = observed.timestamp() if observed is not None else float("-inf")
        source_id = str(window.get("source_id") or "")
        if provider not in newest or (rank, source_id) > newest[provider]:
            newest[provider] = (rank, source_id)
    selected.update({provider: value[1] for provider, value in newest.items()})
    return selected


def _mobile_trend(trend: Dict[str, Any]) -> Dict[str, Any]:
    source_points = [row for row in _list(trend.get("points")) if isinstance(row, dict)]
    claude_values = [0 for _ in source_points]
    codex_values = [0 for _ in source_points]
    for agent_row in _list(trend.get("by_agent")):
        if not isinstance(agent_row, dict):
            continue
        agent = str(agent_row.get("agent") or "").lower()
        target = claude_values if "claude" in agent else codex_values if ("codex" in agent or "openai" in agent or "gpt" in agent) else None
        if target is None:
            continue
        for index, value in enumerate(_list(agent_row.get("values"))[:len(source_points)]):
            target[index] += max(_int(value), 0)

    points = []
    for index, row in enumerate(source_points):
        bucket = row.get("hour") or row.get("date")
        total_tokens = _int(row.get("total_tokens"))
        cache_tokens = _int(row.get("cache_tokens"))
        claude_tokens, codex_tokens = _fit_known_agent_tokens(
            total_tokens,
            claude_values[index],
            codex_values[index],
        )
        points.append({
            "bucket": bucket,
            "label": _trend_label(bucket, trend.get("granularity")),
            "tokens": total_tokens,
            "input_tokens": _int(row.get("input_tokens")),
            "output_tokens": _int(row.get("output_tokens")),
            "cache_tokens": cache_tokens,
            "cache_ratio": _ratio(cache_tokens, total_tokens),
            "claude_tokens": claude_tokens,
            "codex_tokens": codex_tokens,
            "unknown_tokens": max(total_tokens - claude_tokens - codex_tokens, 0),
        })
    return {
        "period": trend.get("period"),
        "granularity": trend.get("granularity"),
        "start_date": trend.get("start_date"),
        "end_date": trend.get("end_date"),
        "points": points,
    }


def _fit_known_agent_tokens(total: int, claude: int, codex: int) -> tuple[int, int]:
    total = max(total, 0)
    claude = max(claude, 0)
    codex = max(codex, 0)
    known = claude + codex
    if known <= total:
        return claude, codex
    if known == 0:
        return 0, 0
    fitted_claude = total * claude // known
    return fitted_claude, total - fitted_claude


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
        "accuracy": row.get("accuracy") or {"status": "unknown", "agents": []},
    }


def _is_health_issue_source(row: Dict[str, Any]) -> bool:
    status = str(row.get("status") or "").lower()
    return status not in {"", "ok", "disabled"}


def _limit_window(row: Dict[str, Any], account_context: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    provider = str(row.get("provider") or "")
    provider_context = account_context.get(provider.lower(), {})
    account_label = _safe_account_label(
        row.get("account_email")
        or row.get("account_label")
        or provider_context.get("label")
        or provider_context.get("display_name")
    )
    plan_label = _safe_plan_label(
        provider,
        row.get("account_plan_label")
        or row.get("account_plan")
        or row.get("subscription")
        or provider_context.get("subscription")
    )
    result = {
        "source_id": row.get("source_id"),
        "provider": provider,
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
    if account_label:
        result["account_label"] = account_label
    if plan_label:
        result["account_plan_label"] = plan_label
    return result


def _effective_limit_window(window: Dict[str, Any]) -> bool:
    return (
        window.get("official") is True
        and window.get("confidence") == "observed"
        and window.get("status") == "ok"
        and window.get("source_type") != "active_limits_cache"
    )


def _mobile_metadata(
    snapshot: Dict[str, Any],
    windows: List[Dict[str, Any]],
    candidate_windows: List[Dict[str, Any]],
    generated_at: Optional[datetime],
) -> Dict[str, Any]:
    metadata = _dict(snapshot.get("metadata"))
    limits_observed_at = metadata.get("limits_observed_at") or max(
        (str(window.get("observed_at") or "") for window in candidate_windows),
        default=None,
    )
    freshness_status = metadata.get("freshness_status") or ("ok" if windows else "unknown")
    if not windows and candidate_windows and any(_stale_limit_window(window, generated_at) for window in candidate_windows):
        freshness_status = "stale"
    return {
        "backend_mode": metadata.get("backend_mode") or "origin_direct",
        "canonical_store": metadata.get("canonical_store") or "origin_sqlite",
        "read_model_generated_at": metadata.get("read_model_generated_at") or snapshot.get("generated_at"),
        "freshness_status": freshness_status,
        "limits_observed_at": limits_observed_at,
    }


def _stale_limit_window(window: Dict[str, Any], generated_at: Optional[datetime]) -> bool:
    if generated_at is None:
        return False
    observed_at = _parse_datetime(window.get("observed_at"))
    if observed_at is None:
        return True
    if observed_at.tzinfo is not None and generated_at.tzinfo is not None:
        observed_at = observed_at.astimezone(generated_at.tzinfo)
    try:
        age_minutes = (generated_at - observed_at).total_seconds() / 60
    except TypeError:
        return True
    return age_minutes > LIMIT_STALE_AFTER_MINUTES


def _group_rows(rows: List[Any]) -> List[Dict[str, Any]]:
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = row.get("display_name") or row.get("name")
        total_tokens = _int(row.get("total_tokens"))
        if total_tokens <= 0:
            continue
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
            total_tokens = _int(user.get("total_tokens"))
            if total_tokens <= 0:
                continue
            label = user.get("account") or "unknown"
            entry = rows.setdefault(str(label), {
                "id": label,
                "label": label,
                "tokens": 0,
                "source_ids": set(),
                "contributions": {},
            })
            entry["tokens"] += total_tokens
            entry["source_ids"].update(str(source_id) for source_id in _list(user.get("source_ids")))
            _add_contribution(entry["contributions"], _list(user.get("source_ids")), total_tokens)

    if not rows:
        for item in items:
            if not isinstance(item, dict):
                continue
            total_tokens = _int(item.get("total_tokens"))
            if total_tokens <= 0:
                continue
            label = item.get("account") or "unknown"
            entry = rows.setdefault(str(label), {
                "id": label,
                "label": label,
                "tokens": 0,
                "source_ids": set(),
                "contributions": {},
            })
            entry["tokens"] += total_tokens
            if item.get("source_id"):
                entry["source_ids"].add(str(item["source_id"]))
                _add_contribution(entry["contributions"], [item["source_id"]], total_tokens)

    normalized = []
    for row in rows.values():
        if _int(row["tokens"]) <= 0:
            continue
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


def _expired_short_window(window: Dict[str, Any], generated_at: Optional[datetime]) -> bool:
    if generated_at is None or not _is_short_window(window):
        return False
    reset_at = _parse_datetime(window.get("reset_at"))
    if reset_at is None:
        return False
    reset_at, generated_at = _align_datetimes(reset_at, generated_at)
    return reset_at <= generated_at


def _is_short_window(window: Dict[str, Any]) -> bool:
    name = str(window.get("window") or "").lower()
    duration = _int(window.get("window_duration_minutes"))
    return (
        "5h" in name
        or "session" in name
        or (duration > 0 and duration <= 360)
    )


def _account_context(account_hourly: Any, ai_accounts: Any = None) -> Dict[str, Dict[str, Any]]:
    rows = _list(_dict(account_hourly).get("by_ai_account")) + _list(ai_accounts)
    grouped: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        provider = _provider_context_key(row.get("provider"))
        context = _account_context_row(row)
        if not provider or not context:
            continue
        key = _account_context_key(context, index)
        provider_accounts = grouped.setdefault(provider, {})
        if key in provider_accounts:
            _merge_account_context(provider_accounts[key], context)
        else:
            provider_accounts[key] = context
    result: Dict[str, Dict[str, Any]] = {}
    for provider, provider_accounts in grouped.items():
        accounts = list(provider_accounts.values())
        if len(accounts) == 1:
            result[provider] = accounts[0]
    return result


def _account_context_row(row: Dict[str, Any]) -> Dict[str, Any]:
    account_id = str(row.get("account_id") or row.get("ai_account_id") or "").strip()
    label = _safe_account_label(row.get("label") or row.get("account_label") or row.get("account_email"))
    display_name = _safe_account_label(row.get("display_name"))
    subscription = row.get("subscription") or row.get("account_plan") or row.get("account_plan_label")
    result = {
        "account_id": account_id,
        "label": label,
        "display_name": display_name,
        "subscription": subscription,
    }
    return {
        key: value
        for key, value in result.items()
        if value not in (None, "")
    }


def _account_context_key(context: Dict[str, Any], index: int) -> str:
    for key in ("account_id", "label", "display_name"):
        value = context.get(key)
        if value:
            return f"{key}:{value}"
    return f"row:{index}"


def _merge_account_context(target: Dict[str, Any], source: Dict[str, Any]) -> None:
    for key, value in source.items():
        if target.get(key) in (None, "") and value not in (None, ""):
            target[key] = value


def _provider_context_key(value: Any) -> str:
    provider = str(value or "").lower()
    if provider == "openai":
        return "codex"
    if provider == "anthropic":
        return "claude"
    return provider


def _safe_account_label(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    lowered = text.lower()
    unsafe_fragments = (
        "token",
        "bearer ",
        "authorization",
        "auth.json",
        ".codex",
        ".claude",
        "/users/",
        "/home/",
        "\\users\\",
    )
    if lowered.startswith(("sk-", "sess-", "eyj")):
        return None
    if any(fragment in lowered for fragment in unsafe_fragments):
        return None
    if len(text) > 120:
        return None
    return text


def _safe_plan_label(provider: str, value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    lowered = raw.lower().replace("_", " ").replace("-", " ")
    normalized = " ".join(lowered.split())
    provider_key = provider.lower()
    if "codex" in provider_key or "openai" in provider_key:
        if normalized == "pro":
            return "Pro 20x"
        if normalized in {"prolite", "pro lite"}:
            return "Pro 5x"
    if "claude" in provider_key or "anthropic" in provider_key:
        if normalized in {"pro", "claude pro"}:
            return "Pro"
    if len(raw) <= 32 and all(ch.isalnum() or ch in " .+-_" for ch in raw):
        display = " ".join(raw.replace("_", " ").replace("-", " ").split())
        return " ".join(_title_plan_part(part) for part in display.split())
    return None


def _title_plan_part(value: str) -> str:
    if value.lower().endswith("x") and any(ch.isdigit() for ch in value):
        return value.lower()
    return value[:1].upper() + value[1:]


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _align_datetimes(lhs: datetime, rhs: datetime) -> tuple[datetime, datetime]:
    if lhs.tzinfo is None and rhs.tzinfo is not None:
        lhs = lhs.replace(tzinfo=rhs.tzinfo)
    elif lhs.tzinfo is not None and rhs.tzinfo is None:
        rhs = rhs.replace(tzinfo=lhs.tzinfo)
    elif lhs.tzinfo is not None and rhs.tzinfo is not None:
        lhs = lhs.astimezone(rhs.tzinfo)
    return lhs, rhs


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
