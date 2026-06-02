from __future__ import annotations

import os
import json
import sqlite3
import tempfile
import unittest

from ai_usage_widget.models import UsageBlockItem, UsageHourlyItem, UsageItem
from ai_usage_widget.storage_sqlite import write_sqlite, _safe_error


class TestStorageSQLiteWAL(unittest.TestCase):
    def setUp(self) -> None:
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".sqlite")
        self.collected_at = "2026-06-01T10:50:00+08:00"
        self.timezone = "Asia/Shanghai"

        self.test_items = [
            UsageItem(
                source_id="mac-local",
                machine="macbook-pro",
                account="wangzhipeng",
                agent="claude",
                date="2026-06-01",
                input_tokens=1000,
                output_tokens=500,
                cache_creation_tokens=100,
                cache_read_tokens=200,
                total_tokens=1800,
                total_cost=0.05,
                metadata={"test": True},
                model_breakdowns=[
                    {
                        "model_name": "claude-sonnet-4-6",
                        "input_tokens": 1000,
                        "output_tokens": 500,
                        "cache_creation_tokens": 100,
                        "cache_read_tokens": 200,
                        "total_tokens": 1800,
                        "cost": 0.05
                    }
                ]
            )
        ]

    def tearDown(self) -> None:
        os.close(self.db_fd)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_sqlite_wal_mode_and_timeout(self) -> None:
        """验证 SQLite 成功启用 WAL 模式"""
        write_sqlite(
            path=self.db_path,
            collected_at=self.collected_at,
            timezone=self.timezone,
            run_status="success",
            source_reports=[],
            items=self.test_items
        )

        with sqlite3.connect(self.db_path) as conn:
            # 校验 journal_mode 为 wal
            cursor = conn.execute("PRAGMA journal_mode;")
            mode = cursor.fetchone()[0]
            self.assertEqual(mode.lower(), "wal")

    def test_sqlite_upsert_idempotency(self) -> None:
        """验证多次写入相同的 source_id + date + agent 时，只进行 Upsert 覆盖，而不增加记录行"""
        # 第一次写入
        write_sqlite(
            path=self.db_path,
            collected_at=self.collected_at,
            timezone=self.timezone,
            run_status="success",
            source_reports=[],
            items=self.test_items
        )

        # 第二次写入（更新 tokens）
        updated_items = [
            UsageItem(
                source_id="mac-local",
                machine="macbook-pro",
                account="wangzhipeng",
                agent="claude",
                date="2026-06-01",
                input_tokens=2000,  # 增大一倍
                output_tokens=1000,
                cache_creation_tokens=100,
                cache_read_tokens=200,
                total_tokens=3300,
                total_cost=0.10,
                metadata={"test": True, "updated": True},
                model_breakdowns=[
                    {
                        "model_name": "claude-sonnet-4-6",
                        "input_tokens": 2000,
                        "output_tokens": 1000,
                        "cache_creation_tokens": 100,
                        "cache_read_tokens": 200,
                        "total_tokens": 3300,
                        "cost": 0.10
                    }
                ]
            )
        ]

        write_sqlite(
            path=self.db_path,
            collected_at=self.collected_at,
            timezone=self.timezone,
            run_status="success",
            source_reports=[],
            items=updated_items
        )

        # 查询数据库，记录总数应该依然为 1，但数值为更新后的值
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT count(*) FROM usage_daily;")
            count = cursor.fetchone()[0]
            self.assertEqual(count, 1)

            cursor = conn.execute("SELECT input_tokens, total_cost, metadata_json FROM usage_daily;")
            row = cursor.fetchone()
            self.assertEqual(row[0], 2000)
            self.assertEqual(row[1], 0.10)
            self.assertIn("updated", row[2])

    def test_safe_error_sanitization(self) -> None:
        """测试错误信息安全脱敏与截断"""
        msg_with_paths = "Error at /Users/wangzhipeng/Documents/project/file.py line 12: Connection failed with token admin-123"
        sanitized = _safe_error(msg_with_paths)
        self.assertNotIn("wangzhipeng", sanitized)
        self.assertIn("/Users/<user>/", sanitized)
        self.assertNotIn("admin-123", sanitized)
        self.assertIn("token=***", sanitized)

        # 测试长度截断
        long_msg = "x" * 1000
        self.assertEqual(len(_safe_error(long_msg)), 500)

    def test_sqlite_preserves_structured_ccusage_raw_json(self) -> None:
        """验证 SQLite 保存 ccusage 原始结构化 row/model JSON，便于后端后续统一验算"""
        item = UsageItem(
            source_id="mac-local",
            machine="macbook",
            account="wang",
            agent="claude",
            date="2026-06-01",
            input_tokens=100,
            output_tokens=20,
            cache_creation_tokens=0,
            cache_read_tokens=0,
            total_tokens=120,
            metadata={
                "machine": "macbook",
                "account": "wang",
                "ccusage_row": {"modelsUsed": ["opus"], "customDetail": {"kept": True}},
            },
            model_breakdowns=[
                {
                    "model_name": "opus",
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "total_tokens": 120,
                    "cost": None,
                    "raw": {"vendorExtra": "preserve-me"},
                }
            ],
        )

        write_sqlite(
            path=self.db_path,
            collected_at=self.collected_at,
            timezone=self.timezone,
            run_status="ok",
            source_reports=[],
            items=[item],
        )

        with sqlite3.connect(self.db_path) as conn:
            daily_raw = conn.execute("SELECT raw_json FROM usage_daily").fetchone()[0]
            model_raw = conn.execute("SELECT raw_json FROM usage_daily_models").fetchone()[0]

        self.assertEqual(json.loads(daily_raw)["modelsUsed"], ["opus"])
        self.assertEqual(json.loads(model_raw)["vendorExtra"], "preserve-me")

    def test_sqlite_preserves_hourly_usage_and_raw_session_json(self) -> None:
        """验证 SQLite 保存按小时 usage facts 以及 ccusage session 原始行"""
        hourly_item = UsageHourlyItem(
            source_id="mac-local",
            machine="macbook",
            account="wang",
            agent="claude",
            hour="2026-06-01T09:00:00+08:00",
            input_tokens=100,
            output_tokens=20,
            cache_creation_tokens=3,
            cache_read_tokens=7,
            total_tokens=130,
            total_cost=0.01,
            metadata={
                "machine": "macbook",
                "account": "wang",
                "ccusage_session_row": {"sessionId": "s1", "metadata": {"lastActivity": "2026-06-01T09:12:00+08:00"}},
            },
        )

        write_sqlite(
            path=self.db_path,
            collected_at=self.collected_at,
            timezone=self.timezone,
            run_status="ok",
            source_reports=[],
            items=[],
            hourly_items=[hourly_item],
        )

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT hour, input_tokens, output_tokens, cache_creation_tokens,
                       cache_read_tokens, total_tokens, raw_json
                FROM usage_hourly
                """
            ).fetchone()

        self.assertEqual(row[0], "2026-06-01T09:00:00+08:00")
        self.assertEqual(row[1:6], (100, 20, 3, 7, 130))
        self.assertEqual(json.loads(row[6])["sessionId"], "s1")

    def test_sqlite_preserves_block_usage_and_raw_block_json(self) -> None:
        """验证 SQLite 保存 ccusage blocks 时间窗口事实"""
        block_item = UsageBlockItem(
            source_id="mac-local",
            machine="macbook",
            account="wang",
            agent="claude",
            start_time="2026-06-01T05:00:00+08:00",
            end_time="2026-06-01T09:50:00+08:00",
            input_tokens=100,
            output_tokens=20,
            cache_creation_tokens=30,
            cache_read_tokens=850,
            total_tokens=1000,
            total_cost=0.1,
            metadata={
                "machine": "macbook",
                "account": "wang",
                "ccusage_block_row": {"id": "2026-05-31T21:00:00.000Z", "models": ["claude-opus"]},
            },
        )

        write_sqlite(
            path=self.db_path,
            collected_at=self.collected_at,
            timezone=self.timezone,
            run_status="ok",
            source_reports=[],
            items=[],
            block_items=[block_item],
        )

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT start_time, end_time, input_tokens, output_tokens,
                       cache_creation_tokens, cache_read_tokens, total_tokens, raw_json
                FROM usage_blocks
                """
            ).fetchone()

        self.assertEqual(row[0], "2026-06-01T05:00:00+08:00")
        self.assertEqual(row[1], "2026-06-01T09:50:00+08:00")
        self.assertEqual(row[2:7], (100, 20, 30, 850, 1000))
        self.assertEqual(json.loads(row[7])["models"], ["claude-opus"])
