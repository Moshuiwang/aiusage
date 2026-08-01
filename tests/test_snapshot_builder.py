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

    def test_build_snapshot_uses_account_hourly_ledger_for_user_visible_total(self) -> None:
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

        self.assertEqual(snapshot["summary"]["total_tokens"], 155)
        self.assertEqual(snapshot["summary"]["input_tokens"], 100)
        self.assertEqual(snapshot["summary"]["output_tokens"], 20)
        self.assertEqual(snapshot["summary"]["cache_read_tokens"], 30)
        self.assertEqual(snapshot["items"][0]["agent"], "codex")
        self.assertEqual(snapshot["items"][0]["total_tokens"], 155)
        account_hourly = snapshot["account_hourly"]
        self.assertEqual(account_hourly["total_tokens"], 155)
        self.assertEqual(account_hourly["facts"], 1)
        self.assertEqual(account_hourly["by_ai_account"][0]["label"], "start@example.com")
        self.assertIsNone(account_hourly["by_ai_account"][0]["subscription"])
        self.assertEqual(account_hourly["by_ai_account"][0]["attribution_confidence"], "account_observed_usage_inferred")
        self.assertEqual(
            account_hourly["by_ai_account"][0]["confidence_breakdown"],
            [{"confidence": "account_observed_usage_inferred", "total_tokens": 155}],
        )
        self.assertEqual(account_hourly["by_os_user"][0]["os_user"], "wangzhipeng")
        self.assertEqual(account_hourly["confidence_breakdown"][0]["confidence"], "account_observed_usage_inferred")

    def test_ledger_partial_agent_keeps_all_daily_residual(self) -> None:
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-12T14:30:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=[],
            items=[
                UsageItem(
                    source_id="mac-local",
                    machine="MacBook Pro",
                    account="wangzhipeng",
                    agent="all",
                    date="2026-06-12",
                    input_tokens=1000,
                    output_tokens=0,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                    total_tokens=1000,
                    metadata={"machine": "MacBook Pro", "account": "wangzhipeng"},
                )
            ],
            hourly_facts=[
                UsageHourlyFact(
                    fact_id="codex:codex:mac-local:2026-06-12T13:00:00+08:00:2026-06-12T14:00:00+08:00:unconfirmed_local_source:openai:unconfirmed_local_source:mac-local:codex:mswusage_codex_token_count",
                    source_id="mac-local",
                    machine_id="macbook-pro-local",
                    machine_name="MacBook Pro",
                    host="macbook-pro.local",
                    os_user="wangzhipeng",
                    platform="darwin",
                    ai_provider="openai",
                    ai_account_id="unconfirmed_local_source:mac-local:codex",
                    ai_account_label="本机来源 / 未确认账号",
                    ai_account_display_name=None,
                    ai_account_subscription=None,
                    agent="codex",
                    client="codex",
                    window_start="2026-06-12T13:00:00+08:00",
                    window_end="2026-06-12T14:00:00+08:00",
                    timezone="Asia/Shanghai",
                    input_tokens=400,
                    output_tokens=0,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                    reasoning_output_tokens=0,
                    total_tokens=400,
                    event_count=1,
                    session_count=1,
                    attribution_confidence="unconfirmed_local_source",
                    provenance="mswusage_codex_token_count",
                )
            ],
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str="2026-06-12",
            timezone_str=self.timezone_str,
            current_time_str="2026-06-12T14:55:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        self.assertEqual(snapshot["summary"]["total_tokens"], 1000)
        by_agent = {row["name"]: row["total_tokens"] for row in snapshot["groups"]["by_agent"]}
        self.assertEqual(by_agent["codex"], 400)
        self.assertEqual(by_agent["all"], 600)

    def test_build_snapshot_includes_known_ai_accounts_without_hourly_facts(self) -> None:
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-11T14:30:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=[],
            items=[],
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO ai_accounts (
                  provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "codex",
                    "86b44ff3-d85f-4fa7-bbbb-1a662509b3b7",
                    "startimessocietegn@gmail.com",
                    "StarTimes",
                    "pro",
                    "2026-06-11T14:30:00+08:00",
                    "2026-06-11T14:30:00+08:00",
                ),
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

        self.assertEqual(snapshot["account_hourly"]["by_ai_account"], [])
        self.assertEqual(
            snapshot["ai_accounts"],
            [
                {
                    "provider": "codex",
                    "account_id": "86b44ff3-d85f-4fa7-bbbb-1a662509b3b7",
                    "label": "startimessocietegn@gmail.com",
                    "display_name": "StarTimes",
                    "subscription": "pro",
                    "last_seen_at": "2026-06-11T14:30:00+08:00",
                }
            ],
        )

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

    def test_build_snapshot_keeps_best_limit_window_per_source_provider_and_window(self) -> None:
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
                    used_percent=92.0,
                    remaining_percent=8.0,
                    reset_at="2026-05-24T14:40:00+00:00",
                    window_duration_minutes=300,
                    observed_at="2026-06-01T10:45:00+08:00",
                    source_type="active_limits_cache",
                    confidence="observed",
                    status="ok",
                ),
                LimitWindow(
                    provider="claude",
                    source_id="claude-main",
                    window="session",
                    used_percent=96.0,
                    remaining_percent=4.0,
                    reset_at="2026-06-01T18:09:00+08:00",
                    window_duration_minutes=300,
                    observed_at="2026-06-01T10:46:00+08:00",
                    source_type="official_cli",
                    confidence="observed",
                    status="ok",
                ),
                LimitWindow(
                    provider="claude",
                    source_id="claude-main",
                    window="week",
                    used_percent=47.0,
                    remaining_percent=53.0,
                    reset_at="2026-06-08T00:00:00+08:00",
                    window_duration_minutes=10080,
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
            [(row["source_id"], row["provider"], row["window"], row["source_type"], row["remaining_percent"]) for row in snapshot["limits"]],
            [
                ("claude-main", "claude", "session", "official_cli", 4.0),
                ("claude-main", "claude", "week", "official_cli", 53.0),
            ],
        )

    def test_build_snapshot_filters_old_active_limits_cache_from_effective_windows(self) -> None:
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
                    source_id="old-cache",
                    window="session",
                    used_percent=99.0,
                    remaining_percent=1.0,
                    reset_at="2026-06-01T18:00:00+08:00",
                    window_duration_minutes=300,
                    observed_at="2026-06-01T10:44:00+08:00",
                    source_type="active_limits_cache",
                    confidence="observed",
                    status="ok",
                ),
                LimitWindow(
                    provider="claude",
                    source_id="runtime",
                    window="session",
                    used_percent=3.0,
                    remaining_percent=97.0,
                    reset_at="2026-06-01T18:00:00+08:00",
                    window_duration_minutes=300,
                    observed_at="2026-06-01T10:46:00+08:00",
                    source_type="runtime_api",
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
            [(row["source_id"], row["source_type"], row["remaining_percent"]) for row in snapshot["limits"]],
            [("runtime", "runtime_api", 97.0)],
        )

    def test_build_snapshot_excludes_expired_limit_windows(self) -> None:
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
                    used_percent=96.0,
                    remaining_percent=4.0,
                    reset_at="2026-06-01T10:00:00+08:00",
                    window_duration_minutes=300,
                    observed_at="2026-06-01T09:45:00+08:00",
                    source_type="official_cli",
                    confidence="observed",
                    status="ok",
                ),
                LimitWindow(
                    provider="claude",
                    source_id="claude-main",
                    window="week",
                    used_percent=47.0,
                    remaining_percent=53.0,
                    reset_at="2026-06-08T00:00:00+08:00",
                    window_duration_minutes=10080,
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
            [(row["provider"], row["window"], row["remaining_percent"]) for row in snapshot["limits"]],
            [("claude", "week", 53.0)],
        )
        self.assertEqual(snapshot["limit_status"], [{
            "provider": "claude",
            "source_id": "claude-main",
            "observed_at": "2026-06-01T10:46:00+08:00",
            "source_type": "official_cli",
            "status": "ok",
        }])

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
        self.assertEqual(snapshot["limits"], [])

    def test_latest_provider_failure_immediately_marks_previous_success_unavailable(self) -> None:
        write_sqlite(
            path=self.db_path, collected_at="2026-06-01T10:30:00+08:00",
            timezone=self.timezone_str, run_status="success",
            source_reports=self.source_reports, items=self.items,
        )
        write_limit_windows(self.db_path, [
            LimitWindow(
                provider="claude", source_id="linux-biai-wangzhipeng", window="session",
                used_percent=76, remaining_percent=24, reset_at="2026-06-01T15:00:00+08:00",
                window_duration_minutes=300, observed_at="2026-06-01T10:00:00+08:00",
                source_type="oauth_usage_api", confidence="observed", status="ok",
            ),
            LimitWindow(
                provider="claude", source_id="linux-biai-wangzhipeng", window="unknown",
                used_percent=0, remaining_percent=0, reset_at="2026-06-01T10:30:00+08:00",
                window_duration_minutes=0, observed_at="2026-06-01T10:30:00+08:00",
                source_type="provider_runtime", confidence="missing", status="provider_failed",
            ),
        ], seen_at="2026-06-01T10:30:00+08:00")

        build_snapshot(
            db_path=self.db_path, output_path=self.out_path, date_str=self.date_str,
            timezone_str=self.timezone_str, current_time_str="2026-06-01T10:31:00+08:00",
        )
        with open(self.out_path, "r", encoding="utf-8") as handle:
            snapshot = json.load(handle)

        self.assertEqual(snapshot["limit_status"], [{
            "provider": "claude", "source_id": "linux-biai-wangzhipeng",
            "observed_at": "2026-06-01T10:00:00+08:00",
            "source_type": "oauth_usage_api", "status": "unavailable",
        }])


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

    def test_today_period_dedupes_cumulative_ccusage_block_snapshots(self) -> None:
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-28T09:45:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=[],
            items=[
                UsageItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="all",
                    date="2026-06-28",
                    input_tokens=1_000,
                    output_tokens=500,
                    cache_creation_tokens=0,
                    cache_read_tokens=20_000,
                    total_tokens=21_500,
                    metadata={"machine": "macbook", "account": "wang"},
                ),
            ],
            hourly_items=[
                UsageHourlyItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="codex",
                    hour="2026-06-28T08:00:00+08:00",
                    input_tokens=100,
                    output_tokens=50,
                    cache_creation_tokens=0,
                    cache_read_tokens=3_350,
                    total_tokens=3_500,
                    metadata={"machine": "macbook", "account": "wang"},
                ),
            ],
            block_items=[
                UsageBlockItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="claude",
                    start_time="2026-06-28T08:00:00+08:00",
                    end_time="2026-06-28T08:12:00+08:00",
                    input_tokens=200,
                    output_tokens=100,
                    cache_creation_tokens=0,
                    cache_read_tokens=4_700,
                    total_tokens=5_000,
                    metadata={
                        "machine": "macbook",
                        "account": "wang",
                        "ccusage_block_row": {"id": "2026-06-28T00:00:00.000Z", "actualEndTime": "2026-06-28T00:12:00.000Z"},
                    },
                ),
                UsageBlockItem(
                    source_id="mac-local",
                    machine="macbook",
                    account="wang",
                    agent="claude",
                    start_time="2026-06-28T08:00:00+08:00",
                    end_time="2026-06-28T08:48:00+08:00",
                    input_tokens=300,
                    output_tokens=200,
                    cache_creation_tokens=0,
                    cache_read_tokens=9_500,
                    total_tokens=10_000,
                    metadata={
                        "machine": "macbook",
                        "account": "wang",
                        "ccusage_block_row": {"id": "2026-06-28T00:00:00.000Z", "actualEndTime": "2026-06-28T00:48:00.000Z"},
                    },
                ),
            ],
        )

        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str="2026-06-28",
            timezone_str=self.timezone_str,
            period="today",
            current_time_str="2026-06-28T09:45:00+08:00",
        )

        with open(self.out_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        points = {point["hour"]: point for point in snapshot["trend"]["points"]}
        self.assertEqual(points["2026-06-28T08:00:00+08:00"]["total_tokens"], 13_500)
        by_agent = {row["agent"]: row["total_tokens"] for row in snapshot["trend"]["by_agent"]}
        self.assertEqual(by_agent["claude"], 10_000)
        self.assertEqual(by_agent["codex"], 3_500)

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


class TestSnapshotProviderSlots(unittest.TestCase):
    """Issue #61：/api/summary 把 Claude 用量与 Claude 额度作为两个独立字段返回。"""

    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        self.out_fd, self.out_path = tempfile.mkstemp(suffix=".json")
        self.date_str = "2026-06-01"
        self.timezone_str = "Asia/Shanghai"
        self.current_time = "2026-06-01T10:55:00+08:00"
        self.source_reports = [
            {
                "source_id": "mac-local",
                "report_type": "daily",
                "command": "ccusage daily --json",
                "status": "ok",
                "error_type": None,
                "error_message": None,
            },
            {
                "source_id": "linux-server",
                "report_type": "daily",
                "command": "ccusage daily --json",
                "status": "ok",
                "error_type": None,
                "error_message": None,
            },
        ]

    def tearDown(self) -> None:
        os.close(self.db_fd)
        os.close(self.out_fd)
        for path in [self.db_path, self.out_path]:
            if os.path.exists(path):
                os.remove(path)

    def _claude_item(self) -> UsageItem:
        return UsageItem(
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
            model_breakdowns=[],
        )

    def _codex_item(self) -> UsageItem:
        return UsageItem(
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
            model_breakdowns=[],
        )

    def _write_usage(self, items) -> None:
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-01T10:50:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=self.source_reports,
            items=items,
        )

    def _build(self) -> dict:
        build_snapshot(
            db_path=self.db_path,
            output_path=self.out_path,
            date_str=self.date_str,
            timezone_str=self.timezone_str,
            current_time_str=self.current_time,
        )
        with open(self.out_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def _slot(self, snapshot: dict, provider: str) -> dict:
        return next(row for row in snapshot["provider_slots"] if row["provider"] == provider)

    def test_provider_slots_expose_claude_usage_and_quota_as_independent_fields(self) -> None:
        self._write_usage([self._claude_item(), self._codex_item()])
        write_limit_windows(
            self.db_path,
            [
                LimitWindow(
                    provider="claude",
                    source_id="claude-main",
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

        claude = self._slot(self._build(), "claude")

        self.assertEqual(claude["usage"]["status"], "available")
        self.assertEqual(claude["usage"]["total_tokens"], 1800)
        self.assertEqual(claude["usage"]["input_tokens"], 1000)
        self.assertEqual(claude["usage"]["output_tokens"], 500)
        self.assertEqual(claude["usage"]["cache_tokens"], 300)
        self.assertEqual(claude["quota"]["status"], "available")
        self.assertIsNone(claude["quota"]["reason"])
        self.assertEqual(claude["quota"]["source_id"], "claude-main")
        self.assertEqual(claude["quota"]["last_verified_at"], "2026-06-01T10:46:00+08:00")
        self.assertEqual(
            [(row["window"], row["used_percent"], row["reset_at"]) for row in claude["quota"]["windows"]],
            [("week", 31.5, "2026-06-09T00:00:00+08:00")],
        )

    def test_provider_slots_keep_claude_usage_when_official_quota_is_stale(self) -> None:
        self._write_usage([self._claude_item(), self._codex_item()])
        write_limit_windows(
            self.db_path,
            [
                LimitWindow(
                    provider="claude",
                    source_id="claude-main",
                    window="week",
                    used_percent=78.25,
                    remaining_percent=21.75,
                    reset_at="2026-06-09T00:00:00+08:00",
                    window_duration_minutes=10080,
                    observed_at="2026-05-30T10:00:00+08:00",
                    source_type="oauth_usage_api",
                    confidence="observed",
                    status="ok",
                ),
            ],
            seen_at="2026-05-30T10:00:00+08:00",
        )

        claude = self._slot(self._build(), "claude")

        self.assertEqual(claude["usage"]["status"], "available")
        self.assertEqual(claude["usage"]["total_tokens"], 1800)
        self.assertEqual(claude["quota"]["status"], "missing")
        self.assertEqual(claude["quota"]["reason"], "stale")
        self.assertEqual(claude["quota"]["windows"], [])
        self.assertEqual(claude["quota"]["last_verified_at"], "2026-05-30T10:00:00+08:00")
        serialized = json.dumps(claude["quota"], sort_keys=True)
        for leaked in ("used_percent", "remaining_percent", "reset_at", "78.25", "2026-06-09"):
            self.assertNotIn(leaked, serialized)

    def test_provider_slots_hide_expired_official_quota_but_keep_last_verified_at(self) -> None:
        self._write_usage([self._claude_item()])
        write_limit_windows(
            self.db_path,
            [
                LimitWindow(
                    provider="claude",
                    source_id="claude-main",
                    window="session",
                    used_percent=91.0,
                    remaining_percent=9.0,
                    reset_at="2026-06-01T10:00:00+08:00",
                    window_duration_minutes=300,
                    observed_at="2026-06-01T09:00:00+08:00",
                    source_type="oauth_usage_api",
                    confidence="observed",
                    status="ok",
                ),
            ],
            seen_at="2026-06-01T09:00:00+08:00",
        )

        claude = self._slot(self._build(), "claude")

        self.assertEqual(claude["quota"]["status"], "missing")
        self.assertEqual(claude["quota"]["reason"], "expired")
        self.assertEqual(claude["quota"]["windows"], [])
        self.assertEqual(claude["quota"]["last_verified_at"], "2026-06-01T09:00:00+08:00")
        serialized = json.dumps(claude["quota"], sort_keys=True)
        for leaked in ("used_percent", "91.0", "2026-06-01T10:00:00+08:00"):
            self.assertNotIn(leaked, serialized)

    def test_provider_slots_keep_claude_quota_when_claude_usage_is_absent(self) -> None:
        self._write_usage([self._codex_item()])
        write_limit_windows(
            self.db_path,
            [
                LimitWindow(
                    provider="claude",
                    source_id="claude-main",
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

        claude = self._slot(self._build(), "claude")

        self.assertEqual(claude["usage"]["status"], "missing")
        self.assertEqual(claude["usage"]["total_tokens"], 0)
        self.assertEqual(claude["quota"]["status"], "available")
        self.assertEqual([row["window"] for row in claude["quota"]["windows"]], ["week"])

    def test_provider_slots_report_missing_usage_and_missing_quota_without_facts(self) -> None:
        self._write_usage([self._codex_item()])

        claude = self._slot(self._build(), "claude")

        self.assertEqual(claude["usage"]["status"], "missing")
        self.assertEqual(claude["usage"]["total_tokens"], 0)
        self.assertEqual(claude["quota"]["status"], "missing")
        self.assertEqual(claude["quota"]["reason"], "no_data")
        self.assertEqual(claude["quota"]["windows"], [])
        self.assertIsNone(claude["quota"]["last_verified_at"])
        self.assertIsNone(claude["quota"]["source_id"])

    def test_codex_limit_window_never_occupies_claude_quota_slot(self) -> None:
        self._write_usage([self._claude_item(), self._codex_item()])
        write_limit_windows(
            self.db_path,
            [
                LimitWindow(
                    provider="codex",
                    source_id="codex-main",
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
            ],
            seen_at="2026-06-01T10:45:00+08:00",
        )

        snapshot = self._build()
        claude = self._slot(snapshot, "claude")
        codex = self._slot(snapshot, "codex")

        self.assertEqual(claude["quota"]["status"], "missing")
        self.assertEqual(claude["quota"]["reason"], "no_data")
        self.assertIsNone(claude["quota"]["source_id"])
        self.assertEqual(claude["quota"]["windows"], [])
        self.assertNotIn("codex-main", json.dumps(claude, sort_keys=True))
        self.assertEqual(codex["quota"]["status"], "available")
        self.assertEqual(codex["quota"]["source_id"], "codex-main")
        self.assertEqual([row["window"] for row in codex["quota"]["windows"]], ["session"])

    def test_last_verified_at_ignores_local_estimate_rows(self) -> None:
        """ccusage 本地估算不是官方验证，不能借 last_verified_at 伪装成新鲜的官方额度。"""
        self._write_usage([self._claude_item()])
        write_limit_windows(
            self.db_path,
            [
                LimitWindow(
                    provider="claude",
                    source_id="claude-main",
                    window="week",
                    used_percent=78.25,
                    remaining_percent=21.75,
                    reset_at="2026-06-09T00:00:00+08:00",
                    window_duration_minutes=10080,
                    observed_at="2026-05-30T10:00:00+08:00",
                    source_type="oauth_usage_api",
                    confidence="observed",
                    status="ok",
                ),
                LimitWindow(
                    provider="claude",
                    source_id="claude-local-estimate",
                    window="week",
                    used_percent=12.0,
                    remaining_percent=88.0,
                    reset_at="2026-06-09T00:00:00+08:00",
                    window_duration_minutes=10080,
                    observed_at="2026-06-01T10:54:00+08:00",
                    source_type="ccusage_blocks",
                    confidence="estimated",
                    status="ok",
                ),
            ],
            seen_at="2026-06-01T10:54:00+08:00",
        )

        claude = self._slot(self._build(), "claude")

        self.assertEqual(claude["quota"]["status"], "missing")
        self.assertEqual(claude["quota"]["reason"], "stale")
        self.assertEqual(claude["quota"]["source_id"], "claude-main")
        self.assertEqual(claude["quota"]["source_type"], "oauth_usage_api")
        self.assertEqual(claude["quota"]["last_verified_at"], "2026-05-30T10:00:00+08:00")

    def test_last_verified_at_belongs_to_the_reported_quota_source(self) -> None:
        """last_verified_at 必须和同一对象里的 source_id / source_type 指向同一条记录。"""
        self._write_usage([self._claude_item()])
        write_limit_windows(
            self.db_path,
            [
                LimitWindow(
                    provider="claude",
                    source_id="claude-main",
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
                LimitWindow(
                    provider="claude",
                    source_id="claude-ghost",
                    window="week",
                    used_percent=0.0,
                    remaining_percent=0.0,
                    reset_at="2026-06-09T00:00:00+08:00",
                    window_duration_minutes=10080,
                    observed_at="2026-06-01T10:54:00+08:00",
                    source_type="oauth_usage_api",
                    confidence="unknown",
                    status="unknown",
                ),
            ],
            seen_at="2026-06-01T10:54:00+08:00",
        )

        claude = self._slot(self._build(), "claude")

        self.assertEqual(claude["quota"]["status"], "available")
        self.assertEqual(claude["quota"]["source_id"], "claude-main")
        self.assertEqual(claude["quota"]["last_verified_at"], "2026-06-01T10:46:00+08:00")

    def test_local_estimate_only_provider_reports_no_official_verification(self) -> None:
        """只有本地估算时，额度是 unverified，且没有任何官方验证时间可报。"""
        self._write_usage([self._claude_item()])
        write_limit_windows(
            self.db_path,
            [
                LimitWindow(
                    provider="claude",
                    source_id="claude-local-estimate",
                    window="week",
                    used_percent=12.0,
                    remaining_percent=88.0,
                    reset_at="2026-06-09T00:00:00+08:00",
                    window_duration_minutes=10080,
                    observed_at="2026-06-01T10:54:00+08:00",
                    source_type="ccusage_blocks",
                    confidence="estimated",
                    status="ok",
                ),
            ],
            seen_at="2026-06-01T10:54:00+08:00",
        )

        claude = self._slot(self._build(), "claude")

        self.assertEqual(claude["quota"]["status"], "missing")
        self.assertEqual(claude["quota"]["reason"], "unverified")
        self.assertIsNone(claude["quota"]["last_verified_at"])
        self.assertIsNone(claude["quota"]["source_id"])
        self.assertEqual(claude["quota"]["windows"], [])

    def test_last_verified_at_only_counts_successful_official_observations(self) -> None:
        """同一来源里 confidence != observed 的行不是一次成功核对，不能推新最近验证时间。"""
        self._write_usage([self._claude_item()])
        write_limit_windows(
            self.db_path,
            [
                LimitWindow(
                    provider="claude",
                    source_id="claude-main",
                    window="week",
                    used_percent=78.25,
                    remaining_percent=21.75,
                    reset_at="2026-06-09T00:00:00+08:00",
                    window_duration_minutes=10080,
                    observed_at="2026-06-01T10:00:00+08:00",
                    source_type="oauth_usage_api",
                    confidence="observed",
                    status="ok",
                ),
                LimitWindow(
                    provider="claude",
                    source_id="claude-main",
                    window="5h",
                    used_percent=44.0,
                    remaining_percent=56.0,
                    reset_at="2026-06-01T14:00:00+08:00",
                    window_duration_minutes=300,
                    observed_at="2026-06-01T10:54:00+08:00",
                    source_type="oauth_usage_api",
                    confidence="estimated",
                    status="ok",
                ),
            ],
            seen_at="2026-06-01T10:54:00+08:00",
        )

        claude = self._slot(self._build(), "claude")

        self.assertEqual(claude["quota"]["status"], "available")
        self.assertEqual([row["window"] for row in claude["quota"]["windows"]], ["week"])
        self.assertEqual(claude["quota"]["last_verified_at"], "2026-06-01T10:00:00+08:00")

    def test_last_verified_at_ignores_failed_official_probes(self) -> None:
        """provider 每轮失败都不算「核对过」，不能把最近验证时间一路往前推。"""
        self._write_usage([self._claude_item()])
        write_limit_windows(
            self.db_path,
            [
                LimitWindow(
                    provider="claude",
                    source_id="claude-main",
                    window="week",
                    used_percent=78.25,
                    remaining_percent=21.75,
                    reset_at="2026-06-09T00:00:00+08:00",
                    window_duration_minutes=10080,
                    observed_at="2026-06-01T08:00:00+08:00",
                    source_type="oauth_usage_api",
                    confidence="observed",
                    status="ok",
                ),
                LimitWindow(
                    provider="claude",
                    source_id="claude-main",
                    window="5h",
                    used_percent=0.0,
                    remaining_percent=0.0,
                    reset_at="2026-06-01T14:00:00+08:00",
                    window_duration_minutes=300,
                    observed_at="2026-06-01T10:54:00+08:00",
                    source_type="oauth_usage_api",
                    confidence="missing",
                    status="provider_failed",
                ),
            ],
            seen_at="2026-06-01T10:54:00+08:00",
        )

        claude = self._slot(self._build(), "claude")

        self.assertEqual(claude["quota"]["status"], "missing")
        self.assertEqual(claude["quota"]["reason"], "unavailable")
        self.assertEqual(claude["quota"]["last_verified_at"], "2026-06-01T08:00:00+08:00")

    def _claude_fact(self, agent: str, ai_provider: str = "claude") -> UsageHourlyFact:
        return UsageHourlyFact(
            fact_id=f"fact-{ai_provider}-{agent}",
            source_id="mac-local",
            machine_id="macbook",
            machine_name="macbook",
            host="macbook",
            os_user="wang",
            platform="darwin",
            ai_provider=ai_provider,
            ai_account_id=f"{ai_provider}-main",
            ai_account_label=f"{ai_provider}-main",
            ai_account_display_name=None,
            ai_account_subscription=None,
            agent=agent,
            client="cli",
            window_start=f"{self.date_str}T09:00:00+08:00",
            window_end=f"{self.date_str}T10:00:00+08:00",
            timezone=self.timezone_str,
            input_tokens=1000,
            output_tokens=500,
            cache_creation_tokens=100,
            cache_read_tokens=200,
            reasoning_output_tokens=0,
            total_tokens=1800,
            event_count=1,
            session_count=1,
            attribution_confidence="observed",
            provenance="test",
            metadata={"machine": "macbook", "account": "wang"},
        )

    def _write_facts(self, facts, items=()) -> None:
        write_sqlite(
            path=self.db_path,
            collected_at="2026-06-01T10:50:00+08:00",
            timezone=self.timezone_str,
            run_status="success",
            source_reports=self.source_reports,
            items=list(items),
            hourly_facts=facts,
        )

    def test_usage_slots_attribute_aggregate_agent_by_canonical_ai_provider(self) -> None:
        """pusher 只有聚合行时会把 agent 写成 'all'，权威归属在 ai_provider 上。"""
        self._write_facts([self._claude_fact(agent="all")])

        snapshot = self._build()
        claude = self._slot(snapshot, "claude")

        self.assertEqual(snapshot["summary"]["total_tokens"], 1800)
        self.assertEqual(claude["usage"]["status"], "available")
        self.assertEqual(claude["usage"]["total_tokens"], 1800)

    def test_usage_slots_attribute_unknown_agent_by_canonical_ai_provider(self) -> None:
        """源数据缺 agent 时 pusher 会写 'unknown'，同样不能因此丢掉 Claude 用量。"""
        self._write_facts([self._claude_fact(agent="unknown")])

        snapshot = self._build()
        claude = self._slot(snapshot, "claude")

        self.assertEqual(snapshot["summary"]["total_tokens"], 1800)
        self.assertEqual(claude["usage"]["total_tokens"], 1800)

    def test_usage_slots_attribute_anthropic_provider_to_claude(self) -> None:
        self._write_facts([self._claude_fact(agent="unknown", ai_provider="anthropic")])

        snapshot = self._build()

        self.assertEqual(self._slot(snapshot, "claude")["usage"]["total_tokens"], 1800)

    def test_unattributable_usage_is_reported_instead_of_silently_missing(self) -> None:
        """没有 canonical provider、agent 又是聚合名时，不能静默读成「Claude 没有用量」。"""
        legacy_all = UsageItem(
            source_id="mac-local",
            machine="macbook",
            account="wang",
            agent="all",
            date=self.date_str,
            input_tokens=1000,
            output_tokens=500,
            cache_creation_tokens=100,
            cache_read_tokens=200,
            total_tokens=1800,
            total_cost=None,
            metadata={"machine": "macbook", "account": "wang"},
            model_breakdowns=[],
        )
        self._write_facts([], items=[legacy_all])

        snapshot = self._build()

        self.assertEqual(snapshot["summary"]["total_tokens"], 1800)
        self.assertEqual(self._slot(snapshot, "claude")["usage"]["status"], "missing")
        self.assertEqual(
            snapshot["provider_usage_coverage"],
            {
                "status": "partial",
                "total_tokens": 1800,
                "attributed_tokens": 0,
                "other_provider_tokens": 0,
                "unattributed_tokens": 1800,
            },
        )

    def test_provider_usage_coverage_accounts_for_every_summary_token(self) -> None:
        legacy_all = UsageItem(
            source_id="linux-server",
            machine="ubuntu-node",
            account="root",
            agent="all",
            date=self.date_str,
            input_tokens=200,
            output_tokens=100,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=300,
            total_cost=None,
            metadata={"machine": "ubuntu-node", "account": "root"},
            model_breakdowns=[],
        )
        self._write_facts(
            [
                self._claude_fact(agent="all"),
                self._claude_fact(agent="antigravity", ai_provider="antigravity"),
            ],
            items=[legacy_all],
        )

        snapshot = self._build()
        coverage = snapshot["provider_usage_coverage"]

        slot_tokens = sum(row["usage"]["total_tokens"] for row in snapshot["provider_slots"])

        self.assertEqual(coverage["total_tokens"], snapshot["summary"]["total_tokens"])
        # 要守的不变量是：用户能看到的（槽位之和）+ 明确点名的余量 == 总量。
        # attributed_tokens 必须就是槽位之和，任何进不了槽位的 token 都要被单独点名。
        self.assertEqual(coverage["attributed_tokens"], slot_tokens)
        self.assertEqual(
            slot_tokens + coverage["other_provider_tokens"] + coverage["unattributed_tokens"],
            snapshot["summary"]["total_tokens"],
        )
        self.assertEqual(coverage["other_provider_tokens"], 1800)
        self.assertEqual(coverage["unattributed_tokens"], 300)
        self.assertEqual(coverage["status"], "partial")
        self.assertEqual(self._slot(snapshot, "claude")["usage"]["total_tokens"], 1800)

    def test_third_party_provider_usage_is_named_instead_of_hidden_in_attributed(self) -> None:
        """antigravity 有 canonical provider 但没有固定槽位，不能藏进 attributed 里当作已展示。"""
        self._write_facts([
            self._claude_fact(agent="claude"),
            self._claude_fact(agent="antigravity", ai_provider="antigravity"),
        ])

        snapshot = self._build()
        coverage = snapshot["provider_usage_coverage"]
        slot_tokens = sum(row["usage"]["total_tokens"] for row in snapshot["provider_slots"])

        self.assertEqual(snapshot["summary"]["total_tokens"], 3600)
        self.assertEqual(slot_tokens, 1800)
        self.assertEqual(coverage["attributed_tokens"], 1800)
        self.assertEqual(coverage["other_provider_tokens"], 1800)
        self.assertEqual(coverage["unattributed_tokens"], 0)
        self.assertEqual(coverage["status"], "partial")
        self.assertEqual(
            slot_tokens + coverage["other_provider_tokens"] + coverage["unattributed_tokens"],
            snapshot["summary"]["total_tokens"],
        )

    def test_naive_limit_timestamps_fail_closed_instead_of_crashing(self) -> None:
        """缺时区的 reset_at / observed_at 无法判断新鲜度，必须 fail closed 而不是让 /api/summary 500。"""
        self._write_usage([self._claude_item()])
        write_limit_windows(
            self.db_path,
            [
                LimitWindow(
                    provider="claude",
                    source_id="claude-main",
                    window="week",
                    used_percent=78.25,
                    remaining_percent=21.75,
                    reset_at="2026-06-09T00:00:00",
                    window_duration_minutes=10080,
                    observed_at="2026-06-01T10:46:00",
                    source_type="oauth_usage_api",
                    confidence="observed",
                    status="ok",
                ),
            ],
            seen_at="2026-06-01T10:46:00",
        )

        snapshot = self._build()
        claude = self._slot(snapshot, "claude")

        self.assertEqual(claude["usage"]["total_tokens"], 1800)
        self.assertEqual(claude["quota"]["status"], "missing")
        serialized = json.dumps(claude["quota"], sort_keys=True)
        for leaked in ("used_percent", "remaining_percent", "reset_at", "78.25"):
            self.assertNotIn(leaked, serialized)
