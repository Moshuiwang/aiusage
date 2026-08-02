from __future__ import annotations

import json
import os
import unittest

from ai_usage_widget.ingest import (
    IngestValidationError,
    validate_ingest_payload,
    IngestRequest,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class TestIngestContract(unittest.TestCase):
    def setUp(self) -> None:
        valid_path = os.path.join(FIXTURES_DIR, "ingest_payload_valid.json")
        with open(valid_path, "r", encoding="utf-8") as f:
            self.valid_data = json.load(f)

    def test_valid_payload_parsing(self) -> None:
        """验证合法的 Ingest Payload 能够被成功解析为 IngestRequest"""
        req = validate_ingest_payload(self.valid_data)
        self.assertIsInstance(req, IngestRequest)
        self.assertEqual(req.schema_version, 1)
        self.assertEqual(req.source_id, "mac-local")
        self.assertEqual(req.host, "macbook-pro")
        self.assertEqual(req.os_user, "wangzhipeng")
        self.assertEqual(req.platform, "darwin")
        self.assertEqual(req.timezone, "Asia/Shanghai")
        self.assertEqual(req.observed_at, "2026-06-01T10:40:00+08:00")
        self.assertEqual(req.collection_window, "daily")
        self.assertIsInstance(req.usage_daily, list)
        self.assertEqual(len(req.usage_daily), 1)

    def test_missing_schema_version(self) -> None:
        """验证缺少 schema_version 字段时应该校验失败"""
        data = self.valid_data.copy()
        del data["schema_version"]
        with self.assertRaises(IngestValidationError) as context:
            validate_ingest_payload(data)
        self.assertIn("schema_version", str(context.exception))

    def test_missing_required_fields(self) -> None:
        """验证缺少任意必填字段 (source_id, host, os_user, timezone, observed_at) 时应该校验失败"""
        required_fields = ["source_id", "host", "os_user", "timezone", "observed_at"]
        for field_name in required_fields:
            with self.subTest(field=field_name):
                data = self.valid_data.copy()
                del data[field_name]
                with self.assertRaises(IngestValidationError) as context:
                    validate_ingest_payload(data)
                self.assertIn(field_name, str(context.exception))

    def test_prevent_sensitive_logs_path_or_content(self) -> None:
        """验证当 payload 中包含原始敏感日志路径或内容（如 .claude, .codex）时，应该拦截报错"""
        sensitive_inputs = [
            "~/.claude/logs/",
            "/home/ubuntu/.codex/config.json",
            "some-path-containing-.claude-substring",
        ]
        for val in sensitive_inputs:
            with self.subTest(sensitive_val=val):
                data = self.valid_data.copy()
                # 尝试将敏感内容塞入其中一个字符串字段
                data["source_id"] = val
                with self.assertRaises(IngestValidationError) as context:
                    validate_ingest_payload(data)
                self.assertIn("sensitive", str(context.exception).lower())

    def test_prevent_ssh_parameters(self) -> None:
        """验证当输入包含 SSH 敏感密钥或配置关键字时拒绝接收"""
        data = self.valid_data.copy()
        data["ssh_key"] = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC..."
        with self.assertRaises(IngestValidationError) as context:
            validate_ingest_payload(data)
        self.assertIn("ssh", str(context.exception).lower())

    def test_auth_success(self) -> None:
        """验证提供正确 Token 时验证通过"""
        req = validate_ingest_payload(self.valid_data, token="secret123", expected_token="secret123")
        self.assertIsInstance(req, IngestRequest)

    def test_auth_failed_missing_token(self) -> None:
        """验证当服务器预期有 Token 但客户端未提供时验证失败"""
        with self.assertRaises(IngestValidationError) as context:
            validate_ingest_payload(self.valid_data, token=None, expected_token="secret123")
        self.assertEqual(context.exception.error_type, "http_auth_failed")

    def test_auth_failed_wrong_token(self) -> None:
        """验证客户端提供了错误 Token 时验证失败"""
        with self.assertRaises(IngestValidationError) as context:
            validate_ingest_payload(self.valid_data, token="wrong_token", expected_token="secret123")
        self.assertEqual(context.exception.error_type, "http_auth_failed")
        self.assertNotIn("wrong_token", str(context.exception))  # 确保日志中没有明文 token

    def test_payload_too_large(self) -> None:
        """验证 Payload 过大时应抛出错误 (人为模拟超限)"""
        # 我们模拟一个大 payload 注入
        data = self.valid_data.copy()
        data["huge_field"] = "a" * (51 * 1024 * 1024)  # 51MB, 超过完整 ccusage report 的 50MB 上限
        with self.assertRaises(IngestValidationError) as context:
            validate_ingest_payload(data)
        self.assertEqual(context.exception.error_type, "http_schema_invalid")
        self.assertIn("size", str(context.exception).lower())

    def test_accepts_valid_mswusage_codex_hourly_report(self) -> None:
        data = self.valid_data.copy()
        data["mswusage_codex_hourly_report"] = {
            "schema_version": 1,
            "source": "mswusage_codex",
            "timezone": "Asia/Shanghai",
            "generated_at": "2026-06-05T09:00:00+08:00",
            "provenance": "mswusage_codex_token_count",
            "daily": [],
            "hourly": [],
            "sessions": [],
            "drift": {"status": "ok", "threshold_percent": 5},
        }

        req = validate_ingest_payload(data)

        self.assertEqual(req.mswusage_codex_hourly_report["source"], "mswusage_codex")

    def test_accepts_usage_ledger_accuracy_evidence(self) -> None:
        data = self.valid_data.copy()
        data["usage_ledger_runs"] = [{
            "agent": "codex",
            "provenance": "mswusage_codex_token_count",
            "facts_digest": "safe-facts-digest",
            "collector": {
                "version": "0.1.0",
                "parser_schema_version": 2,
                "mode": "full-rescan",
                "coverage": {"start": None, "end": None},
                "counts": {"read_errors": 0, "unresolved_mismatch": 0},
                "scan_complete": True,
                "report_digest": "safe-digest",
            },
        }]

        req = validate_ingest_payload(data)

        self.assertEqual(req.usage_ledger_runs[0]["collector"]["report_digest"], "safe-digest")

    def test_rejects_invalid_mswusage_codex_hourly_report_shape(self) -> None:
        data = self.valid_data.copy()
        data["mswusage_codex_hourly_report"] = []

        with self.assertRaises(IngestValidationError) as context:
            validate_ingest_payload(data)

        self.assertIn("mswusage_codex_hourly_report", str(context.exception))

    def test_accepts_usage_hourly_facts(self) -> None:
        data = self.valid_data.copy()
        data["usage_hourly_facts"] = [
            {
                "fact_id": "codex:codex:mac-local:2026-06-11T13:00:00+08:00:2026-06-11T14:00:00+08:00:account_observed_usage_inferred:openai:acct-main:codex_token_events",
                "agent": "codex",
                "client": "codex",
                "window_start": "2026-06-11T13:00:00+08:00",
                "window_end": "2026-06-11T14:00:00+08:00",
                "ai_account": {
                    "provider": "openai",
                    "account_id": "acct-main",
                    "label": "start@example.com",
                },
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "cache_creation_tokens": 0,
                    "cache_read_tokens": 30,
                    "reasoning_output_tokens": 5,
                    "total_tokens": 155,
                },
                "event_count": 2,
                "session_count": 1,
                "attribution_confidence": "account_observed_usage_inferred",
                "provenance": "codex_token_events",
            }
        ]

        req = validate_ingest_payload(data)

        self.assertEqual(len(req.usage_hourly_facts), 1)
        self.assertEqual(req.usage_hourly_facts[0]["ai_account"]["label"], "start@example.com")

    def test_ignores_the_dropped_ccusage_daily_status_field(self) -> None:
        """#78：该字段已从两侧摘除，老版本采集端发来时必须当未知字段忽略。

        三种形态（合法三键 / 非 object / 缺键）此前分别被接受、被拒、被拒；现在**一律
        既不报错也不解析**——生产用的 Worker 从来就是这个行为，Python 侧不能更严。
        跨实现一致性的完整断言在
        ``tests/test_collector_payload_contract.py`` 与
        ``cloudflare/native-worker/test/ingest.test.ts``（读同一份历史字段探针）。
        """
        legacy_shapes = [
            {"status": "missing_tool", "error_type": "missing_tool", "error_message": "ccusage not found"},
            [],
            {"status": "missing_tool", "error_type": "missing_tool"},
            "missing_tool",
        ]
        for shape in legacy_shapes:
            with self.subTest(shape=shape):
                data = self.valid_data.copy()
                data["usage_daily"] = []
                data["ccusage_daily_status"] = shape

                req = validate_ingest_payload(data)

                self.assertFalse(
                    hasattr(req, "ccusage_daily_status"),
                    "IngestRequest 不该再带这个字段",
                )
                self.assertEqual(req.source_id, data["source_id"])

    def test_rejects_usage_hourly_facts_missing_required_field(self) -> None:
        data = self.valid_data.copy()
        data["usage_hourly_facts"] = [{"fact_id": "bad"}]

        with self.assertRaises(IngestValidationError) as context:
            validate_ingest_payload(data)

        self.assertIn("usage_hourly_facts[0].agent", str(context.exception))

    def test_accepts_collector_release_and_flattens_it(self) -> None:
        data = self.valid_data.copy()
        data["collector_release"] = {
            "collector_version": "0.3.0",
            "config_schema_version": 1,
            "parser_schema_version": 2,
            "release_channel": "stable",
            "build_sha": "0a1b2c3d4e5",
            "last_upgrade": {
                "status": "succeeded",
                "from_version": "0.2.0",
                "to_version": "0.3.0",
                "finished_at": "2026-08-01T09:00:00+08:00",
            },
        }

        req = validate_ingest_payload(data)

        self.assertEqual(req.collector_release["collector_version"], "0.3.0")
        self.assertEqual(req.collector_release["release_channel"], "stable")
        self.assertEqual(req.collector_release["last_upgrade_status"], "succeeded")
        self.assertEqual(req.collector_release["last_upgrade_from_version"], "0.2.0")

    def test_missing_collector_release_degrades_instead_of_failing(self) -> None:
        """缺整块版本信息只降级为未知，既不 500 也不静默当成合规"""
        data = self.valid_data.copy()
        data.pop("collector_release", None)

        req = validate_ingest_payload(data)

        self.assertIsNone(req.collector_release)

    def test_partial_collector_release_keeps_known_fields_and_nulls_the_rest(self) -> None:
        data = self.valid_data.copy()
        data["collector_release"] = {"collector_version": "0.3.0"}

        req = validate_ingest_payload(data)

        self.assertEqual(req.collector_release["collector_version"], "0.3.0")
        self.assertIsNone(req.collector_release["build_sha"])
        self.assertIsNone(req.collector_release["last_upgrade_status"])

    def test_rejects_non_object_collector_release(self) -> None:
        data = self.valid_data.copy()
        data["collector_release"] = []

        with self.assertRaises(IngestValidationError) as context:
            validate_ingest_payload(data)

        self.assertEqual(context.exception.error_type, "http_schema_invalid")
        self.assertIn("collector_release", str(context.exception))

    def test_rejects_unknown_key_inside_collector_release(self) -> None:
        data = self.valid_data.copy()
        data["collector_release"] = {"collector_version": "0.3.0", "auth_token": "whatever"}

        with self.assertRaises(IngestValidationError) as context:
            validate_ingest_payload(data)

        self.assertIn("auth_token", str(context.exception))

    def test_rejects_credential_or_path_shaped_version_values_without_echoing_them(self) -> None:
        fake_token = "sk-ant-api03-FAKEfakeFAKEfake0123456789"
        fake_path = "/opt/ai-usage/releases/current/bin/collector"
        cases = [
            ("collector_version", fake_token),
            ("collector_version", fake_path),
            ("build_sha", fake_token),
            ("build_sha", fake_path),
            ("release_channel", fake_path),
        ]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                data = self.valid_data.copy()
                data["collector_release"] = {field: value}

                with self.assertRaises(IngestValidationError) as context:
                    validate_ingest_payload(data)

                message = str(context.exception)
                self.assertEqual(context.exception.error_type, "http_schema_invalid")
                self.assertIn(f"collector_release.{field}", message)
                self.assertNotIn(value, message)

    def test_rejects_sensitive_strings_inside_mswusage_report(self) -> None:
        data = self.valid_data.copy()
        data["mswusage_codex_hourly_report"] = {
            "schema_version": 1,
            "source": "mswusage_codex",
            "timezone": "Asia/Shanghai",
            "generated_at": "2026-06-05T09:00:00+08:00",
            "provenance": "mswusage_codex_token_count",
            "daily": [],
            "hourly": [{"debug": "/Users/wang/.codex/sessions/raw.jsonl"}],
            "sessions": [],
        }

        with self.assertRaises(IngestValidationError) as context:
            validate_ingest_payload(data)

        self.assertIn("sensitive", str(context.exception).lower())
