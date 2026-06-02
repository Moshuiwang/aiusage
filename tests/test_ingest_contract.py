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
