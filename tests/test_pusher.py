from __future__ import annotations

import os
import unittest
from typing import Any, Dict

from ai_usage_widget.config import DeviceConfig
from ai_usage_widget.models import CommandResult
from ai_usage_widget.pusher import DevicePusher, IngestHTTPClient


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

    def test_pusher_success_flow(self) -> None:
        """测试正常流：ccusage 采集成功且 HTTP 上报成功"""
        ccusage_stdout = '{"daily": [{"period": "2026-06-01", "agent": "claude", "inputTokens": 100, "modelsUsed": ["opus"]}], "totals": {"totalTokens": 100}, "extra": {"kept": true}}'
        executor = FakeExecutor([
            CommandResult(stdout=ccusage_stdout, exit_code=0),
            CommandResult(stdout='{"session": []}', exit_code=0),
            CommandResult(stdout='{"blocks": []}', exit_code=0),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted", "source_id": "mac-local"})

        pusher = DevicePusher(self.config, executor=executor, http_client=http_client)
        result = pusher.push()

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "accepted")
        # 校验 HTTP 头部携带 Bearer Token
        self.assertEqual(http_client.last_headers.get("Authorization"), "Bearer test-token-123")
        # 校验采集时使用了正确的参数
        self.assertIn("ccusage", executor.calls[0][0])
        self.assertIn("daily", executor.calls[0])
        self.assertIn("session", executor.calls[1])
        self.assertIn("blocks", executor.calls[2])
        self.assertEqual(http_client.last_json["ccusage_daily_report"]["totals"]["totalTokens"], 100)
        self.assertEqual(http_client.last_json["host"], "macbook-pro.local")
        self.assertEqual(http_client.last_json["machine"], "macbook-pro")
        self.assertEqual(http_client.last_json["ccusage_daily_report"]["extra"], {"kept": True})
        self.assertEqual(http_client.last_json["usage_daily"][0]["modelsUsed"], ["opus"])
        self.assertEqual(http_client.last_json["ccusage_session_report"]["session"], [])
        self.assertEqual(http_client.last_json["ccusage_blocks_report"]["blocks"], [])

    def test_pusher_sends_full_ccusage_session_report_when_available(self) -> None:
        """测试客户端把 ccusage session 原始结构一起交给后端"""
        daily_stdout = '{"daily": []}'
        session_stdout = '{"session": [{"agent": "claude", "inputTokens": 10, "metadata": {"lastActivity": "2026-06-01T09:00:00+08:00"}}], "totals": {"totalTokens": 10}}'
        executor = FakeExecutor([
            CommandResult(stdout=daily_stdout, exit_code=0),
            CommandResult(stdout=session_stdout, exit_code=0),
            CommandResult(stdout='{"blocks": []}', exit_code=0),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted"})

        pusher = DevicePusher(self.config, executor=executor, http_client=http_client)
        result = pusher.push()

        self.assertTrue(result["success"])
        self.assertEqual(executor.calls[0], ["ccusage", "daily", "--json", "--timezone", "Asia/Shanghai"])
        self.assertEqual(executor.calls[1], ["ccusage", "session", "--json", "--timezone", "Asia/Shanghai"])
        self.assertEqual(executor.calls[2], ["ccusage", "blocks", "--json", "--timezone", "Asia/Shanghai"])
        self.assertEqual(http_client.last_json["ccusage_session_report"]["totals"], {"totalTokens": 10})
        self.assertEqual(
            http_client.last_json["ccusage_session_report"]["session"][0]["metadata"]["lastActivity"],
            "2026-06-01T09:00:00+08:00",
        )

    def test_pusher_sends_full_ccusage_blocks_report_when_available(self) -> None:
        """测试客户端把 ccusage blocks 原始结构一起交给后端"""
        daily_stdout = '{"daily": []}'
        session_stdout = '{"session": []}'
        blocks_stdout = '{"blocks": [{"startTime": "2026-05-31T21:00:00.000Z", "endTime": "2026-06-01T02:00:00.000Z", "totalTokens": 1000}]}'
        executor = FakeExecutor([
            CommandResult(stdout=daily_stdout, exit_code=0),
            CommandResult(stdout=session_stdout, exit_code=0),
            CommandResult(stdout=blocks_stdout, exit_code=0),
        ])
        http_client = FakeHTTPClient(status_code=200, response_data={"status": "accepted"})

        pusher = DevicePusher(self.config, executor=executor, http_client=http_client)
        result = pusher.push()

        self.assertTrue(result["success"])
        self.assertEqual(executor.calls[2], ["ccusage", "blocks", "--json", "--timezone", "Asia/Shanghai"])
        self.assertEqual(
            http_client.last_json["ccusage_blocks_report"]["blocks"][0]["startTime"],
            "2026-05-31T21:00:00.000Z",
        )

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
        """测试当 ccusage 输出非合法 JSON 时，Pusher 返回 'invalid_json'"""
        ccusage_stdout = "{malformed-json"
        executor = FakeExecutor(CommandResult(stdout=ccusage_stdout, exit_code=0))
        http_client = FakeHTTPClient(status_code=200, response_data={})

        pusher = DevicePusher(self.config, executor=executor, http_client=http_client)
        result = pusher.push()

        self.assertFalse(result["success"])
        self.assertEqual(result["error_type"], "invalid_json")
