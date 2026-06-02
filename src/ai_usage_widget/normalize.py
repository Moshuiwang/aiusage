from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from .models import NormalizeResult, UsageBlockItem, UsageHourlyItem, UsageItem
from .ingest import IngestRequest

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None  # type: ignore


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

    metadata = row.get("metadata").copy() if isinstance(row.get("metadata"), dict) else {}
    metadata["ccusage_row"] = dict(row)
    if isinstance(source.get("ccusage_totals"), dict):
        metadata["ccusage_totals"] = dict(source["ccusage_totals"])

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
        metadata=metadata,
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
                "raw": dict(model),
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


def normalize_ingest_request(req: IngestRequest) -> List[UsageItem]:
    """
    将 IngestRequest 的 usage_daily 列表转换为标准化的 UsageItem 列表。
    对于同一 Payload 内重复的 (source_id, date, agent) 行，采用后面覆盖前面的去重upsert策略。
    """
    items_dict = {}
    source_config = {
        "source_id": req.source_id,
        "host_label": req.machine or req.host,
        "host": req.host,
        "os_user": req.os_user,
        "platform": req.platform,
    }

    usage_daily = req.usage_daily
    ccusage_totals = None
    if isinstance(req.ccusage_daily_report, dict):
        report_daily = req.ccusage_daily_report.get("daily")
        if isinstance(report_daily, list):
            usage_daily = report_daily
        if isinstance(req.ccusage_daily_report.get("totals"), dict):
            ccusage_totals = req.ccusage_daily_report["totals"]

    if ccusage_totals:
        source_config["ccusage_totals"] = ccusage_totals

    for row in usage_daily:
        if not isinstance(row, dict) or "period" not in row:
            continue
        item = _daily_row_to_item(source_config, row)
        # 显式把 machine 和 account 注入到 metadata 里，方便 SQLite 读写快照还原
        item.metadata["machine"] = item.machine
        item.metadata["host"] = req.host
        item.metadata["account"] = item.account
        item.metadata["platform"] = req.platform
        key = (item.source_id, item.date, item.agent)
        # 后面行覆盖前面行，确保去重
        items_dict[key] = item

    return list(items_dict.values())


def normalize_ingest_hourly_request(req: IngestRequest) -> List[UsageHourlyItem]:
    items_dict = {}
    if not isinstance(req.ccusage_session_report, dict):
        return []
    sessions = req.ccusage_session_report.get("session")
    if not isinstance(sessions, list):
        return []

    source_config = {
        "source_id": req.source_id,
        "host_label": req.machine or req.host,
        "host": req.host,
        "os_user": req.os_user,
        "platform": req.platform,
    }
    for row in sessions:
        if not isinstance(row, dict):
            continue
        hour = _session_hour(row, req.timezone)
        if not hour:
            continue
        item = _session_row_to_hourly_item(source_config, row, hour)
        key = (item.source_id, item.hour, item.agent)
        if key in items_dict:
            prev = items_dict[key]
            prev.input_tokens += item.input_tokens
            prev.output_tokens += item.output_tokens
            prev.cache_creation_tokens += item.cache_creation_tokens
            prev.cache_read_tokens += item.cache_read_tokens
            prev.total_tokens += item.total_tokens
            if prev.total_cost is not None or item.total_cost is not None:
                prev.total_cost = (prev.total_cost or 0) + (item.total_cost or 0)
        else:
            item.metadata["machine"] = item.machine
            item.metadata["host"] = req.host
            item.metadata["account"] = item.account
            item.metadata["platform"] = req.platform
            items_dict[key] = item
    return list(items_dict.values())


def normalize_ingest_block_request(req: IngestRequest) -> List[UsageBlockItem]:
    items = []
    if not isinstance(req.ccusage_blocks_report, dict):
        return []
    blocks = req.ccusage_blocks_report.get("blocks")
    if not isinstance(blocks, list):
        return []

    source_config = {
        "source_id": req.source_id,
        "host_label": req.machine or req.host,
        "host": req.host,
        "os_user": req.os_user,
        "platform": req.platform,
    }
    for row in blocks:
        if not isinstance(row, dict) or row.get("isGap"):
            continue
        item = _block_row_to_item(source_config, row, req.timezone)
        if item is not None:
            items.append(item)
    return items


def _block_row_to_item(source: Dict[str, Any], row: Dict[str, Any], timezone_str: str) -> Optional[UsageBlockItem]:
    start_time = _block_time(row.get("startTime"), timezone_str)
    end_time = _block_time(row.get("actualEndTime") or row.get("endTime"), timezone_str)
    if not start_time or not end_time:
        return None

    token_counts = row.get("tokenCounts") if isinstance(row.get("tokenCounts"), dict) else {}
    input_tokens = int(token_counts.get("inputTokens") or row.get("inputTokens") or 0)
    output_tokens = int(token_counts.get("outputTokens") or row.get("outputTokens") or 0)
    cache_creation_tokens = int(token_counts.get("cacheCreationInputTokens") or row.get("cacheCreationTokens") or 0)
    cache_read_tokens = int(token_counts.get("cacheReadInputTokens") or row.get("cacheReadTokens") or 0)
    total_tokens = _optional_int_field(row, "totalTokens")
    if total_tokens is None:
        total_tokens = input_tokens + output_tokens + cache_creation_tokens + cache_read_tokens
    if total_tokens <= 0:
        return None

    metadata = {
        "machine": source.get("host_label") or source.get("machine") or source["source_id"],
        "host": source.get("host"),
        "account": source.get("os_user") or source.get("account") or "unknown",
        "platform": source.get("platform") or "unknown",
        "ccusage_block_row": dict(row),
    }
    return UsageBlockItem(
        source_id=source["source_id"],
        machine=metadata["machine"],
        account=metadata["account"],
        agent=row.get("agent") or "claude",
        start_time=start_time,
        end_time=end_time,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        total_tokens=total_tokens,
        total_cost=_optional_float_field(row, "costUSD"),
        metadata=metadata,
    )


def _session_row_to_hourly_item(source: Dict[str, Any], row: Dict[str, Any], hour: str) -> UsageHourlyItem:
    input_tokens = _int_field(row, "inputTokens")
    output_tokens = _int_field(row, "outputTokens")
    cache_creation_tokens = _int_field(row, "cacheCreationTokens")
    cache_read_tokens = _int_field(row, "cacheReadTokens")
    total_tokens = _optional_int_field(row, "totalTokens")
    if total_tokens is None:
        total_tokens = input_tokens + output_tokens + cache_creation_tokens + cache_read_tokens
    metadata = row.get("metadata").copy() if isinstance(row.get("metadata"), dict) else {}
    metadata["ccusage_session_row"] = dict(row)
    return UsageHourlyItem(
        source_id=source["source_id"],
        machine=source.get("host_label") or source.get("machine") or source["source_id"],
        account=source.get("os_user") or source.get("account") or "unknown",
        agent=row.get("agent") or "unknown",
        hour=hour,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        total_tokens=total_tokens,
        total_cost=_optional_float_field(row, "totalCost"),
        metadata=metadata,
    )


def _session_hour(row: Dict[str, Any], timezone_str: str) -> Optional[str]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    value = metadata.get("lastActivity")
    if not value:
        return None
    text = str(value)
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text + "T00:00:00"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        local = parsed
    else:
        tz = _zoneinfo(timezone_str)
        local = parsed.astimezone(tz) if tz else parsed.astimezone()
    return local.replace(minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def _block_time(value: Any, timezone_str: str) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        local = parsed
    else:
        tz = _zoneinfo(timezone_str)
        local = parsed.astimezone(tz) if tz else parsed.astimezone()
    return local.replace(microsecond=0).isoformat(timespec="seconds")


def _zoneinfo(timezone_str: str):
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(timezone_str)
    except Exception:
        return None


def merge_usage_items(existing_items: List[UsageItem], new_items: List[UsageItem]) -> List[UsageItem]:
    """
    将新上报的 UsageItems 与现存的 UsageItems 基于 (source_id, date, agent) 主键进行幂等合并。
    冲突时，新项覆盖旧项。
    """
    merged = {}
    for item in existing_items:
        key = (item.source_id, item.date, item.agent)
        merged[key] = item
    for item in new_items:
        key = (item.source_id, item.date, item.agent)
        merged[key] = item
    return list(merged.values())
