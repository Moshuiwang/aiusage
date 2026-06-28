from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from .snapshot_filters import metadata_from_str
from .snapshot_periods import parse_datetime


def hourly_trend(axis: list[str], rows: list[Any], block_rows: Optional[list[Any]] = None) -> Dict[str, Any]:
    by_token_type = {
        "input": {hour: 0.0 for hour in axis},
        "output": {hour: 0.0 for hour in axis},
        "cache": {hour: 0.0 for hour in axis},
    }
    points = {
        hour: {
            "date": hour,
            "hour": hour,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_tokens": 0,
            "total_tokens": 0,
        }
        for hour in axis
    }
    agent_totals: Dict[str, float] = {}
    by_agent: Dict[str, Dict[str, float]] = {}
    block_rows = dedupe_cumulative_block_rows(block_rows or [])
    block_sources = {row[0] for row in block_rows}

    for row in rows:
        source_id, hour, agent, inp, out, cc, cr, tot, _, _ = row
        if hour not in points:
            continue
        if source_id in block_sources and not is_codex_agent(agent):
            continue
        cache_tokens = cc + cr
        by_token_type["input"][hour] += inp
        by_token_type["output"][hour] += out
        by_token_type["cache"][hour] += cache_tokens
        points[hour]["input_tokens"] += inp
        points[hour]["output_tokens"] += out
        points[hour]["cache_tokens"] += cache_tokens
        points[hour]["total_tokens"] += tot
        agent_totals[agent] = agent_totals.get(agent, 0) + tot
        by_agent.setdefault(agent, {h: 0 for h in axis})
        by_agent[agent][hour] += tot

    for row in block_rows:
        add_block_to_hour_buckets(axis, row, by_token_type, points, agent_totals, by_agent)

    return {
        "period": "today",
        "granularity": "hour",
        "start_date": axis[0][:10] if axis else None,
        "end_date": axis[-1][:10] if axis else None,
        "axis": axis,
        "by_token_type": [
            {"type": "input", "label": "Input", "values": [round(by_token_type["input"].get(hour, 0)) for hour in axis]},
            {"type": "output", "label": "Output", "values": [round(by_token_type["output"].get(hour, 0)) for hour in axis]},
            {"type": "cache", "label": "Cache", "values": [round(by_token_type["cache"].get(hour, 0)) for hour in axis]},
        ],
        "points": [points[hour] for hour in axis],
        "by_agent": [
            {
                "agent": agent,
                "total_tokens": round(agent_totals.get(agent, 0)),
                "values": [round(values.get(hour, 0)) for hour in axis],
            }
            for agent, values in sorted(by_agent.items(), key=lambda item: agent_totals.get(item[0], 0), reverse=True)
        ],
    }


def fill_today_hourly_residual(
    trend: Dict[str, Any],
    ref_time: datetime,
    *,
    total_tokens: int,
    input_tokens: int,
    output_tokens: int,
    cache_tokens: int,
    excluded_daily: Optional[dict[str, int]] = None,
    excluded_hourly: Optional[dict[str, int]] = None,
) -> None:
    points = trend.get("points") or []
    axis = trend.get("axis") or []
    if not points or not axis:
        return

    excluded_daily = excluded_daily or empty_token_totals()
    excluded_hourly = excluded_hourly or empty_token_totals()
    current_total = sum(int(point.get("total_tokens") or 0) for point in points) - excluded_hourly["total"]
    residual_total = max(int(total_tokens) - excluded_daily["total"] - current_total, 0)
    token_residuals = {
        "input": max(int(input_tokens) - excluded_daily["input"] - (sum_token_type(trend, "input") - excluded_hourly["input"]), 0),
        "output": max(int(output_tokens) - excluded_daily["output"] - (sum_token_type(trend, "output") - excluded_hourly["output"]), 0),
        "cache": max(int(cache_tokens) - excluded_daily["cache"] - (sum_token_type(trend, "cache") - excluded_hourly["cache"]), 0),
    }
    if residual_total <= 0 and all(value <= 0 for value in token_residuals.values()):
        return

    ref_hour = ref_time.replace(minute=0, second=0, microsecond=0).isoformat(timespec="seconds")
    target_hour = ref_hour if ref_hour in axis else axis[-1]
    target_index = axis.index(target_hour)

    point = points[target_index]
    point["input_tokens"] = int(point.get("input_tokens") or 0) + token_residuals["input"]
    point["output_tokens"] = int(point.get("output_tokens") or 0) + token_residuals["output"]
    point["cache_tokens"] = int(point.get("cache_tokens") or 0) + token_residuals["cache"]
    point["total_tokens"] = int(point.get("total_tokens") or 0) + residual_total

    for row in trend.get("by_token_type") or []:
        token_type = row.get("type")
        if token_type not in token_residuals:
            continue
        values = row.get("values") or []
        if target_index < len(values):
            values[target_index] = values[target_index] + token_residuals[token_type]


def cap_today_hourly_to_period_totals(
    trend: Dict[str, Any],
    *,
    total_tokens: int,
    input_tokens: int,
    output_tokens: int,
    cache_tokens: int,
) -> None:
    points = trend.get("points") or []
    if not points:
        return

    point_totals = [int(point.get("total_tokens") or 0) for point in points]
    capped_totals = scale_down_ints(point_totals, int(total_tokens))
    if capped_totals != point_totals:
        for point, value in zip(points, capped_totals):
            point["total_tokens"] = value
        _scale_agent_rows(trend, int(total_tokens))

    targets = {
        "input": int(input_tokens),
        "output": int(output_tokens),
        "cache": int(cache_tokens),
    }
    point_fields = {
        "input": "input_tokens",
        "output": "output_tokens",
        "cache": "cache_tokens",
    }
    for token_type, target in targets.items():
        row = next((item for item in trend.get("by_token_type") or [] if item.get("type") == token_type), None)
        if row is None:
            continue
        values = [int(value or 0) for value in row.get("values") or []]
        capped_values = scale_down_ints(values, target)
        if capped_values == values:
            continue
        row["values"] = capped_values
        field = point_fields[token_type]
        for point, value in zip(points, capped_values):
            point[field] = value


def scale_down_ints(values: list[int], target: int) -> list[int]:
    current = sum(values)
    if current <= target or current <= 0:
        return values
    if target <= 0:
        return [0 for _ in values]

    scaled = [value * target / current for value in values]
    floors = [int(value) for value in scaled]
    remainder = target - sum(floors)
    fractions = sorted(
        ((scaled_value - floor_value, index) for index, (scaled_value, floor_value) in enumerate(zip(scaled, floors))),
        reverse=True,
    )
    for _, index in fractions[:remainder]:
        floors[index] += 1
    return floors


def _scale_agent_rows(trend: Dict[str, Any], total_tokens: int) -> None:
    for row in trend.get("by_agent") or []:
        values = [int(value or 0) for value in row.get("values") or []]
        capped_values = scale_down_ints(values, total_tokens)
        row["values"] = capped_values
        row["total_tokens"] = sum(capped_values)


def codex_hourly_context(daily_rows: list[Any], hourly_rows: list[Any]) -> dict[str, Any]:
    drift = {"status": "comparison_unavailable"}
    daily_totals = empty_token_totals()
    all_daily_totals = empty_token_totals()
    hourly_totals = empty_token_totals()

    for row in daily_rows:
        _, _, agent, inp, out, cc, cr, tot, _, _ = row
        if is_codex_agent(agent):
            target = daily_totals
        elif str(agent or "").lower() == "all":
            target = all_daily_totals
        else:
            continue
        target["input"] += int(inp or 0)
        target["output"] += int(out or 0)
        target["cache"] += int(cc or 0) + int(cr or 0)
        target["total"] += int(tot or 0)

    for row in hourly_rows:
        _, _, agent, inp, out, cc, cr, tot, _, metadata_str = row
        metadata = metadata_from_str(metadata_str)
        if not is_codex_agent(agent) or metadata.get("provenance") != "mswusage_codex_token_count":
            continue
        hourly_totals["input"] += int(inp or 0)
        hourly_totals["output"] += int(out or 0)
        hourly_totals["cache"] += int(cc or 0) + int(cr or 0)
        hourly_totals["total"] += int(tot or 0)
        if isinstance(metadata.get("drift"), dict):
            drift = dict(metadata["drift"])

    if daily_totals["total"] == 0 and drift.get("baseline_agent") == "all":
        daily_totals = all_daily_totals

    status = drift.get("status")
    return {
        "drift": drift,
        "daily": daily_totals,
        "hourly": hourly_totals,
        "skip_residual": status in {"drift_detected", "comparison_unavailable"} and hourly_totals["total"] > 0,
    }


def empty_token_totals() -> dict[str, int]:
    return {"input": 0, "output": 0, "cache": 0, "total": 0}


def sum_token_type(trend: Dict[str, Any], token_type: str) -> int:
    for row in trend.get("by_token_type") or []:
        if row.get("type") == token_type:
            return int(sum(row.get("values") or []))
    return 0


def add_block_to_hour_buckets(
    axis: list[str],
    row: Any,
    by_token_type: Dict[str, Dict[str, float]],
    points: Dict[str, Dict[str, Any]],
    agent_totals: Dict[str, float],
    by_agent: Dict[str, Dict[str, float]],
) -> None:
    _, start_time, end_time, agent, inp, out, cc, cr, tot, _, _ = row
    start = parse_datetime(start_time)
    end = parse_datetime(end_time)
    if not start or not end or end <= start:
        return
    duration = (end - start).total_seconds()
    if duration <= 0:
        return
    by_agent.setdefault(agent, {h: 0 for h in axis})
    for hour in axis:
        hour_start = parse_datetime(hour)
        if not hour_start:
            continue
        hour_end = hour_start + timedelta(hours=1)
        overlap = max(0.0, (min(end, hour_end) - max(start, hour_start)).total_seconds())
        if overlap <= 0:
            continue
        ratio = overlap / duration
        input_part = inp * ratio
        output_part = out * ratio
        cache_part = (cc + cr) * ratio
        total_part = tot * ratio
        by_token_type["input"][hour] += input_part
        by_token_type["output"][hour] += output_part
        by_token_type["cache"][hour] += cache_part
        points[hour]["input_tokens"] = round(points[hour]["input_tokens"] + input_part)
        points[hour]["output_tokens"] = round(points[hour]["output_tokens"] + output_part)
        points[hour]["cache_tokens"] = round(points[hour]["cache_tokens"] + cache_part)
        points[hour]["total_tokens"] = round(points[hour]["total_tokens"] + total_part)
        agent_totals[agent] = agent_totals.get(agent, 0) + total_part
        by_agent[agent][hour] += total_part


def dedupe_cumulative_block_rows(rows: list[Any]) -> list[Any]:
    latest_by_key: Dict[str, Any] = {}
    for row in rows:
        key = block_dedupe_key(row)
        current = latest_by_key.get(key)
        if current is None or block_row_sort_key(row) >= block_row_sort_key(current):
            latest_by_key[key] = row
    return sorted(latest_by_key.values(), key=lambda row: (str(row[1]), str(row[0]), str(row[3]), str(row[2])))


def block_dedupe_key(row: Any) -> str:
    source_id, start_time, end_time, agent = row[0], row[1], row[2], row[3]
    metadata = metadata_from_str(row[10] if len(row) > 10 else None)
    raw_block = metadata.get("ccusage_block_row") if isinstance(metadata, dict) else None
    block_id = raw_block.get("id") if isinstance(raw_block, dict) else None
    if block_id:
        return f"{source_id}\0{agent}\0{block_id}"
    return f"{source_id}\0{agent}\0{start_time}\0{end_time}"


def block_row_sort_key(row: Any) -> tuple[str, int]:
    return (str(row[2] or ""), int(row[8] or 0))


def is_codex_agent(agent: str) -> bool:
    raw = str(agent or "").lower()
    return "codex" in raw or "gpt" in raw or "openai" in raw
