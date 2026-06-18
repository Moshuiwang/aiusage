from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

from ai_usage_widget.limits import LimitWindow
from ai_usage_widget.models import UsageBlockItem, UsageHourlyFact, UsageHourlyItem, UsageItem
from ai_usage_widget.storage_sqlite import write_limit_windows, write_sqlite
from ai_usage_widget.snapshot_builder import build_snapshot


class TestSnapshotBuilder(unittest.TestCase):
    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        self.out_fd, self.out_path = tempfile.mkstemp(suffix=".json")
        self.date_str = "2026-06-01"
        self.timezone_str = "Asia/Shanghai"

        # 模拟写入两条数据：
        # 1. mac-local 设备的 claude
        # 2. linux-server 设备的 codex
        self.items = [
            UsageItem(
                source_id="mac-local",
                machine="macbook",
                account="wang",
                agent="claude",
                date=self.date_str,
                input_tokens=1000,
                output_tokens=500,
                cache_creation_tokens=100,
                cache_read_tokens=200,
                total_tokens=1800,
                total_cost=0.05,
                metadata={"machine": "macbook", "account": "wang"},
                model_breakdowns=[]
            ),
            UsageItem(
                source_id="linux-server",
                machine="ubuntu-node",
                account="root",
                agent="codex",
                date=self.date_str,
                input_tokens=2000,
                output_tokens=1000,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                total_tokens=3000,
                total_cost=0.08,
                metadata={"machine": "ubuntu-node", "account": "root"},
                model_breakdowns=[]
            )
        ]

        # 模拟上报状态数据
        self.source_reports = [
            {
                "source_id": "mac-local",
                "report_type": "daily",
                "command": "ccusage daily --json",
                "status": "ok",
                "error_type": None,
                "error_message": None
            },
            {
                "source_id": "linux-server",
                "report_type": "daily",
                "command": "ccusage daily --json",
                "status": "command_failed",
                "error_type": "timeout",
                "error_message": "command timed out"
            }
        ]

    def tearDown(self) -> None:
        os.close(self.db_fd)
        os.close(self.out_fd)
        for p in [self.db_path, self.out_path]:
            if os.path.exists(p):
                os.remove(p)

    def test_build_snapshot_success(self) -> None:
        """测试从 SQLite 数据库提取数据并正确生成 latest.json 快照"""
        # 写入测试数据到数据库
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-01T10:50:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=self.source_reports,
            items=self.items
        )

        # 生成快照
        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str=self.date_str,
            timezone_str=self.timezone_str,
            current_time_str="2026-06-01T10:55:00+08:00",
        )

        self.assertTrue(os.path.exists(self.out_path))

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        # 1. 检验基本元数据
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(snapshot["timezone"], self.timezone_str)

        # 2. 检验 Summary (累加 1800 + 3000 = 4800)
        summary = snapshot["summary"]
        self.assertEqual(summary["date"], self.date_str)
        self.assertEqual(summary["total_tokens"], 4800)
        self.assertEqual(summary["input_tokens"], 3000)
        self.assertEqual(summary["output_tokens"], 1500)

        # 3. 检验 Groups 聚合结果
        groups = snapshot["groups"]
        # by_machine
        self.assertEqual(len(groups["by_machine"]), 2)
        mac_group = next(g for g in groups["by_machine"] if g["name"] == "macbook")
        self.assertEqual(mac_group["total_tokens"], 1800)

        # by_agent
        self.assertEqual(len(groups["by_agent"]), 2)
        claude_group = next(g for g in groups["by_agent"] if g["name"] == "claude")
        self.assertEqual(claude_group["total_tokens"], 1800)

        # 4. 检验 source_status
        source_status = snapshot["source_status"]
        self.assertEqual(len(source_status), 2)
        mac_status = next(s for s in source_status if s["source_id"] == "mac-local")
        self.assertEqual(mac_status["status"], "ok")

        linux_status = next(s for s in source_status if s["source_id"] == "linux-server")
        self.assertEqual(linux_status["status"], "command_failed")
        self.assertEqual(linux_status["error_message"], "command timed out")
        self.assertEqual(snapshot["limits"], [])
        self.assertEqual(snapshot["account_hourly"]["total_tokens"], 0)

    def test_build_snapshot_includes_account_hourly_summary_without_changing_daily_total(self) -> None:
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-11T14:30:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=[],
            items=[
                UsageItem(
                    source_id="mac-local",
                    machine="MacBook Pro",
                    account="wangzhipeng",
                    agent="codex",
                    date="2026-06-11",
                    input_tokens=10,
                    output_tokens=5,
                    cache_creation_tokens=0,
                    cache_read_tokens=5,
                    total_tokens=20,
                    metadata={"machine": "MacBook Pro", "account": "wangzhipeng"},
                )
            ],
            hourly_facts=[
                UsageHourlyFact(
                    fact_id="codex:codex:mac-local:2026-06-11T13:00:00+08:00:2026-06-11T14:00:00+08:00:account_observed_usage_inferred:openai:acct-main:codex_token_events",
                    source_id="mac-local",
                    machine_id="macbook-pro-local",
                    machine_name="MacBook Pro",
                    host="macbook-pro.local",
                    os_user="wangzhipeng",
                    platform="darwin",
                    ai_provider="openai",
                    ai_account_id="acct-main",
                    ai_account_label="start@example.com",
                    ai_account_display_name="StarTimes",
                    ai_account_subscription=None,
                    agent="codex",
                    client="codex",
                    window_start="2026-06-11T13:00:00+08:00",
                    window_end="2026-06-11T14:00:00+08:00",
                    timezone="Asia/Shanghai",
                    input_tokens=100,
                    output_tokens=20,
                    cache_creation_tokens=0,
                    cache_read_tokens=30,
                    reasoning_output_tokens=5,
                    total_tokens=155,
                    event_count=2,
                    session_count=1,
                    attribution_confidence="account_observed_usage_inferred",
                    provenance="codex_token_events",
                )
            ],
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str="2026-06-11",
            timezone_str=self.timezone_str,
            current_time_str="2026-06-11T14:55:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        self.assertEqual(snapshot["summary"]["total_tokens"], 20)
        account_hourly = snapshot["account_hourly"]
        self.assertEqual(account_hourly["total_tokens"], 155)
        self.assertEqual(account_hourly["facts"], 1)
        self.assertEqual(account_hourly["by_ai_account"][0]["label"], "start@example.com")
        self.assertEqual(account_hourly["by_ai_account"][0]["attribution_confidence"], "account_observed_usage_inferred")
        self.assertEqual(
            account_hourly["by_ai_account"][0]["confidence_breakdown"],
            [{"confidence": "account_observed_usage_inferred", "total_tokens": 155}],
        )
        self.assertEqual(account_hourly["by_os_user"][0]["os_user"], "wangzhipeng")
        self.assertEqual(account_hourly["confidence_breakdown"][0]["confidence"], "account_observed_usage_inferred")

    def test_account_hourly_mixed_confidence_is_visible_per_account(self) -> None:
        facts = []
        for fact_id, confidence, total in [
            ("fact-observed", "observed", 100),
            ("fact-inferred", "account_observed_usage_inferred", 55),
        ]:
            facts.append(
                UsageHourlyFact(
                    fact_id=fact_id,
                    source_id="mac-local",
                    machine_id="macbook-pro-local",
                    machine_name="MacBook Pro",
                    host="macbook-pro.local",
                    os_user="wangzhipeng",
                    platform="darwin",
                    ai_provider="openai",
                    ai_account_id="acct-main",
                    ai_account_label="start@example.com",
                    ai_account_display_name=None,
                    ai_account_subscription=None,
                    agent="codex",
                    client="codex",
                    window_start=f"2026-06-11T{13 if fact_id == 'fact-observed' else 14}:00:00+08:00",
                    window_end=f"2026-06-11T{14 if fact_id == 'fact-observed' else 15}:00:00+08:00",
                    timezone="Asia/Shanghai",
                    input_tokens=total,
                    output_tokens=0,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                    reasoning_output_tokens=0,
                    total_tokens=total,
                    attribution_confidence=confidence,
                    provenance="codex_token_events",
                )
            )
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-11T15:30:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=[],
            items=[],
            hourly_facts=facts,
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str="2026-06-11",
            timezone_str=self.timezone_str,
            current_time_str="2026-06-11T15:55:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        account = snapshot["account_hourly"]["by_ai_account"][0]
        self.assertEqual(account["total_tokens"], 155)
        self.assertEqual(account["attribution_confidence"], "mixed")
        self.assertEqual(
            account["confidence_breakdown"],
            [
                {"confidence": "observed", "total_tokens": 100},
                {"confidence": "account_observed_usage_inferred", "total_tokens": 55},
            ],
        )

    def test_account_hourly_period_filter_uses_configured_timezone(self) -> None:
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-11T01:30:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=[],
            items=[],
            hourly_facts=[
                UsageHourlyFact(
                    fact_id="utc-previous-day-local-current-day",
                    source_id="linux-dev",
                    machine_id="linux-dev",
                    machine_name="linux-dev",
                    host="linux-dev",
                    os_user="wang",
                    platform="linux",
                    ai_provider="openai",
                    ai_account_id="acct-main",
                    ai_account_label="start@example.com",
                    ai_account_display_name=None,
                    ai_account_subscription=None,
                    agent="codex",
                    client="codex",
                    window_start="2026-06-10T17:00:00+00:00",
                    window_end="2026-06-10T18:00:00+00:00",
                    timezone="UTC",
                    input_tokens=155,
                    output_tokens=0,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                    reasoning_output_tokens=0,
                    total_tokens=155,
                    attribution_confidence="account_observed_usage_inferred",
                    provenance="codex_token_events",
                )
            ],
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str="2026-06-11",
            timezone_str=self.timezone_str,
            current_time_str="2026-06-11T01:30:00+08:00",
        )
        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)
        self.assertEqual(snapshot["account_hourly"]["total_tokens"], 155)

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str="2026-06-10",
            timezone_str=self.timezone_str,
            current_time_str="2026-06-10T23:30:00+08:00",
        )
        with open(self.out_path, "r", encoding="utf-8") as f:
            previous_day = json.load(f)
        self.assertEqual(previous_day["account_hourly"]["total_tokens"], 0)

    def test_build_snapshot_includes_observed_limits(self) -> None:
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-01T10:50:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=self.source_reports,
            items=self.items,
        )
        write_limit_windows(
            self.db_path,
            [
                LimitWindow(
                    provider="codex",
                    window="session",
                    used_percent=41.2,
                    remaining_percent=58.8,
                    reset_at="2026-06-01T14:00:00+08:00",
                    window_duration_minutes=300,
                    observed_at="2026-06-01T10:45:00+08:00",
                    source_type="runtime_api",
                    confidence="observed",
                    status="ok",
                ),
                LimitWindow(
                    provider="claude",
                    window="week",
                    used_percent=31.5,
                    remaining_percent=68.5,
                    reset_at="2026-06-09T00:00:00+08:00",
                    window_duration_minutes=10080,
                    observed_at="2026-06-01T10:46:00+08:00",
                    source_type="oauth_usage_api",
                    confidence="observed",
                    status="ok",
                ),
            ],
            seen_at="2026-06-01T10:46:00+08:00",
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str=self.date_str,
            timezone_str=self.timezone_str,
            current_time_str="2026-06-01T10:55:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        self.assertEqual(
            [(row["provider"], row["window"], row["reset_at"]) for row in snapshot["limits"]],
            [
                ("claude", "week", "2026-06-09T00:00:00+08:00"),
                ("codex", "session", "2026-06-01T14:00:00+08:00"),
            ],
        )
        self.assertEqual(snapshot["limits"][0]["source_type"], "oauth_usage_api")
        self.assertEqual(snapshot["limits"][0]["confidence"], "observed")
        self.assertTrue(snapshot["limits"][0]["official"])

    def test_build_snapshot_keeps_multi_account_limits(self) -> None:
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-01T10:50:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=self.source_reports,
            items=self.items,
        )
        write_limit_windows(
            self.db_path,
            [
                LimitWindow(
                    provider="claude",
                    source_id="claude-main",
                    window="session",
                    used_percent=20.0,
                    remaining_percent=80.0,
                    reset_at="2026-06-01T14:00:00+08:00",
                    window_duration_minutes=300,
                    observed_at="2026-06-01T10:45:00+08:00",
                    source_type="official_cli",
                    confidence="observed",
                    status="ok",
                ),
                LimitWindow(
                    provider="claude",
                    source_id="claude-w",
                    window="session",
                    used_percent=50.0,
                    remaining_percent=50.0,
                    reset_at="2026-06-01T15:00:00+08:00",
                    window_duration_minutes=300,
                    observed_at="2026-06-01T10:46:00+08:00",
                    source_type="official_cli",
                    confidence="observed",
                    status="ok",
                ),
            ],
            seen_at="2026-06-01T10:46:00+08:00",
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str=self.date_str,
            timezone_str=self.timezone_str,
            current_time_str="2026-06-01T10:55:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        self.assertEqual(
            [(row["source_id"], row["provider"], row["window"], row["used_percent"]) for row in snapshot["limits"]],
            [
                ("claude-main", "claude", "session", 20.0),
                ("claude-w", "claude", "session", 50.0),
            ],
        )

    def test_failed_limits_do_not_break_usage_summary(self) -> None:
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-01T10:50:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=self.source_reports,
            items=self.items,
        )
        write_limit_windows(
            self.db_path,
            [
                LimitWindow(
                    provider="claude",
                    window="session",
                    used_percent=0,
                    remaining_percent=0,
                    reset_at="2026-06-01T10:46:00+08:00",
                    window_duration_minutes=300,
                    observed_at="2026-06-01T10:46:00+08:00",
                    source_type="oauth_usage_api",
                    confidence="missing",
                    status="provider_failed",
                ),
            ],
            seen_at="2026-06-01T10:46:00+08:00",
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str=self.date_str,
            timezone_str=self.timezone_str,
            current_time_str="2026-06-01T10:55:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        self.assertEqual(snapshot["summary"]["total_tokens"], 4800)
        self.assertEqual(snapshot["limits"][0]["status"], "provider_failed")
        self.assertEqual(snapshot["limits"][0]["confidence"], "missing")
        self.assertFalse(snapshot["limits"][0]["official"])

    def test_source_health_staleness_and_never_seen(self) -> None:
        """验证 Source 离线变 Stale、未上报变 Never Seen 以及今日 0 用量但在线的区别"""
        # 配置 known sources
        sources_config = [
            {"source_id": "mac-local", "stale_after_minutes": 60},     # 60分钟无数据变 stale
            {"source_id": "linux-server", "stale_after_minutes": 120},
            {"source_id": "windows-desktop", "stale_after_minutes": 120}  # 从未上报过的机器
        ]

        # 写入历史数据：
        # 1. mac-local 上报在 2小时前 ( staled )
        # 2. linux-server 在 10分钟前上报，且无今日用量 ( 0 usage but ok )
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-01T08:00:00+08:00",  # mac-local 在 8:00 上报
            timezone=self.timezone_str,
            run_status="success",
            source_reports=[
                {
                    "source_id": "mac-local",
                    "report_type": "daily",
                    "command": "ccusage daily --json",
                    "status": "ok",
                    "error_type": None,
                    "error_message": None
                }
            ],
            items=[]
        )

        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-01T10:40:00+08:00",  # linux-server 在 10:40 上报
            timezone=self.timezone_str,
            run_status="success",
            source_reports=[
                {
                    "source_id": "linux-server",
                    "report_type": "daily",
                    "command": "ccusage daily --json",
                    "status": "ok",
                    "error_type": None,
                    "error_message": None
                }
            ],
            items=[]
        )

        # 设定生成时间为 2026-06-01 10:50
        # 此时 mac-local 距离上报过去了 170 分钟，远超 60 分钟限额 -> 应判定为 stale
        # linux-server 距离上报仅过去了 10 分钟，且无 items -> 应判定为 ok
        # windows-desktop 没有任何上报 -> 应判定为 never_seen
        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str=self.date_str,
            timezone_str=self.timezone_str,
            sources_config=sources_config,
            current_time_str="2026-06-01T10:50:00+08:00"  # 传入固定时间进行测试
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        status_list = snapshot["source_status"]
        self.assertEqual(len(status_list), 3)

        mac_status = next(s for s in status_list if s["source_id"] == "mac-local")
        self.assertEqual(mac_status["status"], "stale")

        linux_status = next(s for s in status_list if s["source_id"] == "linux-server")
        self.assertEqual(linux_status["status"], "ok")

        win_status = next(s for s in status_list if s["source_id"] == "windows-desktop")
        self.assertEqual(win_status["status"], "never_seen")

    def test_build_snapshot_week_period_aggregates_date_range(self) -> None:
        """验证 week period 按真实日期范围聚合，并输出真实趋势序列"""
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-01T10:50:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=self.source_reports,
            items=[
                UsageItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="claude",
                    date="2026-06-01",
                    input_tokens=100,
                    output_tokens=50,
                    cache_creation_tokens=0,
                    cache_read_tokens=20,
                    total_tokens=170,
                    metadata={"machine": "macbook", "account": "wang"},
                    model_breakdowns=[{
                        "model_name": "claude-opus",
                        "input_tokens": 100,
                        "output_tokens": 50,
                        "cache_creation_tokens": 0,
                        "cache_read_tokens": 20,
                        "total_tokens": 170,
                        "cost": None,
                    }],
                ),
                UsageItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="claude",
                    date="2026-06-02",
                    input_tokens=200,
                    output_tokens=50,
                    cache_creation_tokens=0,
                    cache_read_tokens=30,
                    total_tokens=280,
                    metadata={"machine": "macbook", "account": "wang"},
                    model_breakdowns=[{
                        "model_name": "claude-opus",
                        "input_tokens": 200,
                        "output_tokens": 50,
                        "cache_creation_tokens": 0,
                        "cache_read_tokens": 30,
                        "total_tokens": 280,
                        "cost": None,
                    }],
                ),
                UsageItem(
                    source_id="linux-server",
                    machine="biai",
                    account="root",
                    agent="codex",
                    date="2026-05-31",
                    input_tokens=999,
                    output_tokens=1,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                    total_tokens=1000,
                    metadata={"machine": "biai", "account": "root"},
                    model_breakdowns=[],
                ),
            ],
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str="2026-06-02",
            timezone_str=self.timezone_str,
            period="week",
            current_time_str="2026-06-02T10:55:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        self.assertEqual(snapshot["summary"]["period"], "week")
        self.assertEqual(snapshot["summary"]["start_date"], "2026-05-27")
        self.assertEqual(snapshot["summary"]["end_date"], "2026-06-02")
        self.assertEqual(snapshot["summary"]["total_tokens"], 1450)
        self.assertEqual(snapshot["groups"]["by_agent"], [
            {"name": "codex", "total_tokens": 1000},
            {"name": "claude", "total_tokens": 450},
        ])
        self.assertEqual(snapshot["trend"]["axis"], [
            "2026-05-27",
            "2026-05-28",
            "2026-05-29",
            "2026-05-30",
            "2026-05-31",
            "2026-06-01",
            "2026-06-02",
        ])
        codex_trend = next(row for row in snapshot["trend"]["by_agent"] if row["agent"] == "codex")
        claude_trend = next(row for row in snapshot["trend"]["by_agent"] if row["agent"] == "claude")
        self.assertEqual(codex_trend["values"], [0, 0, 0, 0, 1000, 0, 0])
        self.assertEqual(claude_trend["values"], [0, 0, 0, 0, 0, 170, 280])
        token_types = {row["type"]: row["values"] for row in snapshot["trend"]["by_token_type"]}
        self.assertEqual(token_types["input"], [0, 0, 0, 0, 999, 100, 200])
        self.assertEqual(token_types["output"], [0, 0, 0, 0, 1, 50, 50])
        self.assertEqual(token_types["cache"], [0, 0, 0, 0, 0, 20, 30])
        self.assertEqual(snapshot["trend"]["points"][-1], {
            "date": "2026-06-02",
            "input_tokens": 200,
            "output_tokens": 50,
            "cache_tokens": 30,
            "total_tokens": 280,
        })

    def test_today_period_uses_calendar_day_hourly_trend(self) -> None:
        """验证 today 周期趋势图使用所选日期 00:00-23:00 的小时级事实"""
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-01T11:35:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=self.source_reports,
            items=self.items,
            hourly_items=[
                UsageHourlyItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="claude",
                    hour="2026-06-01T09:00:00+08:00",
                    input_tokens=100,
                    output_tokens=20,
                    cache_creation_tokens=0,
                    cache_read_tokens=30,
                    total_tokens=150,
                    metadata={"machine": "macbook", "account": "wang"},
                ),
                UsageHourlyItem(
                    source_id="linux-server",
                    machine="ubuntu-node",
                    account="root",
                    agent="codex",
                    hour="2026-06-01T10:00:00+08:00",
                    input_tokens=80,
                    output_tokens=40,
                    cache_creation_tokens=5,
                    cache_read_tokens=15,
                    total_tokens=140,
                    metadata={"machine": "ubuntu-node", "account": "root"},
                ),
            ],
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str=self.date_str,
            timezone_str=self.timezone_str,
            period="today",
            current_time_str="2026-06-01T11:35:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        self.assertEqual(snapshot["trend"]["granularity"], "hour")
        self.assertEqual(len(snapshot["trend"]["axis"]), 24)
        self.assertEqual(snapshot["trend"]["axis"][0], "2026-06-01T00:00:00+08:00")
        self.assertEqual(snapshot["trend"]["axis"][-1], "2026-06-01T23:00:00+08:00")
        token_types = {row["type"]: row["values"] for row in snapshot["trend"]["by_token_type"]}
        self.assertEqual(token_types["input"][9:11], [100, 80])
        self.assertEqual(token_types["output"][9:11], [20, 40])
        self.assertEqual(token_types["cache"][9:11], [30, 20])
        self.assertEqual(snapshot["trend"]["points"][9]["hour"], "2026-06-01T09:00:00+08:00")
        self.assertEqual(snapshot["trend"]["points"][9]["total_tokens"], 150)
        self.assertEqual(
            sum(point["total_tokens"] for point in snapshot["trend"]["points"]),
            snapshot["summary"]["total_tokens"],
        )
        self.assertEqual(
            snapshot["trend"]["points"][11]["total_tokens"],
            snapshot["summary"]["total_tokens"] - 150 - 140,
        )

    def test_today_period_spreads_ccusage_blocks_across_overlapping_hours(self) -> None:
        """验证 ccusage blocks 的 5 小时窗口会分摊到覆盖的小时，避免上午用量消失"""
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-01T11:35:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=self.source_reports,
            items=self.items,
            hourly_items=[
                UsageHourlyItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="claude",
                    hour="2026-06-01T00:00:00+08:00",
                    input_tokens=0,
                    output_tokens=0,
                    cache_creation_tokens=0,
                    cache_read_tokens=5000,
                    total_tokens=5000,
                    metadata={"machine": "macbook", "account": "wang"},
                ),
                UsageHourlyItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="codex",
                    hour="2026-06-01T10:00:00+08:00",
                    input_tokens=10,
                    output_tokens=5,
                    cache_creation_tokens=0,
                    cache_read_tokens=85,
                    total_tokens=100,
                    metadata={"machine": "macbook", "account": "wang"},
                ),
            ],
            block_items=[
                UsageBlockItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="claude",
                    start_time="2026-06-01T05:00:00+08:00",
                    end_time="2026-06-01T10:00:00+08:00",
                    input_tokens=100,
                    output_tokens=50,
                    cache_creation_tokens=0,
                    cache_read_tokens=350,
                    total_tokens=500,
                    metadata={"machine": "macbook", "account": "wang"},
                )
            ],
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str=self.date_str,
            timezone_str=self.timezone_str,
            period="today",
            current_time_str="2026-06-01T11:35:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        points = {point["hour"]: point for point in snapshot["trend"]["points"]}
        self.assertEqual(points["2026-06-01T00:00:00+08:00"]["total_tokens"], 0)
        self.assertEqual(points["2026-06-01T07:00:00+08:00"]["total_tokens"], 100)
        self.assertEqual(points["2026-06-01T08:00:00+08:00"]["total_tokens"], 100)
        self.assertEqual(points["2026-06-01T09:00:00+08:00"]["total_tokens"], 100)
        self.assertEqual(points["2026-06-01T10:00:00+08:00"]["total_tokens"], 100)
        by_agent = {row["agent"]: row["total_tokens"] for row in snapshot["trend"]["by_agent"]}
        self.assertEqual(by_agent["claude"], 500)
        self.assertEqual(by_agent["codex"], 100)

    def test_codex_drift_does_not_create_current_hour_residual_spike(self) -> None:
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-05T11:35:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=[],
            items=[
                UsageItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="codex",
                    date="2026-06-05",
                    input_tokens=2000,
                    output_tokens=500,
                    cache_creation_tokens=0,
                    cache_read_tokens=500,
                    total_tokens=3000,
                    metadata={"machine": "macbook", "account": "wang"},
                ),
            ],
            hourly_items=[
                UsageHourlyItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="codex",
                    hour="2026-06-05T08:00:00+08:00",
                    input_tokens=700,
                    output_tokens=200,
                    cache_creation_tokens=0,
                    cache_read_tokens=100,
                    total_tokens=1000,
                    metadata={
                        "machine": "macbook",
                        "account": "wang",
                        "provenance": "mswusage_codex_token_count",
                        "drift": {"status": "drift_detected", "threshold_percent": 5},
                    },
                ),
            ],
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str="2026-06-05",
            timezone_str=self.timezone_str,
            period="today",
            current_time_str="2026-06-05T11:35:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        self.assertEqual(snapshot["summary"]["total_tokens"], 3000)
        self.assertEqual(snapshot["trend"]["points"][8]["total_tokens"], 1000)
        self.assertEqual(snapshot["trend"]["points"][11]["total_tokens"], 0)
        self.assertEqual(snapshot["metadata"]["codex_hourly"]["drift"]["status"], "drift_detected")

    def test_codex_drift_with_all_daily_baseline_does_not_double_count_trend(self) -> None:
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-05T11:35:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=[],
            items=[
                UsageItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="all",
                    date="2026-06-05",
                    input_tokens=2000,
                    output_tokens=500,
                    cache_creation_tokens=0,
                    cache_read_tokens=500,
                    total_tokens=3000,
                    metadata={"machine": "macbook", "account": "wang"},
                ),
            ],
            hourly_items=[
                UsageHourlyItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="codex",
                    hour="2026-06-05T08:00:00+08:00",
                    input_tokens=700,
                    output_tokens=200,
                    cache_creation_tokens=0,
                    cache_read_tokens=100,
                    total_tokens=1000,
                    metadata={
                        "machine": "macbook",
                        "account": "wang",
                        "provenance": "mswusage_codex_token_count",
                        "drift": {"status": "drift_detected", "baseline_agent": "all", "threshold_percent": 5},
                    },
                ),
            ],
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str="2026-06-05",
            timezone_str=self.timezone_str,
            period="today",
            current_time_str="2026-06-05T11:35:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        self.assertEqual(snapshot["summary"]["total_tokens"], 3000)
        self.assertEqual(sum(point["total_tokens"] for point in snapshot["trend"]["points"]), 1000)
        self.assertEqual(snapshot["trend"]["points"][8]["total_tokens"], 1000)
        self.assertEqual(snapshot["trend"]["points"][11]["total_tokens"], 0)

    def test_today_hourly_trend_is_capped_to_period_total_when_hourly_exceeds_daily(self) -> None:
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-05T11:35:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=[],
            items=[
                UsageItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="codex",
                    date="2026-06-05",
                    input_tokens=2000,
                    output_tokens=500,
                    cache_creation_tokens=0,
                    cache_read_tokens=500,
                    total_tokens=3000,
                    metadata={"machine": "macbook", "account": "wang"},
                ),
            ],
            hourly_items=[
                UsageHourlyItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="codex",
                    hour="2026-06-05T08:00:00+08:00",
                    input_tokens=2800,
                    output_tokens=700,
                    cache_creation_tokens=0,
                    cache_read_tokens=700,
                    total_tokens=4200,
                    metadata={
                        "machine": "macbook",
                        "account": "wang",
                        "provenance": "mswusage_codex_token_count",
                        "drift": {"status": "drift_detected", "threshold_percent": 5},
                    },
                ),
            ],
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str="2026-06-05",
            timezone_str=self.timezone_str,
            period="today",
            current_time_str="2026-06-05T11:35:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        self.assertEqual(snapshot["summary"]["total_tokens"], 3000)
        self.assertEqual(sum(point["total_tokens"] for point in snapshot["trend"]["points"]), 3000)
        token_types = {row["type"]: row["values"] for row in snapshot["trend"]["by_token_type"]}
        self.assertEqual(sum(token_types["input"]), 2000)
        self.assertEqual(sum(token_types["output"]), 500)
        self.assertEqual(sum(token_types["cache"]), 500)
        by_agent = {row["agent"]: row["total_tokens"] for row in snapshot["trend"]["by_agent"]}
        self.assertEqual(by_agent["codex"], 3000)

    def test_by_machine_groups_os_accounts_under_same_machine(self) -> None:
        """验证同一物理机器的不同 OS 用户在 by Machine 下作为 users 展示"""
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-01T10:50:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=[],
            items=[
                UsageItem(
                    source_id="mac-wang",
                    machine="macbook",
                    account="wang",
                    agent="claude",
                    date=self.date_str,
                    input_tokens=10,
                    output_tokens=0,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                    total_tokens=10,
                    metadata={"machine": "macbook", "account": "wang"},
                    model_breakdowns=[],
                ),
                UsageItem(
                    source_id="mac-root",
                    machine="macbook",
                    account="root",
                    agent="codex",
                    date=self.date_str,
                    input_tokens=30,
                    output_tokens=0,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                    total_tokens=30,
                    metadata={"machine": "macbook", "account": "root"},
                    model_breakdowns=[],
                ),
            ],
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str=self.date_str,
            timezone_str=self.timezone_str,
            current_time_str="2026-06-01T10:55:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        self.assertEqual(snapshot["groups"]["by_machine"], [
            {
                "name": "macbook",
                "display_name": "macbook",
                "total_tokens": 40,
                "users": [
                    {
                        "account": "root",
                        "machine": "macbook",
                        "display_name": "macbook · root",
                        "total_tokens": 30,
                        "source_ids": ["mac-root"],
                    },
                    {
                        "account": "wang",
                        "machine": "macbook",
                        "display_name": "macbook · wang",
                        "total_tokens": 10,
                        "source_ids": ["mac-wang"],
                    },
                ],
            },
        ])

    def test_by_machine_includes_zero_usage_source_identity_user(self) -> None:
        """验证只有 source identity、没有 usage 的用户也挂在机器 users 下"""
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-01T10:50:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=[],
            items=[
                UsageItem(
                    source_id="linux-ai-wang",
                    machine="VM-0-3-ubuntu",
                    account="wang",
                    agent="claude",
                    date=self.date_str,
                    input_tokens=10,
                    output_tokens=0,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                    total_tokens=10,
                    metadata={"machine": "VM-0-3-ubuntu", "account": "wang"},
                    model_breakdowns=[],
                )
            ],
            source_identities=[
                {
                    "source_id": "linux-ai-lighthouse",
                    "host": "VM-0-3-ubuntu",
                    "machine": "VM-0-3-ubuntu",
                    "os_user": "lighthouse",
                    "platform": "linux",
                }
            ],
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str=self.date_str,
            timezone_str=self.timezone_str,
            current_time_str="2026-06-01T10:55:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        machine = next(row for row in snapshot["groups"]["by_machine"] if row["name"] == "VM-0-3-ubuntu")
        self.assertEqual(
            [(user["account"], user["total_tokens"]) for user in machine["users"]],
            [("wang", 10), ("lighthouse", 0)],
        )

    def test_source_status_includes_latest_source_identity(self) -> None:
        """验证健康状态携带 host/user 标识，方便同一机器多用户区分"""
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-01T10:50:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=[
                {
                    "source_id": "linux-ai-wang",
                    "report_type": "daily",
                    "command": "HTTP Ingest",
                    "status": "ok",
                    "error_type": None,
                    "error_message": None,
                }
            ],
            items=[
                UsageItem(
                    source_id="linux-ai-wang",
                    machine="VM-0-3-ubuntu",
                    account="wang",
                    agent="claude",
                    date=self.date_str,
                    input_tokens=10,
                    output_tokens=0,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                    total_tokens=10,
                    metadata={"machine": "VM-0-3-ubuntu", "account": "wang", "platform": "linux"},
                    model_breakdowns=[],
                ),
                UsageItem(
                    source_id="linux-ai-wang",
                    machine="VM-0-3-ubuntu",
                    account="wang",
                    agent="codex",
                    date=self.date_str,
                    input_tokens=20,
                    output_tokens=0,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                    total_tokens=20,
                    metadata={"machine": "VM-0-3-ubuntu", "account": "wang", "platform": "linux"},
                    model_breakdowns=[],
                ),
            ],
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str=self.date_str,
            timezone_str=self.timezone_str,
            current_time_str="2026-06-01T10:55:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        status = next(s for s in snapshot["source_status"] if s["source_id"] == "linux-ai-wang")
        self.assertEqual(status["host"], "VM-0-3-ubuntu")
        self.assertEqual(status["os_user"], "wang")
        self.assertEqual(status["platform"], "linux")
        self.assertEqual(status["display_name"], "VM-0-3-ubuntu · wang")
