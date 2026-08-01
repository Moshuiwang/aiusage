from __future__ import annotations

import json
import os
import unittest

from ai_usage_widget.config import (
    ConfigError,
    DeviceConfig,
    normalize_platform,
    validate_device_config,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class TestDeviceConfig(unittest.TestCase):
    def setUp(self) -> None:
        self.platforms = ["mac", "linux", "windows"]
        self.fixtures = {}
        for p in self.platforms:
            path = os.path.join(FIXTURES_DIR, f"device_config_{p}.json")
            with open(path, "r", encoding="utf-8") as f:
                self.fixtures[p] = json.load(f)

    def test_fixtures_valid(self) -> None:
        """验证所有平台配置 Fixture 均能通过校验"""
        for p, data in self.fixtures.items():
            with self.subTest(platform=p):
                cfg = validate_device_config(data)
                self.assertIsInstance(cfg, DeviceConfig)
                self.assertEqual(cfg.platform, p if p != "mac" else "darwin")

    def test_machine_name_can_differ_from_network_host(self) -> None:
        """验证展示用原始机器名可以独立于网络 host/domain"""
        data = self.fixtures["linux"].copy()
        data["host"] = "ai.chunbai.com"
        data["machine"] = "VM-0-3-ubuntu"

        cfg = validate_device_config(data)

        self.assertEqual(cfg.host, "ai.chunbai.com")
        self.assertEqual(cfg.machine, "VM-0-3-ubuntu")

    def test_missing_required_fields(self) -> None:
        """验证缺少 source_id, server_url, timezone, platform 时抛出 ConfigError"""
        required = ["source_id", "server_url", "timezone", "platform"]
        base_data = self.fixtures["mac"].copy()
        for field in required:
            with self.subTest(field=field):
                data = base_data.copy()
                del data[field]
                with self.assertRaises(ConfigError) as context:
                    validate_device_config(data)
                self.assertIn(field, str(context.exception))

    def test_unsupported_platform(self) -> None:
        """验证未知/不支持的平台平台时应该报错"""
        data = self.fixtures["mac"].copy()
        data["platform"] = "android"
        with self.assertRaises(ConfigError) as context:
            validate_device_config(data)
        self.assertIn("platform", str(context.exception).lower())

    def test_platform_alias_and_case_are_normalized(self) -> None:
        """平台别名的口径只有 normalize_platform 一份，doctor 等下游必须复用它"""
        for raw, expected in [
            ("mac", "darwin"),
            ("Mac", "darwin"),
            ("MAC", "darwin"),
            ("Linux", "linux"),
            ("WINDOWS", "windows"),
            ("darwin", "darwin"),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(normalize_platform(raw), expected)

    def test_surrounding_whitespace_in_platform_is_accepted_and_trimmed(self) -> None:
        """明确决定：手写 JSON 里的前后空白属于笔误而不是语义差异，规范化掉而不是报错。

        这是相对最初实现的一次放宽，用例把它钉死，避免以后被无声改回去。
        """
        self.assertEqual(normalize_platform("  linux  "), "linux")
        self.assertEqual(normalize_platform("\tmac\n"), "darwin")

        data = self.fixtures["linux"].copy()
        data["platform"] = "  linux  "
        self.assertEqual(validate_device_config(data).platform, "linux")

    def test_platform_that_is_only_whitespace_is_still_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            normalize_platform("   ")

    def test_reject_ssh_fields(self) -> None:
        """验证配置中包含 SSH 字段时被拒绝"""
        data = self.fixtures["mac"].copy()
        data["ssh_host"] = "192.168.1.1"
        with self.assertRaises(ConfigError) as context:
            validate_device_config(data)
        self.assertIn("ssh", str(context.exception).lower())


class TestDeviceConfigReleaseChannel(unittest.TestCase):
    def setUp(self) -> None:
        path = os.path.join(FIXTURES_DIR, "device_config_linux.json")
        with open(path, "r", encoding="utf-8") as handle:
            self.data = json.load(handle)

    def test_release_channel_defaults_to_stable(self) -> None:
        cfg = validate_device_config(dict(self.data))

        self.assertEqual(cfg.release_channel, "stable")

    def test_release_channel_accepts_declared_channels(self) -> None:
        for channel in ("stable", "beta", "dev"):
            with self.subTest(channel=channel):
                data = dict(self.data)
                data["release_channel"] = channel

                self.assertEqual(validate_device_config(data).release_channel, channel)

    def test_release_channel_rejects_undeclared_channel(self) -> None:
        data = dict(self.data)
        data["release_channel"] = "prod"

        with self.assertRaises(ConfigError) as context:
            validate_device_config(data)

        self.assertIn("release_channel", str(context.exception))
