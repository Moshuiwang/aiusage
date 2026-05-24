from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional

from .models import NormalizeResult, UsageItem


def normalize_ccusage_daily(source: Dict[str, Any], stdout: str) -> NormalizeResult:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return NormalizeResult(status="failed", error_type="invalid_json", error_message=str(exc))

    daily = payload.get("daily")
    if not isinstance(daily, list):
        return NormalizeResult(
            status="failed",
            error_type="unsupported_shape",
            error_message="expected top-level daily list",
        )

    items = []
    for row in daily:
        if not isinstance(row, dict) or not row.get("period"):
            return NormalizeResult(
                status="failed",
                error_type="unsupported_shape",
                error_message="daily row must be an object with period",
            )
        items.append(_daily_row_to_item(source, row))

    return NormalizeResult(items=items)


def _daily_row_to_item(source: Dict[str, Any], row: Dict[str, Any]) -> UsageItem:
    input_tokens = _int_field(row, "inputTokens")
    output_tokens = _int_field(row, "outputTokens")
    cache_creation_tokens = _int_field(row, "cacheCreationTokens")
    cache_read_tokens = _int_field(row, "cacheReadTokens")
    total_tokens = _optional_int_field(row, "totalTokens")
    if total_tokens is None:
        total_tokens = input_tokens + output_tokens + cache_creation_tokens + cache_read_tokens

    return UsageItem(
        source_id=source["source_id"],
        machine=source.get("host_label") or source.get("machine") or source["source_id"],
        account=source.get("os_user") or source.get("account") or "unknown",
        agent=row.get("agent") or "unknown",
        date=str(row["period"]),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        total_tokens=total_tokens,
        total_cost=_optional_float_field(row, "totalCost"),
        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
        model_breakdowns=list(_normalize_models(row.get("modelBreakdowns"))),
    )


def _normalize_models(models: Any) -> Iterable[Dict[str, Any]]:
    if not isinstance(models, list):
        return []
    normalized = []
    for model in models:
        if not isinstance(model, dict):
            continue
        input_tokens = _int_field(model, "inputTokens")
        output_tokens = _int_field(model, "outputTokens")
        cache_creation_tokens = _int_field(model, "cacheCreationTokens")
        cache_read_tokens = _int_field(model, "cacheReadTokens")
        total_tokens = _optional_int_field(model, "totalTokens")
        if total_tokens is None:
            total_tokens = input_tokens + output_tokens + cache_creation_tokens + cache_read_tokens
        normalized.append(
            {
                "model_name": model.get("modelName") or "unknown",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_creation_tokens": cache_creation_tokens,
                "cache_read_tokens": cache_read_tokens,
                "total_tokens": total_tokens,
                "cost": _optional_float_field(model, "cost"),
            }
        )
    return normalized


def _int_field(row: Dict[str, Any], name: str) -> int:
    value = row.get(name, 0)
    if value is None:
        return 0
    return int(value)


def _optional_int_field(row: Dict[str, Any], name: str) -> Optional[int]:
    value = row.get(name)
    if value is None:
        return None
    return int(value)


def _optional_float_field(row: Dict[str, Any], name: str) -> Optional[float]:
    value = row.get(name)
    if value is None:
        return None
    return float(value)

