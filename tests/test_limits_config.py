from __future__ import annotations

import json
import tempfile
import unittest

from ai_usage_widget.limits_config import ConfigError, load_limits_config, parse_limits_config, summarize_limits_config


class TestLimitsConfig(unittest.TestCase):
    def test_parse_limits_config_outputs_enabled_providers_and_paths(self) -> None:
        config = parse_limits_config(
            {
                "schema_version": 1,
                "timezone": "Asia/Shanghai",
                "sqlite": "data/usage.sqlite",
                "latest": "data/latest.json",
                "providers": [
                    {"provider": "codex", "auth_file": "/tmp/codex-auth.json", "rpc": True},
                    {
                        "provider": "claude",
                        "auth_file": "/tmp/claude-auth.json",
                        "usage_url": "https://example.invalid/usage",
                        "cli": True,
                    },
                    {"provider": "claude", "enabled": False, "cli": True},
                ],
            }
        )

        self.assertEqual(config.timezone, "Asia/Shanghai")
        self.assertEqual(config.sqlite_path, "data/usage.sqlite")
        self.assertEqual(config.latest_path, "data/latest.json")
        self.assertEqual([provider.provider for provider in config.enabled_providers], ["codex", "claude"])
        self.assertTrue(config.enabled_providers[0].codex_rpc)
        self.assertTrue(config.enabled_providers[1].claude_cli)

    def test_parse_limits_config_allows_multi_account_cli_env(self) -> None:
        config = parse_limits_config(
            {
                "schema_version": 1,
                "timezone": "Asia/Shanghai",
                "providers": [
                    {
                        "provider": "claude",
                        "source_id": "claude-main",
                        "cli": True,
                    },
                    {
                        "provider": "claude",
                        "source_id": "claude-w",
                        "cli": True,
                        "env": {"CLAUDE_CONFIG_DIR": "/Users/wangzhipeng/.claudew"},
                    },
                ],
            }
        )

        self.assertEqual([provider.source_id for provider in config.enabled_providers], ["claude-main", "claude-w"])
        self.assertEqual(config.enabled_providers[0].env, {})
        self.assertEqual(config.enabled_providers[1].env, {"CLAUDE_CONFIG_DIR": "/Users/wangzhipeng/.claudew"})

    def test_rejects_inline_secret_fields(self) -> None:
        with self.assertRaises(ConfigError):
            parse_limits_config(
                {
                    "timezone": "Asia/Shanghai",
                    "providers": [
                        {"provider": "codex", "access_token": "do-not-store-token-here", "rpc": True},
                    ],
                }
            )

    def test_rejects_codex_without_auth_or_rpc(self) -> None:
        with self.assertRaises(ConfigError):
            parse_limits_config({"timezone": "Asia/Shanghai", "providers": [{"provider": "codex"}]})

    def test_rejects_claude_without_oauth_pair_or_cli(self) -> None:
        with self.assertRaises(ConfigError):
            parse_limits_config(
                {
                    "timezone": "Asia/Shanghai",
                    "providers": [
                        {"provider": "claude", "auth_file": "/tmp/claude-auth.json"},
                    ],
                }
            )

    def test_load_limits_config_reads_json_file(self) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
            json.dump(
                {
                    "timezone": "Asia/Shanghai",
                    "providers": [{"provider": "claude", "cli": True}],
                },
                handle,
            )
            handle.flush()

            config = load_limits_config(handle.name)

        self.assertEqual([provider.provider for provider in config.enabled_providers], ["claude"])

    def test_summarize_limits_config_redacts_paths_and_urls(self) -> None:
        config = parse_limits_config(
            {
                "timezone": "Asia/Shanghai",
                "sqlite": "data/usage.sqlite",
                "latest": "data/latest.json",
                "providers": [
                    {
                        "provider": "codex",
                        "auth_file": "/Users/me/.codex/auth.json",
                        "rpc": True,
                        "rpc_sock": "/tmp/codex.sock",
                    },
                    {
                        "provider": "claude",
                        "auth_file": "/Users/me/.claude/auth.json",
                        "usage_url": "https://example.invalid/usage",
                        "cli": True,
                    },
                ],
            }
        )

        summary = summarize_limits_config(config)

        self.assertEqual(summary["providers"][0]["provider"], "codex")
        self.assertTrue(summary["providers"][0]["has_auth_file"])
        self.assertTrue(summary["providers"][0]["codex_rpc"])
        self.assertTrue(summary["providers"][0]["has_codex_rpc_sock"])
        self.assertTrue(summary["providers"][1]["has_usage_url"])
        self.assertNotIn("/Users/me", json.dumps(summary))
        self.assertNotIn("example.invalid", json.dumps(summary))

    def test_summarize_limits_config_redacts_env_values(self) -> None:
        config = parse_limits_config(
            {
                "timezone": "Asia/Shanghai",
                "providers": [
                    {
                        "provider": "claude",
                        "source_id": "claude-w",
                        "cli": True,
                        "env": {"CLAUDE_CONFIG_DIR": "/Users/me/.claudew"},
                    },
                ],
            }
        )

        summary = summarize_limits_config(config)

        self.assertEqual(summary["providers"][0]["source_id"], "claude-w")
        self.assertTrue(summary["providers"][0]["has_env"])
        self.assertEqual(summary["providers"][0]["env_keys"], ["CLAUDE_CONFIG_DIR"])
        self.assertNotIn("/Users/me", json.dumps(summary))


if __name__ == "__main__":
    unittest.main()
