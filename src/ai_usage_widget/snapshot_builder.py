from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .limits import LimitWindow

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None  # type: ignore


def build_snapshot(
    db_path: str,
    output_path: str,
    date_str: str,
    timezone_str: str,
    sources_config: Optional[List[Dict[str, Any]]] = None,
    current_time_str: Optional[str] = None,
    period: str = "today",
    machine_filter: Optional[str] = None,
    account_filter: Optional[str] = None,
) -> None:
    """
    从 SQLite canonical store 中提取指定日期的用量事实，聚合并原子输出为 latest.json 快照
    支持根据 sources_config 监控离线 (stale) 和从未上报 (never_seen) 设备
    """
    # 1. 确定当前参考时间
    tz = _zoneinfo(timezone_str)
    if current_time_str:
        ref_time = datetime.fromisoformat(current_time_str)
        if tz and ref_time.tzinfo is not None:
            ref_time = ref_time.astimezone(tz)
    else:
        ref_time = datetime.now(dt_timezone.utc).astimezone(tz)
    period_id, start_date, end_date = _period_bounds(date_str, period)
    hour_axis = _hour_axis(ref_time) if period_id == "today" else []

    if not os.path.exists(db_path):
        # 数据库不存在时，输出空白结构快照
        empty_snapshot = _empty_snapshot(
            ref_time,
            timezone_str,
            date_str,
            period_id,
            start_date,
            end_date,
            machine_filter=machine_filter,
            account_filter=account_filter,
        )
        _atomic_write(output_path, empty_snapshot)
        return

    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")

            # 查询 usage_daily 记录
            cursor = conn.execute(
                _usage_daily_sql(start_date),
                _date_params(start_date, end_date),
            )
            rows = cursor.fetchall()

            # 查询 usage_daily_models 记录，用来组合 model breakdowns
            cursor = conn.execute(
                _usage_models_sql(start_date),
                _date_params(start_date, end_date),
            )
            model_rows = cursor.fetchall()

            # 查询各 source_id 的最后一次上报状态
            cursor = conn.execute(
                """
                SELECT r.source_id, r.status, c.collected_at, r.error_message
                FROM source_reports r
                JOIN collection_runs c ON r.run_id = c.id
                WHERE r.id IN (SELECT max(id) FROM source_reports GROUP BY source_id)
                """
            )
            status_rows = cursor.fetchall()
            source_identities = _fetch_source_identities(conn)
            hourly_rows = _fetch_hourly_rows(conn, hour_axis[0], hour_axis[-1]) if hour_axis else []
            block_rows = _fetch_block_rows(conn, hour_axis[0], hour_axis[-1]) if hour_axis else []
            limits = _fetch_limit_windows(conn)
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            empty_snapshot = _empty_snapshot(
                ref_time,
                timezone_str,
                date_str,
                period_id,
                start_date,
                end_date,
                machine_filter=machine_filter,
                account_filter=account_filter,
            )
            _atomic_write(output_path, empty_snapshot)
            return
        else:
            raise exc

    rows = [row for row in rows if _daily_row_matches_filter(row, machine_filter, account_filter)]
    allowed_item_keys = {(row[0], row[1], row[2]) for row in rows}
    model_rows = [row for row in model_rows if (row[0], row[1], row[2]) in allowed_item_keys]
    hourly_rows = [row for row in hourly_rows if _timed_row_matches_filter(row, machine_filter, account_filter)]
    block_rows = [row for row in block_rows if _timed_row_matches_filter(row, machine_filter, account_filter)]

    # 2. 在内存中将 model_rows 分类归档，以便拼入 daily items
    models_by_item = {}
    for mr in model_rows:
        key = (mr[0], mr[1], mr[2])  # (source_id, date, agent)
        m_breakdown = {
            "model_name": mr[3],
            "input_tokens": mr[4],
            "output_tokens": mr[5],
            "cache_creation_tokens": mr[6],
            "cache_read_tokens": mr[7],
            "total_tokens": mr[8],
            "cost": mr[9],
        }
        models_by_item.setdefault(key, []).append(m_breakdown)

    # 3. 组装 items 并累加 summary 与 groups
    items = []
    total_tokens = 0
    input_tokens = 0
    output_tokens = 0
    cache_creation_tokens = 0
    cache_read_tokens = 0

    machine_totals: Dict[str, Dict[str, Any]] = {}
    account_totals = {}
    agent_totals = {}
    trend_dates = _date_axis(start_date, end_date, rows)
    trend_by_agent = {}
    trend_by_token_type = {
        "input": {day: 0 for day in trend_dates},
        "output": {day: 0 for day in trend_dates},
        "cache": {day: 0 for day in trend_dates},
    }
    trend_points = {
        day: {
            "date": day,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_tokens": 0,
            "total_tokens": 0,
        }
        for day in trend_dates
    }

    for row in rows:
        source_id, date, agent, inp, out, cc, cr, tot, cost, meta_str = row
        meta = {}
        if meta_str:
            try:
                meta = json.loads(meta_str)
            except Exception:
                meta = {}

        machine = meta.get("machine") or source_id
        account = meta.get("account") or "unknown"

        # 累加 summary
        total_tokens += tot
        input_tokens += inp
        output_tokens += out
        cache_creation_tokens += cc
        cache_read_tokens += cr

        # 累加 groups
        machine_entry = machine_totals.setdefault(
            machine,
            {
                "name": machine,
                "total_tokens": 0,
                "users": {},
            },
        )
        machine_entry["total_tokens"] += tot
        user_entry = machine_entry["users"].setdefault(
            account,
            {
                "account": account,
                "machine": machine,
                "total_tokens": 0,
                "source_ids": set(),
            },
        )
        user_entry["total_tokens"] += tot
        user_entry["source_ids"].add(source_id)
        account_totals[account] = account_totals.get(account, 0) + tot
        agent_totals[agent] = agent_totals.get(agent, 0) + tot
        trend_by_agent.setdefault(agent, {day: 0 for day in trend_dates})
        trend_by_agent[agent][date] = trend_by_agent[agent].get(date, 0) + tot
        cache_tokens = cc + cr
        if date in trend_by_token_type["input"]:
            trend_by_token_type["input"][date] += inp
            trend_by_token_type["output"][date] += out
            trend_by_token_type["cache"][date] += cache_tokens
            trend_points[date]["input_tokens"] += inp
            trend_points[date]["output_tokens"] += out
            trend_points[date]["cache_tokens"] += cache_tokens
            trend_points[date]["total_tokens"] += tot

        # 组合 breakdowns
        item_key = (source_id, date, agent)
        breakdowns = models_by_item.get(item_key, [])

        items.append({
            "source_id": source_id,
            "machine": machine,
            "account": account,
            "agent": agent,
            "date": date,
            "input_tokens": inp,
            "output_tokens": out,
            "cache_creation_tokens": cc,
            "cache_read_tokens": cr,
            "total_tokens": tot,
            "total_cost": cost,
            "model_breakdowns": breakdowns
        })

    # 4. 构建 groups 列表形式
    for source_id, identity in source_identities.items():
        machine = identity.get("machine") or identity.get("host") or source_id
        account = identity.get("os_user") or identity.get("account") or "unknown"
        if not _identity_matches_filter(identity, machine_filter, account_filter):
            continue
        machine_entry = machine_totals.setdefault(
            machine,
            {
                "name": machine,
                "total_tokens": 0,
                "users": {},
            },
        )
        user_entry = machine_entry["users"].setdefault(
            account,
            {
                "account": account,
                "machine": machine,
                "total_tokens": 0,
                "source_ids": set(),
            },
        )
        user_entry["source_ids"].add(source_id)

    by_machine = []
    for name, entry in machine_totals.items():
        users = []
        for user in entry["users"].values():
            source_ids = sorted(user["source_ids"])
            users.append({
                "account": user["account"],
                "machine": user["machine"],
                "display_name": f"{user['machine']} · {user['account']}",
                "total_tokens": user["total_tokens"],
                "source_ids": source_ids,
            })
        users.sort(key=lambda x: x["total_tokens"], reverse=True)
        by_machine.append({
            "name": name,
            "display_name": name,
            "total_tokens": entry["total_tokens"],
            "users": users,
        })
    by_account = [{"name": name, "total_tokens": val} for name, val in account_totals.items()]
    by_agent = [{"name": name, "total_tokens": val} for name, val in agent_totals.items()]

    by_machine.sort(key=lambda x: x["total_tokens"], reverse=True)
    by_account.sort(key=lambda x: x["total_tokens"], reverse=True)
    by_agent.sort(key=lambda x: x["total_tokens"], reverse=True)
    if period_id == "today":
        trend = _hourly_trend(hour_axis, hourly_rows, block_rows)
    else:
        trend = {
            "period": period_id,
            "granularity": "day",
            "start_date": start_date,
            "end_date": end_date,
            "axis": trend_dates,
            "by_token_type": [
                {
                    "type": "input",
                    "label": "Input",
                    "values": [trend_by_token_type["input"].get(day, 0) for day in trend_dates],
                },
                {
                    "type": "output",
                    "label": "Output",
                    "values": [trend_by_token_type["output"].get(day, 0) for day in trend_dates],
                },
                {
                    "type": "cache",
                    "label": "Cache",
                    "values": [trend_by_token_type["cache"].get(day, 0) for day in trend_dates],
                },
            ],
            "points": [trend_points[day] for day in trend_dates],
            "by_agent": [
                {
                    "agent": agent,
                    "total_tokens": agent_totals.get(agent, 0),
                    "values": [values.get(day, 0) for day in trend_dates],
                }
                for agent, values in sorted(
                    trend_by_agent.items(),
                    key=lambda item: agent_totals.get(item[0], 0),
                    reverse=True,
                )
            ],
        }

    # 5. 组装并计算 source_status 健康度与离线状态 (TP-V2-009)
    db_status = {sr[0]: {"status": sr[1], "collected_at": sr[2], "error_message": sr[3]} for sr in status_rows}
    if machine_filter or account_filter:
        db_status = {
            sid: status
            for sid, status in db_status.items()
            if _identity_matches_filter(source_identities.get(sid), machine_filter, account_filter)
        }
    source_status = []

    if sources_config:
        # 如果提供了配置文件中的 known sources 列表，我们保证遍历它们，捕获 never_seen 状态
        for src in sources_config:
            sid = src["source_id"]
            stale_threshold = int(src.get("stale_after_minutes", 120))
            if sid not in db_status:
                source_status.append(_source_status_entry({
                    "source_id": sid,
                    "status": "never_seen",
                    "observed_at": None,
                    "error_message": None,
                }, source_identities.get(sid), src))
            else:
                last_report = db_status[sid]
                collected_time = datetime.fromisoformat(last_report["collected_at"])
                # 计算离线分钟数
                diff_minutes = (ref_time - collected_time).total_seconds() / 60.0
                status_val = last_report["status"]

                if diff_minutes > stale_threshold:
                    status_val = "stale"

                source_status.append(_source_status_entry({
                    "source_id": sid,
                    "status": status_val,
                    "observed_at": last_report["collected_at"],
                    "error_message": last_report.get("error_message"),
                }, source_identities.get(sid), src))
    else:
        # 如果未提供 sources_config，直接从数据库历史记录做默认 of 120 分钟 staleness 判定
        for sid, last_report in db_status.items():
            collected_time = datetime.fromisoformat(last_report["collected_at"])
            diff_minutes = (ref_time - collected_time).total_seconds() / 60.0
            status_val = last_report["status"]

            if diff_minutes > 120:
                status_val = "stale"

            source_status.append(_source_status_entry({
                "source_id": sid,
                "status": status_val,
                "observed_at": last_report["collected_at"],
                "error_message": last_report.get("error_message"),
            }, source_identities.get(sid)))

    # 6. 组装完整快照 (v1 schema)
    snapshot = {
        "schema_version": 1,
        "generated_at": ref_time.isoformat(),
        "timezone": timezone_str,
        "summary": {
            "date": date_str,
            "period": period_id,
            "start_date": start_date,
            "end_date": end_date,
            "total_tokens": total_tokens,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_tokens": cache_creation_tokens,
            "cache_read_tokens": cache_read_tokens,
        },
        "groups": {
            "by_machine": by_machine,
            "by_account": by_account,
            "by_agent": by_agent,
        },
        "items": items,
        "trend": trend,
        "source_status": source_status,
        "limits": limits,
    }
    if machine_filter:
        snapshot["summary"]["machine"] = machine_filter
    if account_filter:
        snapshot["summary"]["account"] = account_filter

    # 7. 原子写入 latest.json
    _atomic_write(output_path, snapshot)


def _atomic_write(path: str, data: dict) -> None:
    """原子化写入 JSON 到指定路径"""
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, out_path)


def _period_bounds(date_str: str, period: str) -> tuple[str, Optional[str], str]:
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


def _usage_daily_sql(start_date: Optional[str]) -> str:
    where = "date <= ?" if start_date is None else "date >= ? AND date <= ?"
    return f"""
        SELECT source_id, date, agent, input_tokens, output_tokens,
               cache_creation_tokens, cache_read_tokens, total_tokens, total_cost, metadata_json
        FROM usage_daily
        WHERE {where}
        ORDER BY date ASC, source_id ASC, agent ASC
    """


def _usage_models_sql(start_date: Optional[str]) -> str:
    where = "date <= ?" if start_date is None else "date >= ? AND date <= ?"
    return f"""
        SELECT source_id, date, agent, model_name, input_tokens, output_tokens,
               cache_creation_tokens, cache_read_tokens, total_tokens, cost
        FROM usage_daily_models
        WHERE {where}
        ORDER BY date ASC, source_id ASC, agent ASC, model_name ASC
    """


def _date_params(start_date: Optional[str], end_date: str) -> tuple[str, ...]:
    if start_date is None:
        return (end_date,)
    return (start_date, end_date)


def _daily_row_matches_filter(row: Any, machine_filter: Optional[str], account_filter: Optional[str]) -> bool:
    metadata = _metadata_from_str(row[9] if len(row) > 9 else None)
    identity = {
        "host": metadata.get("machine") or metadata.get("host") or row[0],
        "os_user": metadata.get("account") or metadata.get("os_user") or "unknown",
    }
    return _identity_matches_filter(identity, machine_filter, account_filter)


def _timed_row_matches_filter(row: Any, machine_filter: Optional[str], account_filter: Optional[str]) -> bool:
    metadata = _metadata_from_str(row[-1] if len(row) > 0 else None)
    identity = {
        "host": metadata.get("machine") or metadata.get("host") or row[0],
        "os_user": metadata.get("account") or metadata.get("os_user") or "unknown",
    }
    return _identity_matches_filter(identity, machine_filter, account_filter)


def _identity_matches_filter(
    identity: Optional[dict[str, Any]],
    machine_filter: Optional[str],
    account_filter: Optional[str],
) -> bool:
    identity = identity or {}
    machine = str(identity.get("machine") or identity.get("host") or "")
    account = str(identity.get("os_user") or identity.get("account") or "")
    if machine_filter and machine != machine_filter:
        return False
    if account_filter and account != account_filter:
        return False
    return True


def _metadata_from_str(metadata_str: Any) -> dict[str, Any]:
    if not metadata_str:
        return {}
    try:
        metadata = json.loads(metadata_str)
    except (TypeError, json.JSONDecodeError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _fetch_source_identities(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    candidates: list[tuple[str, str, dict[str, Any]]] = []
    if _table_exists(conn, "source_identities"):
        for source_id, host, machine, os_user, platform, last_seen_at in conn.execute(
            """
            SELECT source_id, host, machine, os_user, platform, last_seen_at
            FROM source_identities
            ORDER BY last_seen_at DESC
            """
        ):
            candidates.append((str(last_seen_at or ""), str(source_id), {
                "host": host,
                "machine": machine,
                "os_user": os_user,
                "platform": platform,
            }))
    for table in ("usage_daily", "usage_hourly", "usage_blocks"):
        if not _table_exists(conn, table):
            continue
        for source_id, metadata_str, last_seen_at in conn.execute(
            f"""
            SELECT source_id, metadata_json, last_seen_at
            FROM {table}
            WHERE metadata_json IS NOT NULL
            ORDER BY last_seen_at DESC
            """
        ):
            if not metadata_str:
                continue
            try:
                metadata = json.loads(metadata_str)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(metadata, dict):
                candidates.append((str(last_seen_at or ""), str(source_id), metadata))

    identities: dict[str, dict[str, Any]] = {}
    for _, source_id, metadata in sorted(candidates, key=lambda row: (row[0], row[1]), reverse=True):
        if source_id in identities:
            continue
        identities[source_id] = {
            "host": metadata.get("host") or metadata.get("host_label"),
            "machine": metadata.get("machine") or metadata.get("host") or metadata.get("host_label"),
            "os_user": metadata.get("account") or metadata.get("os_user"),
            "platform": metadata.get("platform"),
        }
    return identities


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _fetch_limit_windows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "limit_windows"):
        return []
    rows = conn.execute(
        """
        SELECT provider, window, used_percent, remaining_percent, reset_at,
               window_duration_minutes, observed_at, source_type, confidence, status
        FROM limit_windows
        ORDER BY provider ASC, window ASC, source_type ASC
        """
    ).fetchall()
    limits = []
    for row in rows:
        limits.append(
            LimitWindow(
                provider=row[0],
                window=row[1],
                used_percent=float(row[2]),
                remaining_percent=float(row[3]),
                reset_at=row[4],
                window_duration_minutes=int(row[5]),
                observed_at=row[6],
                source_type=row[7],
                confidence=row[8],
                status=row[9],
            ).to_snapshot_dict()
        )
    return limits


def _source_status_entry(
    status: dict[str, Any],
    identity: Optional[dict[str, Any]] = None,
    source_config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    result = dict(status)
    identity = identity or {}
    source_config = source_config or {}
    host = identity.get("host") or identity.get("machine") or source_config.get("host") or source_config.get("host_label")
    os_user = identity.get("os_user") or source_config.get("os_user") or source_config.get("account")
    platform = identity.get("platform") or source_config.get("platform")

    if host:
        result["host"] = str(host)
    if os_user:
        result["os_user"] = str(os_user)
    if platform:
        result["platform"] = str(platform)
    if host and os_user:
        result["display_name"] = f"{host} · {os_user}"
    elif host:
        result["display_name"] = str(host)
    else:
        result["display_name"] = str(result.get("source_id") or "unknown-source")
    return result


def _date_axis(start_date: Optional[str], end_date: str, rows: list[Any]) -> list[str]:
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


def _hour_axis(ref_time: datetime) -> list[str]:
    end_hour = ref_time.replace(minute=0, second=0, microsecond=0)
    start_hour = end_hour - timedelta(hours=23)
    return [(start_hour + timedelta(hours=i)).isoformat(timespec="seconds") for i in range(24)]


def _fetch_hourly_rows(conn: sqlite3.Connection, start_hour: str, end_hour: str) -> list[Any]:
    try:
        return conn.execute(
            """
            SELECT source_id, hour, agent, input_tokens, output_tokens,
                   cache_creation_tokens, cache_read_tokens, total_tokens, total_cost, metadata_json
            FROM usage_hourly
            WHERE hour >= ? AND hour <= ?
            ORDER BY hour ASC, source_id ASC, agent ASC
            """,
            (start_hour, end_hour),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return []
        raise


def _fetch_block_rows(conn: sqlite3.Connection, start_hour: str, end_hour: str) -> list[Any]:
    end_exclusive_dt = _parse_datetime(end_hour)
    end_exclusive = (end_exclusive_dt + timedelta(hours=1)).isoformat(timespec="seconds") if end_exclusive_dt else end_hour
    try:
        return conn.execute(
            """
            SELECT source_id, start_time, end_time, agent, input_tokens, output_tokens,
                   cache_creation_tokens, cache_read_tokens, total_tokens, total_cost, metadata_json
            FROM usage_blocks
            WHERE start_time < ? AND end_time > ?
            ORDER BY start_time ASC, source_id ASC, agent ASC
            """,
            (end_exclusive, start_hour),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return []
        raise


def _hourly_trend(axis: list[str], rows: list[Any], block_rows: Optional[list[Any]] = None) -> Dict[str, Any]:
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
    block_rows = block_rows or []
    block_sources = {row[0] for row in block_rows}

    for row in rows:
        source_id, hour, agent, inp, out, cc, cr, tot, _, _ = row
        if hour not in points:
            continue
        if source_id in block_sources and not _is_codex_agent(agent):
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
        _add_block_to_hour_buckets(axis, row, by_token_type, points, agent_totals, by_agent)

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


def _add_block_to_hour_buckets(
    axis: list[str],
    row: Any,
    by_token_type: Dict[str, Dict[str, float]],
    points: Dict[str, Dict[str, Any]],
    agent_totals: Dict[str, float],
    by_agent: Dict[str, Dict[str, float]],
) -> None:
    _, start_time, end_time, agent, inp, out, cc, cr, tot, _, _ = row
    start = _parse_datetime(start_time)
    end = _parse_datetime(end_time)
    if not start or not end or end <= start:
        return
    duration = (end - start).total_seconds()
    if duration <= 0:
        return
    by_agent.setdefault(agent, {h: 0 for h in axis})
    for hour in axis:
        hour_start = _parse_datetime(hour)
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


def _is_codex_agent(agent: str) -> bool:
    raw = str(agent or "").lower()
    return "codex" in raw or "gpt" in raw or "openai" in raw


def _parse_datetime(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _zoneinfo(timezone_str: str):
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(timezone_str)
    except Exception:
        return None


def _empty_snapshot(
    ref_time: datetime,
    timezone_str: str,
    date_str: str,
    period_id: str,
    start_date: Optional[str],
    end_date: str,
    machine_filter: Optional[str] = None,
    account_filter: Optional[str] = None,
) -> Dict[str, Any]:
    granularity = "hour" if period_id == "today" else "day"
    axis = _hour_axis(ref_time) if granularity == "hour" else _date_axis(start_date, end_date, [])
    snapshot = {
        "schema_version": 1,
        "generated_at": ref_time.isoformat(),
        "timezone": timezone_str,
        "summary": {
            "date": date_str,
            "period": period_id,
            "start_date": start_date,
            "end_date": end_date,
            "total_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
        },
        "groups": {"by_machine": [], "by_account": [], "by_agent": []},
        "items": [],
        "trend": {
            "period": period_id,
            "granularity": granularity,
            "start_date": start_date,
            "end_date": end_date,
            "axis": axis,
            "by_token_type": [
                {"type": "input", "label": "Input", "values": [0 for _ in axis]},
                {"type": "output", "label": "Output", "values": [0 for _ in axis]},
                {"type": "cache", "label": "Cache", "values": [0 for _ in axis]},
            ],
            "points": [
                {
                    "date": day,
                    **({"hour": day} if granularity == "hour" else {}),
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_tokens": 0,
                    "total_tokens": 0,
                }
                for day in axis
            ],
            "by_agent": [],
        },
        "source_status": [],
        "limits": [],
    }
    if machine_filter:
        snapshot["summary"]["machine"] = machine_filter
    if account_filter:
        snapshot["summary"]["account"] = account_filter
    return snapshot
