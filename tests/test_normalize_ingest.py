from __future__ import annotations

import unittest

from ai_usage_widget.ingest import IngestRequest
from ai_usage_widget.models import UsageItem
from ai_usage_widget.normalize import normalize_ingest_block_request, normalize_ingest_hourly_request, normalize_ingest_request, merge_usage_items


class TestNormalizeIngestIdempotency(unittest.TestCase):
    def setUp(self) -> None:
        # 准备一个包含重复和更新条目的 IngestRequest 模拟数据
        self.request = IngestRequest(
            schema_version=1,
            source_id="mac-local",
            host="macbook-pro",
            os_user="wangzhipeng",
            platform="darwin",
            timezone="Asia/Shanghai",
            observed_at="2026-06-01T10:40:00+08:00",
            collection_window="daily",
            usage_daily=[
                {
                    "agent": "claude",
                    "period": "2026-06-01",
                    "inputTokens": 1000,
                    "outputTokens": 500,
                    "cacheCreationTokens": 0,
                    "cacheReadTokens": 0,
                    "totalTokens": 1500,
                    "modelBreakdowns": [
                        {
                            "modelName": "claude-sonnet-4-6",
                            "inputTokens": 1000,
                            "outputTokens": 500,
                        }
                    ]
                },
                # 重复的数据行（agent、period 和 model 均相同，但数值有更新）
                {
                    "agent": "claude",
                    "period": "2026-06-01",
                    "inputTokens": 2000,  # 数值增大，表示更新
                    "outputTokens": 1000,
                    "cacheCreationTokens": 0,
                    "cacheReadTokens": 0,
                    "totalTokens": 3000,
                    "modelBreakdowns": [
                        {
                            "modelName": "claude-sonnet-4-6",
                            "inputTokens": 2000,
                            "outputTokens": 1000,
                        }
                    ]
                }
            ]
        )

    def test_normalize_and_deduplicate_single_payload(self) -> None:
        """测试在单个 Payload 解析时，自动合并相同的 key，且后面覆盖前面"""
        items = normalize_ingest_request(self.request)
        # 虽然 usage_daily 有两个条目，但因为 agent + period + modelName 重合，去重后应该只产出 1 个 item
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.source_id, "mac-local")
        self.assertEqual(item.date, "2026-06-01")
        self.assertEqual(item.agent, "claude")
        self.assertEqual(item.input_tokens, 2000)  # 应覆盖为后面的更新值 2000
        self.assertEqual(item.output_tokens, 1000)

    def test_full_ccusage_report_is_used_and_preserved(self) -> None:
        """测试后端从完整 ccusage report 统一归一化，并保留结构化明细"""
        request = IngestRequest(
            schema_version=1,
            source_id="mac-local",
            host="macbook-pro",
            os_user="wangzhipeng",
            platform="darwin",
            timezone="Asia/Shanghai",
            observed_at="2026-06-01T10:40:00+08:00",
            collection_window="daily",
            usage_daily=[],
            ccusage_daily_report={
                "daily": [
                    {
                        "agent": "claude",
                        "period": "2026-06-01",
                        "inputTokens": 100,
                        "outputTokens": 20,
                        "modelsUsed": ["claude-opus"],
                        "customDetail": {"kept": True},
                        "modelBreakdowns": [
                            {
                                "modelName": "claude-opus",
                                "inputTokens": 100,
                                "outputTokens": 20,
                                "vendorExtra": "preserve-me",
                            }
                        ],
                    }
                ],
                "totals": {"totalTokens": 120},
            },
        )

        items = normalize_ingest_request(request)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.total_tokens, 120)
        self.assertEqual(item.metadata["ccusage_totals"], {"totalTokens": 120})
        self.assertEqual(item.metadata["ccusage_row"]["modelsUsed"], ["claude-opus"])
        self.assertEqual(item.metadata["ccusage_row"]["customDetail"], {"kept": True})
        self.assertEqual(item.model_breakdowns[0]["raw"]["vendorExtra"], "preserve-me")

    def test_full_ccusage_session_report_normalizes_hourly_usage(self) -> None:
        """测试后端从完整 ccusage session report 生成按小时聚合事实，并保留原始 session row"""
        request = IngestRequest(
            schema_version=1,
            source_id="mac-local",
            host="macbook-pro",
            os_user="wangzhipeng",
            platform="darwin",
            timezone="Asia/Shanghai",
            observed_at="2026-06-01T10:40:00+08:00",
            collection_window="daily",
            usage_daily=[],
            ccusage_session_report={
                "session": [
                    {
                        "agent": "claude",
                        "inputTokens": 100,
                        "outputTokens": 20,
                        "cacheReadTokens": 5,
                        "totalTokens": 125,
                        "metadata": {"lastActivity": "2026-06-01T09:15:20+08:00", "project": "alpha"},
                    },
                    {
                        "agent": "claude",
                        "inputTokens": 40,
                        "outputTokens": 10,
                        "cacheCreationTokens": 2,
                        "totalTokens": 52,
                        "metadata": {"lastActivity": "2026-06-01T09:47:00+08:00", "project": "beta"},
                    },
                    {
                        "agent": "codex",
                        "inputTokens": 7,
                        "outputTokens": 3,
                        "totalTokens": 10,
                        "metadata": {"lastActivity": "2026-06-01T10:01:00+08:00"},
                    },
                ],
            },
        )

        hourly = sorted(normalize_ingest_hourly_request(request), key=lambda item: (item.hour, item.agent))

        self.assertEqual(len(hourly), 2)
        claude = hourly[0]
        self.assertEqual(claude.source_id, "mac-local")
        self.assertEqual(claude.machine, "macbook-pro")
        self.assertEqual(claude.account, "wangzhipeng")
        self.assertEqual(claude.agent, "claude")
        self.assertEqual(claude.hour, "2026-06-01T09:00:00+08:00")
        self.assertEqual(claude.input_tokens, 140)
        self.assertEqual(claude.output_tokens, 30)
        self.assertEqual(claude.cache_creation_tokens, 2)
        self.assertEqual(claude.cache_read_tokens, 5)
        self.assertEqual(claude.total_tokens, 177)
        self.assertEqual(claude.metadata["machine"], "macbook-pro")
        self.assertEqual(claude.metadata["account"], "wangzhipeng")
        self.assertEqual(claude.metadata["ccusage_session_row"]["metadata"]["project"], "alpha")

        codex = hourly[1]
        self.assertEqual(codex.hour, "2026-06-01T10:00:00+08:00")
        self.assertEqual(codex.total_tokens, 10)

    def test_ingest_machine_name_overrides_network_host_for_display(self) -> None:
        """展示机器名使用 payload.machine，网络 host 仅作为来源元数据保留"""
        request = IngestRequest(
            schema_version=1,
            source_id="linux-ai-wang",
            host="ai.chunbai.com",
            machine="VM-0-3-ubuntu",
            os_user="wang",
            platform="linux",
            timezone="Asia/Shanghai",
            observed_at="2026-06-01T10:40:00+08:00",
            collection_window="daily",
            usage_daily=[
                {
                    "agent": "claude",
                    "period": "2026-06-01",
                    "inputTokens": 100,
                    "totalTokens": 100,
                }
            ],
        )

        items = normalize_ingest_request(request)

        self.assertEqual(items[0].machine, "VM-0-3-ubuntu")
        self.assertEqual(items[0].metadata["machine"], "VM-0-3-ubuntu")
        self.assertEqual(items[0].metadata["host"], "ai.chunbai.com")

    def test_full_ccusage_blocks_report_normalizes_block_windows(self) -> None:
        """测试后端从 ccusage blocks 生成带起止时间的窗口事实"""
        request = IngestRequest(
            schema_version=1,
            source_id="mac-local",
            host="macbook-pro",
            os_user="wangzhipeng",
            platform="darwin",
            timezone="Asia/Shanghai",
            observed_at="2026-06-01T10:40:00+08:00",
            collection_window="daily",
            usage_daily=[],
            ccusage_blocks_report={
                "blocks": [
                    {
                        "startTime": "2026-05-31T21:00:00.000Z",
                        "endTime": "2026-06-01T02:00:00.000Z",
                        "actualEndTime": "2026-06-01T01:50:00.000Z",
                        "isGap": False,
                        "models": ["claude-opus-4-8"],
                        "tokenCounts": {
                            "inputTokens": 100,
                            "outputTokens": 20,
                            "cacheCreationInputTokens": 30,
                            "cacheReadInputTokens": 850,
                        },
                        "totalTokens": 1000,
                        "costUSD": 0.1,
                    },
                    {
                        "startTime": "2026-06-01T02:00:00.000Z",
                        "endTime": "2026-06-01T07:00:00.000Z",
                        "isGap": True,
                        "totalTokens": 999,
                    },
                ],
            },
        )

        blocks = normalize_ingest_block_request(request)

        self.assertEqual(len(blocks), 1)
        block = blocks[0]
        self.assertEqual(block.source_id, "mac-local")
        self.assertEqual(block.machine, "macbook-pro")
        self.assertEqual(block.account, "wangzhipeng")
        self.assertEqual(block.agent, "claude")
        self.assertEqual(block.start_time, "2026-06-01T05:00:00+08:00")
        self.assertEqual(block.end_time, "2026-06-01T09:50:00+08:00")
        self.assertEqual(block.cache_read_tokens, 850)
        self.assertEqual(block.total_tokens, 1000)
        self.assertEqual(block.metadata["ccusage_block_row"]["models"], ["claude-opus-4-8"])

    def test_merge_multiple_requests_idempotency(self) -> None:
        """测试跨请求多次 Push 时，通过 merge_usage_items 实现基于稳定 Key 的幂等 Upsert"""
        existing_items = [
            UsageItem(
                source_id="mac-local",
                machine="macbook-pro",
                account="wangzhipeng",
                agent="claude",
                date="2026-06-01",
                input_tokens=1000,
                output_tokens=500,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                total_tokens=1500,
                model_breakdowns=[{"model_name": "claude-sonnet-4-6", "input_tokens": 1000, "output_tokens": 500}]
            ),
            UsageItem(
                source_id="linux-server",
                machine="ubuntu",
                account="root",
                agent="codex",
                date="2026-06-01",
                input_tokens=800,
                output_tokens=400,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                total_tokens=1200,
                model_breakdowns=[{"model_name": "gpt-5.5", "input_tokens": 800, "output_tokens": 400}]
            )
        ]

        new_items = [
            # 这是一个对 mac-local 相同天的更新数据
            UsageItem(
                source_id="mac-local",
                machine="macbook-pro",
                account="wangzhipeng",
                agent="claude",
                date="2026-06-01",
                input_tokens=3000,
                output_tokens=1500,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                total_tokens=4500,
                model_breakdowns=[{"model_name": "claude-sonnet-4-6", "input_tokens": 3000, "output_tokens": 1500}]
            )
        ]

        merged = merge_usage_items(existing_items, new_items)
        # 数量依然为 2（覆盖了一个，另一个保持不变）
        self.assertEqual(len(merged), 2)

        # 查找被更新的项目并校验值已修改
        mac_item = next(x for x in merged if x.source_id == "mac-local")
        self.assertEqual(mac_item.input_tokens, 3000)
        self.assertEqual(mac_item.output_tokens, 1500)

        # 校验未改变的项目保持原样
        linux_item = next(x for x in merged if x.source_id == "linux-server")
        self.assertEqual(linux_item.input_tokens, 800)
