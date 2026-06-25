from __future__ import annotations

import importlib.util
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest


SKILL_SCRIPT = Path("/Users/wangzhipeng/.codex/skills/ai-usage-fact-check/scripts/check_usage_facts.py")


def load_fact_check_module():
    spec = importlib.util.spec_from_file_location("ai_usage_fact_check_script", SKILL_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {SKILL_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestUsageFactCheckSkill(unittest.TestCase):
    def test_fact_table_marks_mac_current_tokens_not_applicable(self) -> None:
        module = load_fact_check_module()
        payload = sample_fact_payload()

        table = module.build_fact_check_table(payload)

        mac_row = next(row for row in table if row["source"] == "1. Mac 当前采集源")
        self.assertEqual(mac_row["today_tokens"], "不适用")
        self.assertEqual(mac_row["accuracy"], "✅ 准确")
        self.assertIn("只证明四个额度窗口", mac_row["note"])

    def test_fact_table_includes_d1_today_tokens(self) -> None:
        module = load_fact_check_module()
        payload = sample_fact_payload()

        table = module.build_fact_check_table(payload)

        d1_row = next(row for row in table if row["source"] == "2. Cloudflare D1 规范化存储")
        self.assertEqual(d1_row["today_tokens"], "123,456")
        self.assertEqual(d1_row["accuracy"], "✅ 准确")
        self.assertIn("today tokens 与主站一致", d1_row["note"])

    def test_fact_table_explains_mac_popover_drift(self) -> None:
        module = load_fact_check_module()
        payload = sample_fact_payload()

        table = module.build_fact_check_table(payload)

        popover_row = next(row for row in table if row["source"] == "4. Mac 菜单栏缓存")
        self.assertEqual(popover_row["codex_5h"], "0%")
        self.assertEqual(popover_row["today_tokens"], "120,000")
        self.assertEqual(popover_row["accuracy"], "⚠️ 不准确")
        self.assertIn("期望 Codex 5h 1%，实际 0%", popover_row["note"])
        self.assertIn("期望 today tokens 123,456，实际 120,000", popover_row["note"])
        self.assertIn("generated_at 2026-06-25 06:05 CST", popover_row["note"])

    def test_board_markdown_updates_current_summary_and_table(self) -> None:
        module = load_fact_check_module()
        payload = sample_fact_payload()

        markdown = module.build_board_markdown(payload)

        self.assertIn("最后核查：2026-06-25 06:17 CST", markdown)
        self.assertIn("当前 Cloudflare 主站 API 基线：Codex 5h 1%、Codex 7d 47%、Claude 5h 0%、Claude 7d 52%", markdown)
        self.assertIn("| 2. Cloudflare D1 规范化存储 | 1% | 47% | 0% | 52% | 123,456 |", markdown)
        self.assertIn("Mac 当前采集源只证明四个额度窗口，today tokens 由 API/D1 层核对。", markdown)
        self.assertIn("Mac 菜单栏缓存存在差异", markdown)

    def test_board_markdown_preserves_existing_history(self) -> None:
        module = load_fact_check_module()
        payload = sample_fact_payload()
        existing = "# AI Usage 数据源核查面板\n\n## 历史摘要\n\n- 2026-06-24 19:35：旧核查摘要。"

        markdown = module.build_board_markdown(payload, existing)

        self.assertIn("## 历史摘要", markdown)
        self.assertIn("- 2026-06-24 19:35：旧核查摘要。", markdown)

    def test_normalized_current_values_ignore_expired_quota_windows(self) -> None:
        module = load_fact_check_module()

        normalized = module.normalize_windows(
            [
                {
                    "source_id": "codex-main",
                    "provider": "codex",
                    "window": "session",
                    "used_percent": 52,
                    "remaining_percent": 48,
                    "reset_at": "2026-06-24T14:19:40+08:00",
                    "window_duration_minutes": 300,
                    "observed_at": "2026-06-24T14:18:42+08:00",
                    "source_type": "runtime_api",
                    "confidence": "observed",
                    "status": "ok",
                    "official": True,
                },
                {
                    "source_id": "codex-main",
                    "provider": "codex",
                    "window": "week",
                    "used_percent": 42,
                    "remaining_percent": 58,
                    "reset_at": "2026-06-27T22:10:35+08:00",
                    "window_duration_minutes": 10080,
                    "observed_at": "2026-06-24T14:18:42+08:00",
                    "source_type": "runtime_api",
                    "confidence": "observed",
                    "status": "ok",
                    "official": True,
                },
            ],
            now="2026-06-24T14:22:00+08:00",
        )

        self.assertIsNone(normalized["codex_5h"])
        self.assertEqual(normalized["codex_7d"]["used_percent"], 42)

    def test_device_cache_reads_prefer_app_group_caches_path(self) -> None:
        script = SKILL_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("Library/Caches/last-mobile-summary.json", script)
        self.assertIn("Library/Caches/last-watch-summary.json", script)
        self.assertIn("Library/Caches/last-watch-cache-receipt.json", script)

    def test_fact_check_default_does_not_query_backup_origin(self) -> None:
        module = load_fact_check_module()
        backup_calls = []

        module.collect_mac_current = lambda repo: {"status": "ok"}
        module.collect_mac_popover = lambda: {"status": "ok"}
        module.collect_origin = lambda: backup_calls.append("legacy") or {"status": "error"}
        module.collect_backup_origin = lambda: backup_calls.append("called") or {"status": "error"}

        old_argv = sys.argv
        try:
            sys.argv = [
                "check_usage_facts.py",
                "--skip-iphone",
                "--skip-watch",
                "--skip-cloudflare",
            ]
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(module.main(), 0)
        finally:
            sys.argv = old_argv

        payload = json.loads(stdout.getvalue())
        self.assertEqual(backup_calls, [])
        self.assertNotIn("aliyun_origin", payload)
        self.assertNotIn("backup_origin", payload)

    def test_fact_check_backup_origin_requires_explicit_flag(self) -> None:
        module = load_fact_check_module()

        module.collect_mac_current = lambda repo: {"status": "ok"}
        module.collect_mac_popover = lambda: {"status": "ok"}
        module.collect_backup_origin = lambda: {"status": "ok", "role": "backup"}

        old_argv = sys.argv
        try:
            sys.argv = [
                "check_usage_facts.py",
                "--skip-iphone",
                "--skip-watch",
                "--skip-cloudflare",
                "--include-backup-origin",
            ]
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(module.main(), 0)
        finally:
            sys.argv = old_argv

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["backup_origin"]["role"], "backup")


def sample_window(provider: str, window: str, used_percent: int, observed_at: str) -> dict:
    return {
        "source_id": f"{provider}-main",
        "provider": provider,
        "window": window,
        "used_percent": used_percent,
        "remaining_percent": 100 - used_percent,
        "reset_at": "2026-06-28T02:00:00+08:00" if window == "week" else "2026-06-25T11:00:00+08:00",
        "window_duration_minutes": 10080 if window == "week" else 300,
        "observed_at": observed_at,
        "source_type": "runtime_api" if provider == "codex" else "official_cli",
        "confidence": "observed",
        "status": "ok",
        "official": True,
    }


def sample_limits(codex_5h: int, codex_7d: int, claude_5h: int, claude_7d: int, observed_at: str) -> dict:
    windows = [
        sample_window("codex", "session", codex_5h, observed_at),
        sample_window("codex", "week", codex_7d, observed_at),
        sample_window("claude", "session", claude_5h, observed_at),
        sample_window("claude", "week", claude_7d, observed_at),
    ]
    return {
        "codex_5h": windows[0],
        "codex_7d": windows[1],
        "claude_5h": windows[2],
        "claude_7d": windows[3],
        "windows": windows,
    }


def sample_fact_payload() -> dict:
    api_limits = sample_limits(1, 47, 0, 52, "2026-06-25T06:17:11+08:00")
    popover_limits = sample_limits(0, 47, 0, 52, "2026-06-25T06:05:10+08:00")
    return {
        "cloudflare_public_api": {
            "status": "ok",
            "generated_at": "2026-06-25T06:17:58+08:00",
            "total_tokens": 123456,
            "limits": api_limits,
        },
        "cloudflare": {
            "status": "ok",
            "d1": [
                {
                    "name": "aiusage-prod-db",
                    "normalized_limits": api_limits,
                    "today_total_tokens": 123456,
                }
            ],
        },
        "mac_current": {
            "status": "ok",
            **api_limits,
        },
        "mac_popover": {
            "status": "ok",
            "generated_at": "2026-06-25T06:05:10+08:00",
            "total_tokens": 120000,
            **popover_limits,
        },
    }


if __name__ == "__main__":
    unittest.main()
