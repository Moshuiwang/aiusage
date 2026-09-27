from __future__ import annotations

import os
import json
import unittest
import io
import urllib.error
from unittest.mock import patch
from typing import Any, Dict

from dataclasses import replace

from pathlib import Path

from ai_usage_widget import version_contract
from ai_usage_widget.account_fingerprint import compute_account_fingerprint
from ai_usage_widget.config import DeviceConfig
from ai_usage_widget.models import CommandResult
from ai_usage_widget.pusher import (
    DevicePusher,
    IngestHTTPClient,
    _account_observations,
    _facts_digest,
    _usage_hourly_facts_from_mswusage,
)

FIXTURES = Path(__file__).parent / "fixtures"


class FakeExecutor:
    def __init__(self, result: CommandResult | list[CommandResult]) -> None:
        self.results = result if isinstance(result, list) else [result]
        self.calls = []
        self.last_argv = None
        self.last_timeout = None

    def __call__(self, argv: list[str], timeout: float) -> CommandResult:
        self.calls.append(argv)
        self.last_argv = argv
        self.last_timeout = timeout
        index = min(len(self.calls) - 1, len(self.results) - 1)
        return self.results[index]


class FakeHTTPClient(IngestHTTPClient):
    def __init__(self, status_code: int, response_data: dict, raise_exc: Exception | None = None) -> None:
        self.status_code = status_code
        self.response_data = response_data
        self.raise_exc = raise_exc
        self.last_url = None
        self.last_json = None
        self.last_headers = None

    def post(self, url: str, data: dict, headers: dict, timeout: float) -> tuple[int, dict]:
        self.last_url = url
        self.last_json = data
        self.last_headers = headers
        if self.raise_exc:
            raise self.raise_exc
        return self.status_code, self.response_data


class FlakyHTTPClient(IngestHTTPClient):
    def __init__(self, results: list[Exception | tuple[int, dict]]) -> None:
        self.results = results
        self.calls = 0
        self.last_json = None

    def post(self, url: str, data: dict, headers: dict, timeout: float) -> tuple[int, dict]:
        self.calls += 1
        self.last_json = data
        result = self.results[min(self.calls - 1, len(self.results) - 1)]
        if isinstance(result, Exception):
            raise result
        return result


class TestDevicePusherFakeHTTP(unittest.TestCase):
    def setUp(self) -> None:
        self.config = DeviceConfig(
            schema_version=1,
            source_id="mac-local",
            host="macbook-pro.local",
            machine="macbook-pro",
            os_user="wangzhipeng",
            platform="darwin",
            timezone="Asia/Shanghai",
            server_url="http://localhost:8000/ingest",
            timeout_seconds=30,
            token_env="AI_USAGE_TOKEN"
        )
        # 设一个环境变量模拟 Token
        os.environ["AI_USAGE_TOKEN"] = "test-token-123"

    def tearDown(self) -> None:
        if "AI_USAGE_TOKEN" in os.environ:
            del os.environ["AI_USAGE_TOKEN"]

    def test_full_rescan_facts_are_limited_to_declared_coverage(self) -> None:
        report = {
            "provenance": "mswusage_codex_token_count",
            "generated_at": "2026-07-18T10:00:00+08:00",
            "collector": {
                "mode": "full-rescan",
                "coverage": {"start": "2026-07-12T00:00:00+08:00", "end": "2026-07-13T00:00:00+08:00"},
            },
            "hourly": [
                {"hour": "2026-07-11T23:00:00+08:00", "total_tokens": 999},
                {"hour": "2026-07-12T08:00:00+08:00", "total_tokens": 100},
            ],
        }

        facts = _usage_hourly_facts_from_mswusage(self.config, report)

        self.assertEqual([fact["window_start"] for fact in facts], ["2026-07-12T08:00:00+08:00"])

    def test_facts_digest_uses_utf8_canonical_json(self) -> None:
        fact = {
            "fact_id": "事实:中文账号",
            "agent": "codex",
            "client": "codex",
            "window_start": "2026-07-12T08:00:00+08:00",
            "window_end": "2026-07-12T09:00:00+08:00",
            "usage": {"total_tokens": 1},
            "event_count": 1,
            "session_count": 1,
            "attribution_confidence": "confirmed",
            "provenance": "mswusage_codex_token_count",
        }

        digest = _facts_digest([fact], {"coverage": {"start": None, "end": None}})

        self.assertEqual(digest, "4d8a3fd8150a43afd055d1fcc6d31c0932841e2ca814ca033d424f3b60ee3ec0")

    def test_pusher_success_flow(self) -> None:
        """测试正常流：ccusage 采集成功且 HTTP 上报成功"""
        ccusage_stdout = '{"daily": [{"period": "2026-06-01", "agent": "claude", "inputTokens": 100, "modelsUsed": ["opus"]}], "totals": {"totalTokens": 100}, "extra": {"kept": true}}'
        executor = FakeExecutor([
            CommandResult(stdout=ccusage_stdout, exit_code=0),
            CommandResult(stdout='{"session": []}', exit_code=0),
            CommandResult(stdout='{"schema_version": 1, "source": "mswusage_codex", "timezone": "Asia/Shanghai", "generated_at": "2026-06-05T09:00:00+08:00", "provenance": "mswusage_codex_token_count", "daily": [], "hourly": [], "sessions": []}', exit_code=0),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted", "source_id": "mac-local"})

        pusher = DevicePusher(self.config, executor=executor, http_client=http_client)
        result = pusher.push()

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "accepted")
        # 校验 HTTP 头部携带 Bearer Token
        self.assertEqual(http_client.last_headers.get("Authorization"), "Bearer test-token-123")
        self.assertEqual(http_client.last_headers.get("User-Agent"), "AIUsagePusher/1.0")
        # 校验采集时使用了正确的参数
        self.assertIn("ccusage", executor.calls[0][0])
        self.assertIn("daily", executor.calls[0])
        self.assertIn("session", executor.calls[1])
        # #91：`ccusage blocks` 已停采，session 之后直接进账本采集。
        self.assertIn("mswusage-codex", executor.calls[2])
        self.assertEqual(http_client.last_json["ccusage_daily_report"]["totals"]["totalTokens"], 100)
        self.assertEqual(http_client.last_json["host"], "macbook-pro.local")
        self.assertEqual(http_client.last_json["machine"], "macbook-pro")
        self.assertEqual(http_client.last_json["ccusage_daily_report"]["extra"], {"kept": True})
        self.assertEqual(http_client.last_json["usage_daily"][0]["modelsUsed"], ["opus"])
        self.assertEqual(http_client.last_json["ccusage_session_report"]["session"], [])
        self.assertEqual(http_client.last_json["mswusage_codex_hourly_report"]["source"], "mswusage_codex")

    def test_pusher_adds_mswusage_codex_report_and_drift_status(self) -> None:
        daily_stdout = '{"daily": [{"period": "2026-06-05", "agent": "codex", "inputTokens": 100, "outputTokens": 20, "cacheReadTokens": 30, "totalTokens": 150}]}'
        mswusage_stdout = json.dumps({
            "schema_version": 1,
            "source": "mswusage_codex",
            "timezone": "Asia/Shanghai",
            "generated_at": "2026-06-05T09:00:00+08:00",
            "provenance": "mswusage_codex_token_count",
            "daily": [
                {"date": "2026-06-04", "agent": "codex", "total_tokens": 999999},
                {"date": "2026-06-05", "agent": "codex", "total_tokens": 149},
            ],
            "hourly": [],
            "sessions": [],
        })
        executor = FakeExecutor([
            CommandResult(stdout=daily_stdout, exit_code=0),
            CommandResult(stdout='{"session": []}', exit_code=0),
            CommandResult(stdout=mswusage_stdout, exit_code=0),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted"})

        result = DevicePusher(self.config, executor=executor, http_client=http_client).push()

        self.assertTrue(result["success"])
        report = http_client.last_json["mswusage_codex_hourly_report"]
        self.assertEqual(report["provenance"], "mswusage_codex_token_count")
        self.assertEqual(report["drift"]["status"], "ok")
        self.assertEqual(report["drift"]["daily_codex_total_tokens"], 150)
        self.assertEqual(report["drift"]["mswusage_codex_total_tokens"], 149)
        self.assertEqual(report["drift"]["comparison_dates"], ["2026-06-05"])

    def test_pusher_adds_account_hourly_facts_when_codex_account_is_configured(self) -> None:
        self.config.ai_accounts = {
            "codex": {
                "provider": "openai",
                "account_id": "acct-main",
                "label": "start@example.com",
                "display_name": "StarTimes",
            }
        }
        daily_stdout = '{"daily": [{"period": "2026-06-11", "agent": "codex", "totalTokens": 155}]}'
        mswusage_stdout = json.dumps({
            "schema_version": 1,
            "source": "mswusage_codex",
            "timezone": "Asia/Shanghai",
            "generated_at": "2026-06-11T14:00:00+08:00",
            "provenance": "mswusage_codex_token_count",
            "daily": [{"date": "2026-06-11", "agent": "codex", "total_tokens": 155}],
            "hourly": [
                {
                    "hour": "2026-06-11T13:00:00+08:00",
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 30,
                    "reasoning_output_tokens": 5,
                    "total_tokens": 155,
                    "event_count": 2,
                    "session_count": 1,
                }
            ],
            "sessions": [],
        })
        executor = FakeExecutor([
            CommandResult(stdout=daily_stdout, exit_code=0),
            CommandResult(stdout='{"session": []}', exit_code=0),
            CommandResult(stdout=mswusage_stdout, exit_code=0),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted"})

        result = DevicePusher(self.config, executor=executor, http_client=http_client).push()

        self.assertTrue(result["success"])
        facts = http_client.last_json["usage_hourly_facts"]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["ai_account"]["label"], "start@example.com")
        self.assertEqual(facts[0]["usage"]["total_tokens"], 155)
        self.assertEqual(facts[0]["window_end"], "2026-06-11T14:00:00+08:00")

    def test_pusher_adds_top_level_account_observation_when_source_path_configured(self) -> None:
        """#181 P1-1：配置了 account_fingerprint_sources.codex 之后，指纹只出现在 payload
        顶层一条「账户观察」记录里（本次读取时刻观察到该账户），绝不逐条写进每个
        usage_hourly_facts[].ai_account——否则账户切换后，full-rescan 会把旧账户期间的
        历史 token 全部标成新账户（Codex #185 review P1-1）。
        """
        self.config.account_fingerprint_sources = {
            "codex": str(FIXTURES / "codex_account_auth_sample.json"),
        }
        daily_stdout = '{"daily": [{"period": "2026-06-11", "agent": "codex", "totalTokens": 155}]}'
        mswusage_stdout = json.dumps({
            "schema_version": 1,
            "source": "mswusage_codex",
            "timezone": "Asia/Shanghai",
            "generated_at": "2026-06-11T14:00:00+08:00",
            "provenance": "mswusage_codex_token_count",
            "daily": [{"date": "2026-06-11", "agent": "codex", "total_tokens": 155}],
            "hourly": [
                {
                    "hour": "2026-06-11T13:00:00+08:00",
                    "total_tokens": 155,
                    "event_count": 2,
                    "session_count": 1,
                },
                {
                    "hour": "2026-06-11T12:00:00+08:00",
                    "total_tokens": 50,
                    "event_count": 1,
                    "session_count": 1,
                },
            ],
            "sessions": [],
        })
        executor = FakeExecutor([
            CommandResult(stdout=daily_stdout, exit_code=0),
            CommandResult(stdout='{"session": []}', exit_code=0),
            CommandResult(stdout=mswusage_stdout, exit_code=0),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted"})

        result = DevicePusher(self.config, executor=executor, http_client=http_client).push()

        self.assertTrue(result["success"])
        payload = http_client.last_json
        facts = payload["usage_hourly_facts"]
        self.assertEqual(len(facts), 2)
        # 结构下限：每一条 fact 的 ai_account 都不含 account_fingerprint（不只查第一条）。
        for fact in facts:
            self.assertNotIn("account_fingerprint", fact["ai_account"])
        expected_fp = compute_account_fingerprint("codex", "33333333-3333-3333-3333-333333333333")
        observations = payload["account_observations"]
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["agent"], "codex")
        self.assertEqual(observations[0]["provider"], "codex")
        self.assertEqual(observations[0]["account_fingerprint"], expected_fp)
        # observed_at 是本次读取时刻，跟 payload 顶层的 observed_at 是同一个值——
        # 语义是"在这一刻观察到这个账户登录"，不是某条历史小时的窗口时间。
        self.assertEqual(observations[0]["observed_at"], payload["observed_at"])
        # fixture 里带着的 refresh token 原文绝不能出现在上报 payload 里的任何地方。
        payload_text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("codex-fixture-refresh-token-secret", payload_text)
        self.assertNotIn("codex-fixture-access-token", payload_text)

    def test_pusher_account_observations_absent_when_source_not_configured(self) -> None:
        """没配置 account_fingerprint_sources 时必须降级为「完全不写这个字段」，不猜、
        不报错、不中断采集——顶层 account_observations key 整个不出现，facts 里也从来
        不该出现 account_fingerprint（这条本来就不可能出现，只是确认没有回潮）。
        """
        daily_stdout = '{"daily": [{"period": "2026-06-11", "agent": "codex", "totalTokens": 10}]}'
        mswusage_stdout = json.dumps({
            "schema_version": 1,
            "source": "mswusage_codex",
            "timezone": "Asia/Shanghai",
            "generated_at": "2026-06-11T14:00:00+08:00",
            "provenance": "mswusage_codex_token_count",
            "daily": [{"date": "2026-06-11", "agent": "codex", "total_tokens": 10}],
            "hourly": [{"hour": "2026-06-11T13:00:00+08:00", "total_tokens": 10, "event_count": 1, "session_count": 1}],
            "sessions": [],
        })
        executor = FakeExecutor([
            CommandResult(stdout=daily_stdout, exit_code=0),
            CommandResult(stdout='{"session": []}', exit_code=0),
            CommandResult(stdout=mswusage_stdout, exit_code=0),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted"})

        result = DevicePusher(self.config, executor=executor, http_client=http_client).push()

        self.assertTrue(result["success"])
        payload = http_client.last_json
        self.assertNotIn("account_observations", payload)
        self.assertNotIn("account_fingerprint", payload["usage_hourly_facts"][0]["ai_account"])

    def test_pusher_account_observations_absent_when_source_path_unreadable(self) -> None:
        """反向路径：配置了 account_fingerprint_sources 指向的路径，但那份文件根本不存在
        （或读不出/解析不出）时，同样要降级为「完全不写 account_observations」——不能因为
        『配置过』这件事本身就在 payload 顶层留下一个空列表或者报错中断采集。
        """
        self.config.account_fingerprint_sources = {
            "codex": str(FIXTURES / "does_not_exist_codex_account.json"),
        }
        daily_stdout = '{"daily": [{"period": "2026-06-11", "agent": "codex", "totalTokens": 10}]}'
        mswusage_stdout = json.dumps({
            "schema_version": 1,
            "source": "mswusage_codex",
            "timezone": "Asia/Shanghai",
            "generated_at": "2026-06-11T14:00:00+08:00",
            "provenance": "mswusage_codex_token_count",
            "daily": [{"date": "2026-06-11", "agent": "codex", "total_tokens": 10}],
            "hourly": [{"hour": "2026-06-11T13:00:00+08:00", "total_tokens": 10, "event_count": 1, "session_count": 1}],
            "sessions": [],
        })
        executor = FakeExecutor([
            CommandResult(stdout=daily_stdout, exit_code=0),
            CommandResult(stdout='{"session": []}', exit_code=0),
            CommandResult(stdout=mswusage_stdout, exit_code=0),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted"})

        result = DevicePusher(self.config, executor=executor, http_client=http_client).push()

        self.assertTrue(result["success"])
        payload = http_client.last_json
        self.assertNotIn("account_observations", payload)

    def test_pusher_account_fingerprint_source_does_not_change_facts_at_all(self) -> None:
        """#181 关键不变量：account_fingerprint_sources 配置与否，绝不能改变任何一个
        usage_hourly_facts 条目（包括 fact_id 和整个 ai_account 子对象）——指纹信息
        现在完全走顶层 account_observations，跟逐条 fact 的计算路径正交。用整个 fact
        对象相等（不仅 fact_id）比较，覆盖"只挪了字段名字但还是塞进了 fact"这类绕过。
        """
        report = {
            "provenance": "mswusage_codex_token_count",
            "generated_at": "2026-06-11T14:00:00+08:00",
            "collector": {"mode": "incremental", "coverage": {"start": None, "end": None}},
            "hourly": [
                {"hour": "2026-06-11T13:00:00+08:00", "total_tokens": 10, "event_count": 1, "session_count": 1},
            ],
        }

        facts_without_source = _usage_hourly_facts_from_mswusage(self.config, report)

        self.config.account_fingerprint_sources = {
            "codex": str(FIXTURES / "codex_account_auth_sample.json"),
        }
        facts_with_source = _usage_hourly_facts_from_mswusage(self.config, report)

        self.assertEqual(facts_without_source, facts_with_source)
        self.assertNotIn("account_fingerprint", facts_with_source[0]["ai_account"])

    def test_pusher_account_observations_cover_multiple_configured_providers(self) -> None:
        """同时配置 claude 和 codex 两个 provider 的指纹来源时，account_observations
        必须各出一条，且 provider/agent 与指纹值互不串号——不是只测单 provider 路径。
        """
        self.config.account_fingerprint_sources = {
            "codex": str(FIXTURES / "codex_account_auth_sample.json"),
            "claude": str(FIXTURES / "claude_account_config_sample.json"),
        }

        observations = _account_observations(self.config, "2026-06-11T14:05:00+08:00")

        self.assertEqual(len(observations), 2)
        by_agent = {item["agent"]: item for item in observations}
        self.assertEqual(
            by_agent["codex"]["account_fingerprint"],
            compute_account_fingerprint("codex", "33333333-3333-3333-3333-333333333333"),
        )
        self.assertEqual(
            by_agent["claude"]["account_fingerprint"],
            compute_account_fingerprint("claude", "11111111-1111-1111-1111-111111111111"),
        )
        for item in observations:
            self.assertEqual(item["provider"], item["agent"])
            self.assertEqual(item["observed_at"], "2026-06-11T14:05:00+08:00")

    def test_pusher_sends_usage_ledger_facts_with_unconfirmed_attribution_without_ai_accounts(self) -> None:
        daily_stdout = '{"daily": []}'
        codex_stdout = json.dumps({
            "schema_version": 1,
            "source": "mswusage_codex",
            "timezone": "Asia/Shanghai",
            "generated_at": "2026-06-11T14:00:00+08:00",
            "provenance": "mswusage_codex_token_count",
            "daily": [{"date": "2026-06-11", "agent": "codex", "total_tokens": 155}],
            "hourly": [
                {
                    "hour": "2026-06-11T13:00:00+08:00",
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 30,
                    "reasoning_output_tokens": 5,
                    "total_tokens": 155,
                    "event_count": 2,
                    "session_count": 1,
                }
            ],
            "sessions": [],
        })
        claude_stdout = json.dumps({
            "schema_version": 1,
            "source": "mswusage_claude",
            "timezone": "Asia/Shanghai",
            "generated_at": "2026-06-11T14:00:00+08:00",
            "provenance": "mswusage_claude_assistant_usage",
            "daily": [{"date": "2026-06-11", "agent": "claude", "total_tokens": 77}],
            "hourly": [
                {
                    "hour": "2026-06-11T13:00:00+08:00",
                    "input_tokens": 70,
                    "output_tokens": 7,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "total_tokens": 77,
                    "event_count": 1,
                    "session_count": 0,
                }
            ],
            "sessions": [],
        })
        executor = FakeExecutor([
            CommandResult(stdout=daily_stdout, exit_code=0),
            CommandResult(stdout='{"session": []}', exit_code=0),
            CommandResult(stdout=codex_stdout, exit_code=0),
            CommandResult(stdout=claude_stdout, exit_code=0),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted"})

        result = DevicePusher(self.config, executor=executor, http_client=http_client).push()

        self.assertTrue(result["success"])
        facts = http_client.last_json["usage_hourly_facts"]
        self.assertEqual([fact["agent"] for fact in facts], ["codex", "claude"])
        self.assertEqual([fact["usage"]["total_tokens"] for fact in facts], [155, 77])
        self.assertEqual({fact["attribution_confidence"] for fact in facts}, {"unconfirmed_local_source"})
        self.assertEqual({fact["ai_account"]["label"] for fact in facts}, {"本机来源 / 未确认账号"})
        self.assertIn("mswusage-claude", executor.calls[3])

    def test_pusher_keeps_usage_ledger_push_when_ccusage_is_missing(self) -> None:
        codex_stdout = json.dumps({
            "schema_version": 1,
            "source": "mswusage_codex",
            "timezone": "Asia/Shanghai",
            "generated_at": "2026-06-11T14:00:00+08:00",
            "provenance": "mswusage_codex_token_count",
            "daily": [{"date": "2026-06-11", "agent": "codex", "total_tokens": 155}],
            "hourly": [
                {
                    "hour": "2026-06-11T13:00:00+08:00",
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 30,
                    "reasoning_output_tokens": 5,
                    "total_tokens": 155,
                    "event_count": 2,
                    "session_count": 1,
                }
            ],
            "sessions": [],
        })
        claude_stdout = json.dumps({
            "schema_version": 1,
            "source": "mswusage_claude",
            "timezone": "Asia/Shanghai",
            "generated_at": "2026-06-11T14:00:00+08:00",
            "provenance": "mswusage_claude_assistant_usage",
            "daily": [{"date": "2026-06-11", "agent": "claude", "total_tokens": 77}],
            "hourly": [
                {
                    "hour": "2026-06-11T13:00:00+08:00",
                    "input_tokens": 70,
                    "output_tokens": 7,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "total_tokens": 77,
                    "event_count": 1,
                    "session_count": 0,
                }
            ],
            "sessions": [],
        })
        executor = FakeExecutor([
            CommandResult(error_type="missing_tool", error_message="ccusage not found"),
            CommandResult(stdout=codex_stdout, exit_code=0),
            CommandResult(stdout=claude_stdout, exit_code=0),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted"})

        result = DevicePusher(self.config, executor=executor, http_client=http_client).push()

        self.assertTrue(result["success"])
        self.assertEqual(http_client.last_json["collection_status"], "ok")
        self.assertEqual(http_client.last_json["usage_daily"], [])
        # #78：ccusage 的失败说明不再作为字段上报（生产用的 Worker 不认识它，只会静默丢弃）。
        # 代价是这条路径上 ccusage 的失败原因彻底没有承载字段——payload 是 ok 且不带
        # error_type / error_message，这里一并钉死，免得代价被悄悄忘掉。
        self.assertNotIn("ccusage_daily_status", http_client.last_json)
        self.assertNotIn("error_type", http_client.last_json)
        self.assertNotIn("error_message", http_client.last_json)
        self.assertNotIn("ccusage_daily_report", http_client.last_json)
        self.assertNotIn("ccusage_session_report", http_client.last_json)
        # ccusage_blocks_report 不在这里断言：#91 后任何场景都不发它，在这条失败路径上
        # 断言它不存在是恒真的；全场景守卫在 test_collector_payload_contract 的
        # DROPPED_LEGACY_FIELDS（那边配了真实 payload 基座与变异证据）。
        self.assertIn("mswusage-codex", executor.calls[1])
        self.assertIn("mswusage-claude", executor.calls[2])
        self.assertEqual([fact["agent"] for fact in http_client.last_json["usage_hourly_facts"]], ["codex", "claude"])
        drift = http_client.last_json["mswusage_codex_hourly_report"]["drift"]
        self.assertEqual(drift["status"], "comparison_unavailable")
        self.assertEqual(drift["baseline_agent"], None)

    def test_pusher_can_run_usage_ledger_full_rescan_explicitly(self) -> None:
        daily_stdout = '{"daily": []}'
        empty_codex_report = json.dumps({
            "schema_version": 1,
            "source": "mswusage_codex",
            "timezone": "Asia/Shanghai",
            "generated_at": "2026-06-11T14:00:00+08:00",
            "provenance": "mswusage_codex_token_count",
            "daily": [],
            "hourly": [],
            "sessions": [],
            "collector": {
                "version": "0.1.0",
                "parser_schema_version": 2,
                "mode": "full-rescan",
                "lookback_hours": None,
                "coverage": {"start": None, "end": None},
                "counts": {"read_errors": 0, "unresolved_mismatch": 0},
                "scan_complete": True,
                "report_digest": "safe-digest-a",
            },
        })
        empty_claude_report = json.dumps({
            "schema_version": 1,
            "source": "mswusage_claude",
            "timezone": "Asia/Shanghai",
            "generated_at": "2026-06-11T14:00:00+08:00",
            "provenance": "mswusage_claude_assistant_usage",
            "daily": [],
            "hourly": [],
            "sessions": [],
        })
        executor = FakeExecutor([
            CommandResult(stdout=daily_stdout, exit_code=0),
            CommandResult(stdout='{"session": []}', exit_code=0),
            CommandResult(stdout=empty_codex_report, exit_code=0),
            CommandResult(stdout=empty_claude_report, exit_code=0),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted"})

        result = DevicePusher(
            self.config,
            executor=executor,
            http_client=http_client,
            ledger_mode="full-rescan",
            ledger_coverage_start="2026-07-12T00:00:00+08:00",
        ).push()

        self.assertTrue(result["success"])
        self.assertIn("mswusage-codex", executor.calls[2])
        self.assertIn("mswusage-claude", executor.calls[3])
        self.assertEqual(executor.calls[2][executor.calls[2].index("--mode") + 1], "full-rescan")
        self.assertEqual(executor.calls[3][executor.calls[3].index("--mode") + 1], "full-rescan")
        self.assertNotIn("--lookback-hours", executor.calls[2])
        self.assertNotIn("--lookback-hours", executor.calls[3])
        self.assertEqual(executor.calls[2][executor.calls[2].index("--coverage-start") + 1], "2026-07-12T00:00:00+08:00")
        self.assertEqual(executor.calls[3][executor.calls[3].index("--coverage-start") + 1], "2026-07-12T00:00:00+08:00")
        self.assertEqual(http_client.last_json["usage_ledger_runs"][0]["agent"], "codex")
        self.assertEqual(http_client.last_json["usage_ledger_runs"][0]["collector"]["report_digest"], "safe-digest-a")
        self.assertRegex(http_client.last_json["usage_ledger_runs"][0]["facts_digest"], r"^[0-9a-f]{64}$")

    def test_pusher_marks_drift_unavailable_without_matching_daily_codex_baseline(self) -> None:
        executor = FakeExecutor([
            CommandResult(stdout='{"daily": [{"period": "2026-06-05", "agent": "claude", "totalTokens": 150}]}', exit_code=0),
            CommandResult(stdout='{"session": []}', exit_code=0),
            CommandResult(stdout=json.dumps({
                "schema_version": 1,
                "source": "mswusage_codex",
                "timezone": "Asia/Shanghai",
                "generated_at": "2026-06-05T09:00:00+08:00",
                "provenance": "mswusage_codex_token_count",
                "daily": [{"date": "2026-06-05", "agent": "codex", "total_tokens": 149}],
                "hourly": [],
                "sessions": [],
            }), exit_code=0),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted"})

        result = DevicePusher(self.config, executor=executor, http_client=http_client).push()

        self.assertTrue(result["success"])
        drift = http_client.last_json["mswusage_codex_hourly_report"]["drift"]
        self.assertEqual(drift["status"], "comparison_unavailable")
        self.assertIsNone(drift["daily_codex_total_tokens"])
        self.assertIsNone(drift["mswusage_codex_total_tokens"])

    def test_pusher_uses_all_daily_row_as_codex_drift_baseline_when_codex_row_is_absent(self) -> None:
        executor = FakeExecutor([
            CommandResult(stdout='{"daily": [{"period": "2026-06-05", "agent": "all", "totalTokens": 150}]}', exit_code=0),
            CommandResult(stdout='{"session": []}', exit_code=0),
            CommandResult(stdout=json.dumps({
                "schema_version": 1,
                "source": "mswusage_codex",
                "timezone": "Asia/Shanghai",
                "generated_at": "2026-06-05T09:00:00+08:00",
                "provenance": "mswusage_codex_token_count",
                "daily": [{"date": "2026-06-05", "agent": "codex", "total_tokens": 149}],
                "hourly": [],
                "sessions": [],
            }), exit_code=0),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted"})

        result = DevicePusher(self.config, executor=executor, http_client=http_client).push()

        self.assertTrue(result["success"])
        drift = http_client.last_json["mswusage_codex_hourly_report"]["drift"]
        self.assertEqual(drift["status"], "ok")
        self.assertEqual(drift["daily_codex_total_tokens"], 150)
        self.assertEqual(drift["mswusage_codex_total_tokens"], 149)
        self.assertEqual(drift["baseline_agent"], "all")

    def test_pusher_keeps_daily_push_when_mswusage_codex_fails(self) -> None:
        executor = FakeExecutor([
            CommandResult(stdout='{"daily": [{"period": "2026-06-05", "agent": "codex", "totalTokens": 150}]}', exit_code=0),
            CommandResult(stdout='{"session": []}', exit_code=0),
            CommandResult(exit_code=1, error_type="command_failed", error_message="parser failed at /Users/wang/.codex/raw.jsonl"),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted"})

        result = DevicePusher(self.config, executor=executor, http_client=http_client).push()

        self.assertTrue(result["success"])
        self.assertNotIn("mswusage_codex_hourly_report", http_client.last_json)
        self.assertEqual(http_client.last_json["collection_status"], "ok")
        self.assertEqual(http_client.last_json["codex_hourly_status"], {
            "source": "mswusage_codex",
            "status": "unavailable",
            "error_type": "command_failed",
        })
        output = json.dumps(http_client.last_json, ensure_ascii=False, sort_keys=True)
        self.assertNotIn(".codex", output)
        self.assertNotIn("/Users/", output)

    def test_pusher_sends_full_ccusage_session_report_when_available(self) -> None:
        """测试客户端把 ccusage session 原始结构一起交给后端"""
        daily_stdout = '{"daily": []}'
        session_stdout = '{"session": [{"agent": "claude", "inputTokens": 10, "metadata": {"lastActivity": "2026-06-01T09:00:00+08:00"}}], "totals": {"totalTokens": 10}}'
        executor = FakeExecutor([
            CommandResult(stdout=daily_stdout, exit_code=0),
            CommandResult(stdout=session_stdout, exit_code=0),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted"})

        pusher = DevicePusher(self.config, executor=executor, http_client=http_client)
        result = pusher.push()

        self.assertTrue(result["success"])
        self.assertEqual(executor.calls[0], ["ccusage", "daily", "--json", "--timezone", "Asia/Shanghai"])
        self.assertEqual(executor.calls[1], ["ccusage", "session", "--json", "--timezone", "Asia/Shanghai"])
        # #91：session 之后不再有 `ccusage blocks` 子进程（停采）。
        self.assertTrue(all("blocks" not in call for call in executor.calls))
        self.assertEqual(http_client.last_json["ccusage_session_report"]["totals"], {"totalTokens": 10})
        self.assertEqual(
            http_client.last_json["ccusage_session_report"]["session"][0]["metadata"]["lastActivity"],
            "2026-06-01T09:00:00+08:00",
        )

    # `test_pusher_sends_full_ccusage_blocks_report_when_available` 已随 #91 删除：
    # 采集端不再跑 `ccusage blocks`，也不再上报 `ccusage_blocks_report`。
    # 停采守卫在 tests/test_collector_payload_contract.py（DROPPED_LEGACY_FIELDS +
    # OK 场景命令序列），向后兼容探针的有效性守卫见同文件 TestDroppedLegacyFieldProbesStayValid（服务端行为半边在 ingest.test.ts）。

    def test_pusher_ccusage_failure(self) -> None:
        """测试 ccusage 命令执行失败时仍会上报 source 失败状态"""
        executor = FakeExecutor(CommandResult(exit_code=1, error_type="command_failed", error_message="ccusage not found"))
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted", "source_id": "mac-local"})

        pusher = DevicePusher(self.config, executor=executor, http_client=http_client)
        result = pusher.push()

        self.assertTrue(result["success"])
        self.assertEqual(result["collection_status"], "command_failed")
        self.assertEqual(http_client.last_json["collection_status"], "command_failed")
        self.assertEqual(http_client.last_json["usage_daily"], [])

    def test_pusher_http_unauthorized(self) -> None:
        """测试 HTTP 上报返回 401 认证失败"""
        ccusage_stdout = '{"daily": []}'
        executor = FakeExecutor(CommandResult(stdout=ccusage_stdout, exit_code=0))
        http_client = FakeHTTPClient(status_code=401, response_data={"status": "error", "message": "Unauthorized"})

        pusher = DevicePusher(self.config, executor=executor, http_client=http_client)
        result = pusher.push()

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "http_auth_failed")

    def test_pusher_http_cloudflare_403_is_access_blocked_not_auth_failure(self) -> None:
        """非 JSON 的 Cloudflare 403 不能误导用户轮换有效 token"""
        executor = FakeExecutor(CommandResult(stdout='{"daily": []}', exit_code=0))
        http_client = FakeHTTPClient(status_code=403, response_data={})

        result = DevicePusher(self.config, executor=executor, http_client=http_client).push()

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "http_access_blocked")
        self.assertIn("入口防护", result["error_message"])

    def test_ingest_http_client_safely_handles_non_json_cloudflare_403(self) -> None:
        """Cloudflare HTML 403 只返回空响应对象，不泄露 HTML 或认证信息"""
        http_error = urllib.error.HTTPError(
            "https://example.test/ingest",
            403,
            "Forbidden",
            {"Content-Type": "text/html"},
            io.BytesIO(b"<html>Cloudflare challenge</html>"),
        )
        with patch("urllib.request.urlopen", side_effect=http_error):
            status, response = IngestHTTPClient().post(
                "https://example.test/ingest",
                {"source_id": "test"},
                {"Authorization": "Bearer test-token"},
                1,
            )

        self.assertEqual(status, 403)
        self.assertEqual(response, {})

    def test_pusher_http_timeout(self) -> None:
        """测试 HTTP 上报连接超时"""
        ccusage_stdout = '{"daily": []}'
        executor = FakeExecutor(CommandResult(stdout=ccusage_stdout, exit_code=0))
        http_client = FakeHTTPClient(status_code=0, response_data={}, raise_exc=TimeoutError("Connection timed out"))

        pusher = DevicePusher(self.config, executor=executor, http_client=http_client)
        result = pusher.push()

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "http_request_failed")
        self.assertIn("timed out", result["error_message"].lower())

    def test_pusher_retries_transient_http_failure(self) -> None:
        """HTTP 临时失败后会重试，避免一次网络抖动导致菜单栏数据长时间停住"""
        ccusage_stdout = '{"daily": []}'
        executor = FakeExecutor(CommandResult(stdout=ccusage_stdout, exit_code=0))
        http_client = FlakyHTTPClient([
            TimeoutError("SSL handshake timed out"),
            (200, {"status": "accepted", "source_id": "mac-local"}),
        ])

        pusher = DevicePusher(
            self.config,
            executor=executor,
            http_client=http_client,
            retry_sleep=lambda _: None,
        )
        result = pusher.push()

        self.assertTrue(result["success"])
        self.assertEqual(http_client.calls, 2)

    def test_pusher_agent_fallback(self) -> None:
        """测试当 ccusage 缺失 agent 字段时，客户端 Pusher 自动 fallback 为 'unknown'"""
        ccusage_stdout = '{"daily": [{"period": "2026-06-01", "inputTokens": 100}]}'
        executor = FakeExecutor(CommandResult(stdout=ccusage_stdout, exit_code=0))
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted"})

        pusher = DevicePusher(self.config, executor=executor, http_client=http_client)
        result = pusher.push()

        self.assertTrue(result["success"])
        # 校验发送的 payload 中该行的 agent 自动补上了 unknown
        sent_daily = http_client.last_json["usage_daily"]
        self.assertEqual(sent_daily[0]["agent"], "unknown")

    def test_pusher_invalid_json(self) -> None:
        """测试当 ccusage 输出非合法 JSON 且 ledger 不可用时会上报 source 失败状态"""
        ccusage_stdout = "{malformed-json"
        executor = FakeExecutor([
            CommandResult(stdout=ccusage_stdout, exit_code=0),
            CommandResult(error_type="command_failed", error_message="mswusage codex failed"),
            CommandResult(error_type="command_failed", error_message="mswusage claude failed"),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted", "source_id": "mac-local"})

        pusher = DevicePusher(self.config, executor=executor, http_client=http_client)
        result = pusher.push()

        self.assertTrue(result["success"])
        self.assertEqual(result["collection_status"], "invalid_json")
        self.assertEqual(http_client.last_json["collection_status"], "invalid_json")


class TestDevicePusherCollectorRelease(unittest.TestCase):
    def setUp(self) -> None:
        self.config = DeviceConfig(
            schema_version=1,
            source_id="mac-local",
            host="macbook-pro.local",
            machine="macbook-pro",
            os_user="wangzhipeng",
            platform="darwin",
            timezone="Asia/Shanghai",
            server_url="http://localhost:8000/ingest",
            timeout_seconds=30,
        )
        self.accepted = {"status": "accepted", "source_id": "mac-local"}
        # 快照整个 environ 并在用例结束时还原，只清掉本用例关心的变量，
        # 不把开发机或 CI 上其它 AI_USAGE_* 变量永久删掉。
        env_patcher = patch.dict(os.environ)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        for name in (
            "AI_USAGE_BUILD_SHA",
            "AI_USAGE_LAST_UPGRADE_STATUS",
            "AI_USAGE_LAST_UPGRADE_FROM_VERSION",
            "AI_USAGE_LAST_UPGRADE_TO_VERSION",
            "AI_USAGE_LAST_UPGRADE_FINISHED_AT",
        ):
            os.environ.pop(name, None)

    def _push_ok(self, config=None):
        executor = FakeExecutor([
            CommandResult(stdout='{"daily": []}', exit_code=0),
            CommandResult(stdout='{"session": []}', exit_code=0),
            CommandResult(error_type="command_failed", error_message="mswusage codex failed"),
            CommandResult(error_type="command_failed", error_message="mswusage claude failed"),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data=self.accepted)
        DevicePusher(config or self.config, executor=executor, http_client=http_client).push()
        return http_client

    def test_pusher_reports_its_collector_release(self) -> None:
        http_client = self._push_ok()

        release = http_client.last_json["collector_release"]
        self.assertEqual(release["collector_version"], version_contract.COLLECTOR_VERSION)
        self.assertEqual(release["config_schema_version"], 1)
        self.assertEqual(release["parser_schema_version"], version_contract.COLLECTOR_PARSER_SCHEMA_VERSION)
        self.assertEqual(release["release_channel"], "stable")
        self.assertEqual(release["last_upgrade"], {"status": "never"})

    def test_release_channel_comes_from_device_config(self) -> None:
        config = replace(self.config, release_channel="beta")

        http_client = self._push_ok(config)

        self.assertEqual(http_client.last_json["collector_release"]["release_channel"], "beta")

    def test_build_sha_and_last_upgrade_come_from_environment(self) -> None:
        os.environ["AI_USAGE_BUILD_SHA"] = "0a1b2c3d4e5"
        os.environ["AI_USAGE_LAST_UPGRADE_STATUS"] = "failed"
        os.environ["AI_USAGE_LAST_UPGRADE_FROM_VERSION"] = "0.2.0"
        os.environ["AI_USAGE_LAST_UPGRADE_TO_VERSION"] = "0.3.0"
        os.environ["AI_USAGE_LAST_UPGRADE_FINISHED_AT"] = "2026-08-01T09:00:00+08:00"

        release = self._push_ok().last_json["collector_release"]

        self.assertEqual(release["build_sha"], "0a1b2c3d4e5")
        self.assertEqual(
            release["last_upgrade"],
            {
                "status": "failed",
                "from_version": "0.2.0",
                "to_version": "0.3.0",
                "finished_at": "2026-08-01T09:00:00+08:00",
            },
        )

    def test_unsafe_environment_override_is_dropped_instead_of_being_pushed(self) -> None:
        os.environ["AI_USAGE_BUILD_SHA"] = "sk-ant-api03-FAKEfakeFAKEfake0123456789"

        payload = self._push_ok().last_json

        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("sk-ant-api03", rendered)
        self.assertNotIn("build_sha", payload["collector_release"])
        self.assertEqual(
            payload["collector_release"]["collector_version"],
            version_contract.COLLECTOR_VERSION,
        )

    def test_failed_collection_still_reports_the_collector_release(self) -> None:
        executor = FakeExecutor(
            CommandResult(exit_code=1, error_type="command_failed", error_message="ccusage not found")
        )
        http_client = FakeHTTPClient(status_code=200, response_data=self.accepted)

        DevicePusher(self.config, executor=executor, http_client=http_client).push()

        self.assertEqual(http_client.last_json["collection_status"], "command_failed")
        self.assertEqual(
            http_client.last_json["collector_release"]["collector_version"],
            version_contract.COLLECTOR_VERSION,
        )

    def test_pusher_surfaces_an_unsupported_version_rejection_as_a_clear_error(self) -> None:
        executor = FakeExecutor([
            CommandResult(stdout='{"daily": []}', exit_code=0),
            CommandResult(stdout='{"session": []}', exit_code=0),
            CommandResult(error_type="command_failed", error_message="mswusage codex failed"),
            CommandResult(error_type="command_failed", error_message="mswusage claude failed"),
        ])
        http_client = FakeHTTPClient(
            status_code=400,
            response_data={
                "error_type": version_contract.UNSUPPORTED_ERROR_TYPE,
                "message": "采集端版本 0.1.0 低于服务端最低支持版本 0.2.0，本次上报未写入，请升级采集端后重试",
            },
        )

        result = DevicePusher(self.config, executor=executor, http_client=http_client, retry_attempts=1).push()

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], version_contract.UNSUPPORTED_ERROR_TYPE)
        self.assertIn("未写入", result["error_message"])

    def test_out_of_range_config_schema_version_does_not_break_the_whole_push(self) -> None:
        config = replace(self.config, schema_version=999999)

        payload = self._push_ok(config).last_json

        self.assertEqual(payload["collection_status"], "ok")
        self.assertEqual(
            payload["collector_release"]["collector_version"],
            version_contract.COLLECTOR_VERSION,
        )
        self.assertNotIn("config_schema_version", payload["collector_release"])
