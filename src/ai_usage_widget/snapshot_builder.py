from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .limits import LimitWindow
from .snapshot_filters import (
    daily_row_matches_filter,
    identity_matches_filter,
    metadata_from_str,
    timed_row_matches_filter,
)
from .snapshot_periods import date_axis, hour_axis, parse_datetime, period_bounds, zoneinfo
from .snapshot_source_health import build_source_status
from .snapshot_trends import cap_today_hourly_to_period_totals, codex_hourly_context, fill_today_hourly_residual, hourly_trend


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
    tz = zoneinfo(timezone_str)
    if current_time_str:
        ref_time = datetime.fromisoformat(current_time_str)
        if tz and ref_time.tzinfo is not None:
            ref_time = ref_time.astimezone(tz)
    else:
        ref_time = datetime.now(dt_timezone.utc).astimezone(tz)
    period_id, start_date, end_date = period_bounds(date_str, period)
    hour_axis_values = hour_axis(ref_time, end_date) if period_id == "today" else []

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
            source_accuracy = _fetch_source_accuracy(conn)
            hourly_rows = _fetch_hourly_rows(conn, hour_axis_values[0], hour_axis_values[-1]) if hour_axis_values else []
            block_rows = _fetch_block_rows(conn, hour_axis_values[0], hour_axis_values[-1]) if hour_axis_values else []
            limits = _fetch_limit_windows(
                conn,
                ref_time if period_id == "today" and end_date == ref_time.date().isoformat() else None,
            )
            account_hourly_rows = _fetch_account_hourly_rows(conn, start_date, end_date, timezone_str)
            ai_accounts = _fetch_ai_accounts(conn)
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

    rows = [row for row in rows if daily_row_matches_filter(row, machine_filter, account_filter)]
    allowed_item_keys = {(row[0], row[1], row[2]) for row in rows}
    model_rows = [row for row in model_rows if (row[0], row[1], row[2]) in allowed_item_keys]
    hourly_rows = [row for row in hourly_rows if timed_row_matches_filter(row, machine_filter, account_filter)]
    block_rows = [row for row in block_rows if timed_row_matches_filter(row, machine_filter, account_filter)]
    account_hourly_rows = [
        row for row in account_hourly_rows
        if _account_hourly_row_matches_filter(row, machine_filter, account_filter)
    ]
    ledger_daily_rows = _account_hourly_rows_to_daily_rows(account_hourly_rows, timezone_str)
    rows = _apply_ledger_daily_rows(rows, ledger_daily_rows)
    ledger_hourly_rows = _account_hourly_rows_to_hourly_rows(account_hourly_rows, timezone_str) if period_id == "today" else []
    hourly_rows = _apply_ledger_hourly_rows(hourly_rows, ledger_hourly_rows)
    allowed_item_keys = {(row[0], row[1], row[2]) for row in rows}
    model_rows = [row for row in model_rows if (row[0], row[1], row[2]) in allowed_item_keys]
    codex_hourly_context_data = codex_hourly_context(rows, hourly_rows)
    account_hourly = _account_hourly_summary(account_hourly_rows)

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
    trend_dates = date_axis(start_date, end_date, rows)
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
        if not identity_matches_filter(identity, machine_filter, account_filter):
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
        trend = hourly_trend(hour_axis_values, hourly_rows, block_rows)
        fill_today_hourly_residual(
            trend,
            ref_time,
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_tokens=cache_creation_tokens + cache_read_tokens,
            excluded_daily=codex_hourly_context_data["daily"] if codex_hourly_context_data["skip_residual"] else None,
            excluded_hourly=codex_hourly_context_data["hourly"] if codex_hourly_context_data["skip_residual"] else None,
        )
        cap_today_hourly_to_period_totals(
            trend,
            total_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_tokens=cache_creation_tokens + cache_read_tokens,
        )
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
    source_status = build_source_status(
        status_rows=status_rows,
        source_identities=source_identities,
        sources_config=sources_config,
        ref_time=ref_time,
        machine_filter=machine_filter,
        account_filter=account_filter,
        source_accuracy=source_accuracy,
    )

    # 6. 组装完整快照 (v1 schema)
    metadata = _snapshot_metadata(ref_time, limits, "origin_direct", "origin_sqlite")
    metadata["codex_hourly"] = {
        "drift": codex_hourly_context_data["drift"],
    }
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
        "account_hourly": account_hourly,
        "ai_accounts": ai_accounts,
        "metadata": metadata,
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
    tmp_path = out_path.with_name(f".{out_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, out_path)


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


def _fetch_source_accuracy(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    if not _table_exists(conn, "source_accuracy"):
        return {}
    result: dict[str, list[dict[str, Any]]] = {}
    rows = conn.execute(
        """
        SELECT source_id, agent, accuracy_status, collector_version, parser_schema_version,
               mode, lookback_hours, coverage_start, coverage_end, matching_full_scans,
               scan_complete, read_errors, unresolved_mismatch, verified_at, observed_at
        FROM source_accuracy
        ORDER BY source_id, agent
        """
    ).fetchall()
    for row in rows:
        result.setdefault(str(row[0]), []).append({
            "agent": row[1],
            "status": row[2],
            "collector_version": row[3],
            "parser_schema_version": int(row[4] or 0),
            "mode": row[5],
            "lookback_hours": row[6],
            "coverage": {"start": row[7], "end": row[8]},
            "matching_full_scans": int(row[9] or 0),
            "scan_complete": bool(row[10]),
            "read_errors": int(row[11] or 0),
            "unresolved_mismatch": int(row[12] or 0),
            "verified_at": row[13],
            "observed_at": row[14],
        })
    return result


def _fetch_limit_windows(conn: sqlite3.Connection, ref_time: datetime | None = None) -> list[dict[str, Any]]:
    if not _table_exists(conn, "limit_windows"):
        return []
    columns = {row[1] for row in conn.execute("PRAGMA table_info(limit_windows)")}
    source_expr = "source_id" if "source_id" in columns else "provider"
    rows = conn.execute(
        f"""
        SELECT {source_expr}, provider, window, used_percent, remaining_percent, reset_at,
               window_duration_minutes, observed_at, source_type, confidence, status
        FROM limit_windows
        ORDER BY {source_expr} ASC, provider ASC, window ASC, source_type ASC
        """
    ).fetchall()
    limits = []
    for row in rows:
        limits.append(
            LimitWindow(
                source_id=row[0],
                provider=row[1],
                window=row[2],
                used_percent=float(row[3]),
                remaining_percent=float(row[4]),
                reset_at=row[5],
                window_duration_minutes=int(row[6]),
                observed_at=row[7],
                source_type=row[8],
                confidence=row[9],
                status=row[10],
            ).to_snapshot_dict()
        )
    if ref_time is not None:
        limits = [
            limit for limit in limits
            if not _limit_window_expired(limit, ref_time)
        ]
    return _without_superseded_active_cache(_best_limit_windows(limits))


def _best_limit_windows(limits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    for limit in limits:
        key = (
            str(limit.get("source_id") or limit.get("provider") or ""),
            str(limit.get("provider") or ""),
            str(limit.get("window") or ""),
        )
        existing = best.get(key)
        if existing is None or _limit_rank(limit) > _limit_rank(existing):
            best[key] = limit
    return sorted(
        best.values(),
        key=lambda item: (
            str(item.get("source_id") or ""),
            str(item.get("provider") or ""),
            str(item.get("window") or ""),
        ),
    )


def _without_superseded_active_cache(limits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    effective_keys = {
        (str(limit.get("provider") or ""), str(limit.get("window") or ""))
        for limit in limits
        if _effective_limit_window(limit)
    }
    return [
        limit for limit in limits
        if str(limit.get("source_type") or "") != "active_limits_cache"
        or (str(limit.get("provider") or ""), str(limit.get("window") or "")) not in effective_keys
    ]


def _effective_limit_window(limit: dict[str, Any]) -> bool:
    return (
        bool(limit.get("official"))
        and limit.get("confidence") == "observed"
        and limit.get("status") == "ok"
        and str(limit.get("source_type") or "") != "active_limits_cache"
    )


def _snapshot_metadata(
    ref_time: datetime,
    limits: list[dict[str, Any]],
    backend_mode: str,
    canonical_store: str,
) -> dict[str, Any]:
    effective_limits = [limit for limit in limits if _effective_limit_window(limit)]
    limits_observed_at = max(
        (str(limit.get("observed_at") or "") for limit in effective_limits),
        default=None,
    )
    return {
        "backend_mode": backend_mode,
        "canonical_store": canonical_store,
        "read_model_generated_at": ref_time.isoformat(),
        "freshness_status": "ok" if effective_limits else "unknown",
        "limits_observed_at": limits_observed_at,
    }


def _limit_rank(limit: dict[str, Any]) -> tuple[int, int, str]:
    official_ok = int(
        bool(limit.get("official"))
        and limit.get("confidence") == "observed"
        and limit.get("status") == "ok"
    )
    return (
        official_ok,
        _limit_source_quality(str(limit.get("source_type") or "")),
        str(limit.get("observed_at") or ""),
    )


def _limit_source_quality(source_type: str) -> int:
    quality = {
        "oauth_usage_api": 5,
        "runtime_api": 5,
        "official_cli": 4,
        "official_cli_limit_message": 3,
        "official_cli_subscription": 2,
        "active_limits_cache": 1,
    }
    return quality.get(source_type, 0)


def _limit_window_expired(limit: dict[str, Any], ref_time: datetime) -> bool:
    reset_at = parse_datetime(str(limit.get("reset_at") or ""))
    if reset_at is None:
        return False
    if reset_at.tzinfo is not None and ref_time.tzinfo is not None:
        reset_at = reset_at.astimezone(ref_time.tzinfo)
    return reset_at <= ref_time


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
    end_exclusive_dt = parse_datetime(end_hour)
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


def _fetch_account_hourly_rows(
    conn: sqlite3.Connection,
    start_date: Optional[str],
    end_date: str,
    timezone_str: str,
) -> list[Any]:
    if not _table_exists(conn, "usage_hourly_facts"):
        return []
    rows = conn.execute(
        """
        SELECT f.fact_id, f.source_id, f.machine_id, COALESCE(m.machine_name, f.machine_id) AS machine_name,
               f.os_user, f.ai_provider, f.ai_account_id,
               COALESCE(a.account_label, f.ai_account_id) AS account_label,
               a.display_name, a.subscription, f.agent, f.client, f.window_start, f.window_end,
               f.input_tokens, f.output_tokens, f.cache_creation_tokens, f.cache_read_tokens,
               f.reasoning_output_tokens, f.total_tokens, f.event_count, f.session_count,
               f.attribution_confidence, f.provenance
        FROM usage_hourly_facts f
        LEFT JOIN machines m ON m.machine_id = f.machine_id
        LEFT JOIN ai_accounts a ON a.provider = f.ai_provider AND a.account_id = f.ai_account_id
        ORDER BY f.window_start ASC, f.source_id ASC, f.agent ASC
        """
    ).fetchall()
    return [
        row for row in rows
        if _account_hourly_row_in_period(row, start_date, end_date, timezone_str)
    ]


def _fetch_ai_accounts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _table_exists(conn, "ai_accounts"):
        return []
    rows = conn.execute(
        """
        SELECT provider, account_id, account_label, display_name, subscription, last_seen_at
        FROM ai_accounts
        ORDER BY provider ASC, account_id ASC
        """
    ).fetchall()
    return [
        {
            "provider": row[0],
            "account_id": row[1],
            "label": row[2],
            "display_name": row[3],
            "subscription": row[4],
            "last_seen_at": row[5],
        }
        for row in rows
    ]


def _account_hourly_row_in_period(
    row: Any,
    start_date: Optional[str],
    end_date: str,
    timezone_str: str,
) -> bool:
    window_start = parse_datetime(str(row[12] or ""))
    if window_start is None:
        return False
    tz = zoneinfo(timezone_str)
    local_date = window_start.astimezone(tz).date() if tz and window_start.tzinfo else window_start.date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()
    if local_date > end:
        return False
    if start_date is None:
        return True
    start = datetime.strptime(start_date, "%Y-%m-%d").date()
    return local_date >= start


def _account_hourly_row_matches_filter(row: Any, machine_filter: Optional[str], account_filter: Optional[str]) -> bool:
    machine_name = str(row[3] or row[2] or "")
    machine_id = str(row[2] or "")
    os_user = str(row[4] or "")
    if machine_filter and machine_filter not in {machine_id, machine_name}:
        return False
    if account_filter and os_user != account_filter:
        return False
    return True


def _account_hourly_rows_to_daily_rows(rows: list[Any], timezone_str: str) -> list[Any]:
    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        (
            _fact_id, source_id, _machine_id, machine_name, os_user, _ai_provider,
            _ai_account_id, _account_label, _display_name, _subscription, agent, _client,
            window_start, _window_end, inp, out, cc, cr, _reasoning, tot,
            _event_count, _session_count, _confidence, provenance,
        ) = row
        local_date = _local_date(str(window_start or ""), timezone_str)
        if local_date is None:
            continue
        key = (str(source_id), local_date, str(agent))
        bucket = buckets.setdefault(key, {
            "source_id": str(source_id),
            "date": local_date,
            "agent": str(agent),
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "total_tokens": 0,
            "machine": str(machine_name or source_id),
            "account": str(os_user or "unknown"),
            "provenances": set(),
        })
        bucket["input_tokens"] += int(inp or 0)
        bucket["output_tokens"] += int(out or 0)
        bucket["cache_creation_tokens"] += int(cc or 0)
        bucket["cache_read_tokens"] += int(cr or 0)
        bucket["total_tokens"] += int(tot or 0)
        bucket["provenances"].add(str(provenance or "usage_hourly_facts"))
    result = []
    for key in sorted(buckets):
        bucket = buckets[key]
        metadata = {
            "machine": bucket["machine"],
            "account": bucket["account"],
            "os_user": bucket["account"],
            "provenance": "usage_ledger_hourly_facts",
            "source_provenances": sorted(bucket["provenances"]),
        }
        result.append((
            bucket["source_id"],
            bucket["date"],
            bucket["agent"],
            bucket["input_tokens"],
            bucket["output_tokens"],
            bucket["cache_creation_tokens"],
            bucket["cache_read_tokens"],
            bucket["total_tokens"],
            None,
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        ))
    return result


def _account_hourly_rows_to_hourly_rows(rows: list[Any], timezone_str: str) -> list[Any]:
    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        (
            _fact_id, source_id, _machine_id, machine_name, os_user, _ai_provider,
            _ai_account_id, _account_label, _display_name, _subscription, agent, _client,
            window_start, _window_end, inp, out, cc, cr, _reasoning, tot,
            _event_count, _session_count, _confidence, provenance,
        ) = row
        hour = _local_hour(str(window_start or ""), timezone_str)
        if hour is None:
            continue
        key = (str(source_id), hour, str(agent))
        bucket = buckets.setdefault(key, {
            "source_id": str(source_id),
            "hour": hour,
            "agent": str(agent),
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "total_tokens": 0,
            "machine": str(machine_name or source_id),
            "account": str(os_user or "unknown"),
            "provenances": set(),
        })
        bucket["input_tokens"] += int(inp or 0)
        bucket["output_tokens"] += int(out or 0)
        bucket["cache_creation_tokens"] += int(cc or 0)
        bucket["cache_read_tokens"] += int(cr or 0)
        bucket["total_tokens"] += int(tot or 0)
        bucket["provenances"].add(str(provenance or "usage_hourly_facts"))
    result = []
    for key in sorted(buckets):
        bucket = buckets[key]
        metadata = {
            "machine": bucket["machine"],
            "account": bucket["account"],
            "os_user": bucket["account"],
            "provenance": "usage_ledger_hourly_facts",
            "source_provenances": sorted(bucket["provenances"]),
        }
        result.append((
            bucket["source_id"],
            bucket["hour"],
            bucket["agent"],
            bucket["input_tokens"],
            bucket["output_tokens"],
            bucket["cache_creation_tokens"],
            bucket["cache_read_tokens"],
            bucket["total_tokens"],
            None,
            json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        ))
    return result


def _apply_ledger_daily_rows(rows: list[Any], ledger_rows: list[Any]) -> list[Any]:
    if not ledger_rows:
        return rows
    cost_by_key = {(row[0], row[1], row[2]): row[8] for row in rows if row[8] is not None}
    ledger_rows = [
        (
            *row[:8],
            cost_by_key.get((row[0], row[1], row[2]), row[8]),
            row[9],
        )
        for row in ledger_rows
    ]
    ledger_keys = {(row[0], row[1], row[2]) for row in ledger_rows}
    ledger_totals_by_source_date: dict[tuple[Any, Any], dict[str, int]] = {}
    for row in ledger_rows:
        key = (row[0], row[1])
        totals = ledger_totals_by_source_date.setdefault(
            key,
            {"input": 0, "output": 0, "cache_creation": 0, "cache_read": 0, "total": 0},
        )
        totals["input"] += int(row[3] or 0)
        totals["output"] += int(row[4] or 0)
        totals["cache_creation"] += int(row[5] or 0)
        totals["cache_read"] += int(row[6] or 0)
        totals["total"] += int(row[7] or 0)
    kept = []
    for row in rows:
        key = (row[0], row[1], row[2])
        if key in ledger_keys:
            continue
        source_date = (row[0], row[1])
        if str(row[2] or "").lower() == "all" and source_date in ledger_totals_by_source_date:
            residual = _daily_all_residual_row(row, ledger_totals_by_source_date[source_date])
            if residual is not None:
                kept.append(residual)
            continue
        kept.append(row)
    return sorted([*kept, *ledger_rows], key=lambda row: (row[1], row[0], row[2]))


def _daily_all_residual_row(row: Any, ledger_totals: dict[str, int]) -> Any | None:
    old_total = int(row[7] or 0)
    residual_total = max(old_total - int(ledger_totals.get("total") or 0), 0)
    residual_input = max(int(row[3] or 0) - int(ledger_totals.get("input") or 0), 0)
    residual_output = max(int(row[4] or 0) - int(ledger_totals.get("output") or 0), 0)
    residual_cache_creation = max(int(row[5] or 0) - int(ledger_totals.get("cache_creation") or 0), 0)
    residual_cache_read = max(int(row[6] or 0) - int(ledger_totals.get("cache_read") or 0), 0)
    if residual_total <= 0 and not any([residual_input, residual_output, residual_cache_creation, residual_cache_read]):
        return None
    residual_cost = row[8]
    if residual_cost is not None and old_total > 0:
        residual_cost = float(residual_cost) * (residual_total / old_total)
    metadata = _metadata_json_with_provenance(row[9], "usage_daily_residual_after_ledger")
    return (
        row[0],
        row[1],
        row[2],
        residual_input,
        residual_output,
        residual_cache_creation,
        residual_cache_read,
        residual_total,
        residual_cost,
        metadata,
    )


def _metadata_json_with_provenance(raw: Any, provenance: str) -> str:
    metadata: dict[str, Any] = {}
    if raw:
        try:
            loaded = json.loads(raw)
            if isinstance(loaded, dict):
                metadata.update(loaded)
        except (TypeError, json.JSONDecodeError):
            metadata = {}
    metadata.setdefault("provenance", provenance)
    metadata["residual_provenance"] = provenance
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True)


def _apply_ledger_hourly_rows(rows: list[Any], ledger_rows: list[Any]) -> list[Any]:
    if not ledger_rows:
        return rows
    ledger_keys = {(row[0], row[1], row[2]) for row in ledger_rows}
    kept = [row for row in rows if (row[0], row[1], row[2]) not in ledger_keys]
    return sorted([*kept, *ledger_rows], key=lambda row: (row[1], row[0], row[2]))


def _local_date(value: str, timezone_str: str) -> str | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    tz = zoneinfo(timezone_str)
    if tz and parsed.tzinfo:
        parsed = parsed.astimezone(tz)
    return parsed.date().isoformat()


def _local_hour(value: str, timezone_str: str) -> str | None:
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    tz = zoneinfo(timezone_str)
    if tz and parsed.tzinfo:
        parsed = parsed.astimezone(tz)
    return parsed.replace(minute=0, second=0, microsecond=0).isoformat(timespec="seconds")


def _account_hourly_summary(rows: list[Any]) -> dict[str, Any]:
    if not rows:
        return _empty_account_hourly_summary()
    total_tokens = 0
    by_ai_account: dict[str, dict[str, Any]] = {}
    by_machine: dict[str, dict[str, Any]] = {}
    by_os_user: dict[str, dict[str, Any]] = {}
    by_agent: dict[str, int] = {}
    by_confidence: dict[str, int] = {}

    for row in rows:
        (
            _fact_id, source_id, machine_id, machine_name, os_user, ai_provider,
            ai_account_id, account_label, display_name, subscription, agent, _client,
            _window_start, _window_end, inp, out, cc, cr, reasoning, tot,
            _event_count, _session_count, confidence, _provenance,
        ) = row
        tokens = int(tot or 0)
        total_tokens += tokens
        account_key = f"{ai_provider}:{ai_account_id}"
        account_entry = by_ai_account.setdefault(account_key, {
            "provider": ai_provider,
            "account_id": ai_account_id,
            "label": account_label,
            "display_name": display_name,
            "subscription": subscription,
            "total_tokens": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_tokens": 0,
            "reasoning_output_tokens": 0,
            "confidence": {},
            "source_ids": set(),
        })
        account_entry["total_tokens"] += tokens
        account_entry["input_tokens"] += int(inp or 0)
        account_entry["output_tokens"] += int(out or 0)
        account_entry["cache_tokens"] += int(cc or 0) + int(cr or 0)
        account_entry["reasoning_output_tokens"] += int(reasoning or 0)
        confidence_key = str(confidence)
        account_entry["confidence"][confidence_key] = account_entry["confidence"].get(confidence_key, 0) + tokens
        account_entry["source_ids"].add(source_id)

        machine_entry = by_machine.setdefault(machine_id, {
            "machine_id": machine_id,
            "machine_name": machine_name,
            "total_tokens": 0,
        })
        machine_entry["total_tokens"] += tokens

        user_key = f"{machine_id}:{os_user}"
        user_entry = by_os_user.setdefault(user_key, {
            "machine_id": machine_id,
            "machine_name": machine_name,
            "os_user": os_user,
            "display_name": f"{machine_name} · {os_user}",
            "total_tokens": 0,
        })
        user_entry["total_tokens"] += tokens

        by_agent[str(agent)] = by_agent.get(str(agent), 0) + tokens
        by_confidence[str(confidence)] = by_confidence.get(str(confidence), 0) + tokens

    accounts = []
    for entry in by_ai_account.values():
        normalized = dict(entry)
        confidence = normalized.pop("confidence")
        confidence_breakdown = [
            {"confidence": name, "total_tokens": value}
            for name, value in sorted(confidence.items(), key=lambda item: item[1], reverse=True)
        ]
        normalized["confidence_breakdown"] = confidence_breakdown
        normalized["attribution_confidence"] = (
            confidence_breakdown[0]["confidence"]
            if len(confidence_breakdown) == 1
            else "mixed"
        )
        normalized["source_ids"] = sorted(normalized["source_ids"])
        accounts.append(normalized)

    return {
        "total_tokens": total_tokens,
        "facts": len(rows),
        "by_ai_account": sorted(accounts, key=lambda item: item["total_tokens"], reverse=True),
        "by_machine": sorted(by_machine.values(), key=lambda item: item["total_tokens"], reverse=True),
        "by_os_user": sorted(by_os_user.values(), key=lambda item: item["total_tokens"], reverse=True),
        "by_agent": [
            {"name": name, "total_tokens": tokens}
            for name, tokens in sorted(by_agent.items(), key=lambda item: item[1], reverse=True)
        ],
        "confidence_breakdown": [
            {"confidence": confidence, "total_tokens": tokens}
            for confidence, tokens in sorted(by_confidence.items(), key=lambda item: item[1], reverse=True)
        ],
    }


def _empty_account_hourly_summary() -> dict[str, Any]:
    return {
        "total_tokens": 0,
        "facts": 0,
        "by_ai_account": [],
        "by_machine": [],
        "by_os_user": [],
        "by_agent": [],
        "confidence_breakdown": [],
    }


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
    axis = hour_axis(ref_time, end_date) if granularity == "hour" else date_axis(start_date, end_date, [])
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
        "account_hourly": _empty_account_hourly_summary(),
        "ai_accounts": [],
        "metadata": {
            **_snapshot_metadata(ref_time, [], "origin_direct", "origin_sqlite"),
            "codex_hourly": {
                "drift": {"status": "comparison_unavailable"},
            },
        },
    }
    if machine_filter:
        snapshot["summary"]["machine"] = machine_filter
    if account_filter:
        snapshot["summary"]["account"] = account_filter
    return snapshot
