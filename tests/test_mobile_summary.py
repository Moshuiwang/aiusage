from __future__ import annotations

import unittest

from ai_usage_widget.mobile_summary import build_mobile_summary


class TestMobileSummaryTrend(unittest.TestCase):
    def test_mobile_trend_points_preserve_agent_segments_and_unknown_conservation(self) -> None:
        summary = build_mobile_summary({
            "summary": {"period": "week", "total_tokens": 1000},
            "trend": {
                "period": "week",
                "granularity": "day",
                "points": [
                    {"date": "2026-06-01", "total_tokens": 600},
                    {"date": "2026-06-02", "total_tokens": 400},
                ],
                "by_agent": [
                    {"agent": "claude", "values": [300, 0]},
                    {"agent": "gpt-5", "values": [200, 400]},
                    {"agent": "other-agent", "values": [100, 0]},
                ],
            },
            "source_status": [],
            "groups": {},
            "items": [],
            "limits": [],
        })

        points = summary["trend"]["points"]
        self.assertEqual(
            [
                (row["claude_tokens"], row["codex_tokens"], row["unknown_tokens"], row["tokens"])
                for row in points
            ],
            [(300, 200, 100, 600), (0, 400, 0, 400)],
        )
        self.assertTrue(all(
            row["claude_tokens"] + row["codex_tokens"] + row["unknown_tokens"] == row["tokens"]
            for row in points
        ))


class TestMobileSummaryLimits(unittest.TestCase):
    def test_mobile_summary_only_returns_effective_quota_windows(self) -> None:
        summary = build_mobile_summary({
            "generated_at": "2026-06-02T10:45:00+08:00",
            "summary": {"period": "today", "total_tokens": 1200},
            "trend": {"points": []},
            "source_status": [],
            "groups": {},
            "items": [],
            "limits": [
                {
                    "source_id": "old-cache",
                    "provider": "claude",
                    "window": "session",
                    "used_percent": 99,
                    "remaining_percent": 1,
                    "reset_at": "2026-06-02T15:45:00+08:00",
                    "window_duration_minutes": 300,
                    "observed_at": "2026-06-02T10:44:00+08:00",
                    "source_type": "active_limits_cache",
                    "confidence": "observed",
                    "status": "ok",
                    "official": False,
                },
                {
                    "source_id": "runtime",
                    "provider": "claude",
                    "window": "session",
                    "used_percent": 3,
                    "remaining_percent": 97,
                    "reset_at": "2026-06-02T15:45:00+08:00",
                    "window_duration_minutes": 300,
                    "observed_at": "2026-06-02T10:45:00+08:00",
                    "source_type": "runtime_api",
                    "confidence": "observed",
                    "status": "ok",
                    "official": True,
                },
                {
                    "source_id": "failed",
                    "provider": "codex",
                    "window": "week",
                    "used_percent": 0,
                    "remaining_percent": 0,
                    "reset_at": "2026-06-08T00:00:00+08:00",
                    "window_duration_minutes": 10080,
                    "observed_at": "2026-06-02T10:45:00+08:00",
                    "source_type": "runtime_api",
                    "confidence": "missing",
                    "status": "provider_failed",
                    "official": False,
                },
            ],
        })

        self.assertEqual(summary["limits"]["observed_count"], 1)
        self.assertEqual(summary["limits"]["total_count"], 1)
        self.assertEqual(
            [(row["source_id"], row["provider"], row["window"]) for row in summary["limits"]["windows"]],
            [("runtime", "claude", "session")],
        )

    def test_mobile_summary_exposes_safe_freshness_metadata(self) -> None:
        summary = build_mobile_summary({
            "generated_at": "2026-06-02T10:45:00+08:00",
            "timezone": "Asia/Shanghai",
            "summary": {"period": "today", "total_tokens": 1200},
            "trend": {"points": []},
            "source_status": [],
            "groups": {},
            "items": [],
            "metadata": {
                "backend_mode": "origin_direct",
                "canonical_store": "origin_sqlite",
                "read_model_generated_at": "2026-06-02T10:45:00+08:00",
                "freshness_status": "ok",
                "limits_observed_at": "2026-06-02T10:44:00+08:00",
            },
            "limits": [],
        })

        self.assertEqual(
            summary["metadata"],
            {
                "backend_mode": "origin_direct",
                "canonical_store": "origin_sqlite",
                "read_model_generated_at": "2026-06-02T10:45:00+08:00",
                "freshness_status": "ok",
                "limits_observed_at": "2026-06-02T10:44:00+08:00",
            },
        )

    def test_limits_windows_only_include_official_observed_ok_rows(self) -> None:
        summary = build_mobile_summary({
            "summary": {"period": "today", "total_tokens": 1200},
            "trend": {"points": []},
            "source_status": [],
            "groups": {},
            "items": [],
            "limits": [
                {
                    "source_id": "codex-main",
                    "provider": "codex",
                    "window": "weekly",
                    "used_percent": 37.5,
                    "remaining_percent": 62.5,
                    "reset_at": "2026-06-08T00:00:00+08:00",
                    "window_duration_minutes": 10080,
                    "observed_at": "2026-06-03T09:31:00+08:00",
                    "source_type": "runtime_api",
                    "confidence": "observed",
                    "status": "ok",
                    "official": True,
                },
                {
                    "source_id": "local-estimate",
                    "provider": "codex",
                    "window": "weekly",
                    "used_percent": 50.0,
                    "remaining_percent": 50.0,
                    "reset_at": "2026-06-08T00:00:00+08:00",
                    "window_duration_minutes": 10080,
                    "observed_at": "2026-06-03T09:31:00+08:00",
                    "source_type": "ccusage_daily",
                    "confidence": "observed",
                    "status": "ok",
                    "official": False,
                },
                {
                    "source_id": "claude-weekly",
                    "provider": "claude",
                    "window": "weekly",
                    "used_percent": 0,
                    "remaining_percent": 0,
                    "reset_at": "2026-06-03T09:31:00+08:00",
                    "window_duration_minutes": 0,
                    "observed_at": "2026-06-03T09:31:00+08:00",
                    "source_type": "provider_runtime",
                    "confidence": "missing",
                    "status": "provider_failed",
                    "official": False,
                },
                {
                    "source_id": "codex-stale",
                    "provider": "codex",
                    "window": "weekly",
                    "used_percent": 90,
                    "remaining_percent": 10,
                    "reset_at": "2026-06-08T00:00:00+08:00",
                    "window_duration_minutes": 10080,
                    "observed_at": "2026-06-03T09:31:00+08:00",
                    "source_type": "runtime_api",
                    "confidence": "observed",
                    "status": "provider_failed",
                    "official": True,
                },
            ],
        })

        self.assertEqual(summary["limits"]["observed_count"], 1)
        self.assertEqual(summary["limits"]["total_count"], 1)
        self.assertEqual(
            [(row["source_id"], row["confidence"], row["official"]) for row in summary["limits"]["windows"]],
            [
                ("codex-main", "observed", True),
            ],
        )

    def test_filters_expired_short_quota_windows_and_keeps_fresh_weekly(self) -> None:
        for period in ["today", "week", "month", "all"]:
            with self.subTest(period=period):
                summary = build_mobile_summary({
                    "generated_at": "2026-06-02T10:45:00+08:00",
                    "summary": {"period": period, "total_tokens": 1200},
                    "trend": {"points": []},
                    "source_status": [],
                    "groups": {},
                    "items": [],
                    "limits": [
                        {
                            "source_id": "claude-main",
                            "provider": "claude",
                            "window": "session",
                            "used_percent": 96,
                            "remaining_percent": 4,
                            "reset_at": "2026-06-02T09:45:00+08:00",
                            "window_duration_minutes": 300,
                            "observed_at": "2026-06-02T04:45:00+08:00",
                            "source_type": "oauth_usage_api",
                            "confidence": "observed",
                            "status": "ok",
                            "official": True,
                        },
                        {
                            "source_id": "claude-main",
                            "provider": "claude",
                            "window": "week",
                            "used_percent": 41,
                            "remaining_percent": 59,
                            "reset_at": "2026-06-08T00:00:00+08:00",
                            "window_duration_minutes": 10080,
                            "observed_at": "2026-06-02T10:40:00+08:00",
                            "source_type": "oauth_usage_api",
                            "confidence": "observed",
                            "status": "ok",
                            "official": True,
                        },
                    ],
                })

                windows = summary["limits"]["windows"]
                self.assertEqual([(w["provider"], w["window"]) for w in windows], [("claude", "week")])
                self.assertEqual(summary["limits"]["observed_count"], 1)

    def test_keeps_fresh_short_quota_window_for_every_period(self) -> None:
        for period in ["today", "week", "month", "all"]:
            with self.subTest(period=period):
                summary = build_mobile_summary({
                    "generated_at": "2026-06-02T10:45:00+08:00",
                    "summary": {"period": period, "total_tokens": 1200},
                    "trend": {"points": []},
                    "source_status": [],
                    "groups": {},
                    "items": [],
                    "limits": [
                        {
                            "source_id": "claude-main",
                            "provider": "claude",
                            "window": "session",
                            "used_percent": 0,
                            "remaining_percent": 100,
                            "reset_at": "2026-06-02T15:45:00+08:00",
                            "window_duration_minutes": 300,
                            "observed_at": "2026-06-02T10:45:00+08:00",
                            "source_type": "oauth_usage_api",
                            "confidence": "observed",
                            "status": "ok",
                            "official": True,
                        },
                    ],
                })

                self.assertEqual([(w["provider"], w["window"]) for w in summary["limits"]["windows"]], [("claude", "session")])

    def test_filters_stale_official_window_even_when_reset_is_still_in_future(self) -> None:
        summary = build_mobile_summary({
            "generated_at": "2026-07-18T12:30:00+08:00",
            "summary": {"period": "today", "total_tokens": 1200},
            "trend": {"points": []},
            "source_status": [],
            "groups": {},
            "items": [],
            "limits": [{
                "source_id": "linux-biai-wang",
                "provider": "claude",
                "window": "week",
                "used_percent": 41,
                "remaining_percent": 59,
                "reset_at": "2026-07-20T00:00:00+08:00",
                "window_duration_minutes": 10080,
                "observed_at": "2026-07-18T10:00:00+08:00",
                "source_type": "official_cli",
                "confidence": "observed",
                "status": "ok",
                "official": True,
            }],
        })

        self.assertEqual(summary["limits"]["windows"], [])
        self.assertEqual(summary["metadata"]["freshness_status"], "stale")
        self.assertEqual(summary["metadata"]["limits_observed_at"], "2026-07-18T10:00:00+08:00")

    def test_naive_short_quota_reset_does_not_crash_period_summary(self) -> None:
        summary = build_mobile_summary({
            "generated_at": "2026-06-02T10:45:00+08:00",
            "summary": {"period": "week", "total_tokens": 1200},
            "trend": {"points": []},
            "source_status": [],
            "groups": {},
            "items": [],
            "limits": [
                {
                    "source_id": "claude-main",
                    "provider": "claude",
                    "window": "session",
                    "used_percent": 96,
                    "remaining_percent": 4,
                    "reset_at": "2026-06-02T09:45:00",
                    "window_duration_minutes": 300,
                    "observed_at": "2026-06-02T04:45:00+08:00",
                    "source_type": "oauth_usage_api",
                    "confidence": "observed",
                    "status": "ok",
                    "official": True,
                }
            ],
        })

        self.assertEqual(summary["limits"]["windows"], [])

    def test_adds_safe_account_and_plan_labels_to_quota_windows(self) -> None:
        summary = build_mobile_summary({
            "generated_at": "2026-06-02T10:45:00+08:00",
            "summary": {"period": "today", "total_tokens": 1200},
            "trend": {"points": []},
            "source_status": [],
            "groups": {},
            "items": [],
            "limits": [
                {
                    "source_id": "codex-main",
                    "provider": "codex",
                    "window": "session",
                    "used_percent": 3,
                    "remaining_percent": 97,
                    "reset_at": "2026-06-02T15:45:00+08:00",
                    "window_duration_minutes": 300,
                    "observed_at": "2026-06-02T10:45:00+08:00",
                    "source_type": "runtime_api",
                    "confidence": "observed",
                    "status": "ok",
                    "official": True,
                    "account_email": "startimessocietegn@gmail.com",
                    "account_plan": "pro",
                },
                {
                    "source_id": "claude-main",
                    "provider": "claude",
                    "window": "week",
                    "used_percent": 41,
                    "remaining_percent": 59,
                    "reset_at": "2026-06-08T00:00:00+08:00",
                    "window_duration_minutes": 10080,
                    "observed_at": "2026-06-02T10:45:00+08:00",
                    "source_type": "oauth_usage_api",
                    "confidence": "observed",
                    "status": "ok",
                    "official": True,
                    "account_email": "wangzhipeng2010@gmail.com",
                    "account_plan": "claude_pro",
                },
            ],
        })

        windows = {row["provider"]: row for row in summary["limits"]["windows"]}
        self.assertEqual(windows["codex"]["account_label"], "startimessocietegn@gmail.com")
        self.assertEqual(windows["codex"]["account_plan_label"], "Pro 20x")
        self.assertEqual(windows["claude"]["account_label"], "wangzhipeng2010@gmail.com")
        self.assertEqual(windows["claude"]["account_plan_label"], "Pro")

    def test_uses_safe_ai_accounts_when_hourly_usage_is_empty(self) -> None:
        summary = build_mobile_summary({
            "generated_at": "2026-06-02T10:45:00+08:00",
            "summary": {"period": "today", "total_tokens": 0},
            "trend": {"points": []},
            "source_status": [],
            "groups": {},
            "items": [],
            "account_hourly": {"by_ai_account": []},
            "ai_accounts": [
                {
                    "provider": "codex",
                    "account_id": "86b44ff3-d85f-4fa7-bbbb-1a662509b3b7",
                    "label": "startimessocietegn@gmail.com",
                    "display_name": "StarTimes",
                    "subscription": "pro",
                }
            ],
            "limits": [
                {
                    "source_id": "codex-main",
                    "provider": "codex",
                    "window": "session",
                    "used_percent": 3,
                    "remaining_percent": 97,
                    "reset_at": "2026-06-02T15:45:00+08:00",
                    "window_duration_minutes": 300,
                    "observed_at": "2026-06-02T10:45:00+08:00",
                    "source_type": "runtime_api",
                    "confidence": "observed",
                    "status": "ok",
                    "official": True,
                },
            ],
        })

        window = summary["limits"]["windows"][0]
        self.assertEqual(window["account_label"], "startimessocietegn@gmail.com")
        self.assertEqual(window["account_plan_label"], "Pro 20x")

    def test_maps_openai_ai_account_metadata_to_codex_quota(self) -> None:
        summary = build_mobile_summary({
            "generated_at": "2026-06-02T10:45:00+08:00",
            "summary": {"period": "today", "total_tokens": 0},
            "trend": {"points": []},
            "source_status": [],
            "groups": {},
            "items": [],
            "account_hourly": {
                "by_ai_account": [
                    {
                        "provider": "openai",
                        "account_id": "86b44ff3-d85f-4fa7-bbbb-1a662509b3b7",
                        "label": "startimessocietegn@gmail.com",
                        "display_name": "StarTimes",
                        "subscription": "pro",
                    }
                ]
            },
            "limits": [
                {
                    "source_id": "codex-main",
                    "provider": "codex",
                    "window": "session",
                    "used_percent": 3,
                    "remaining_percent": 97,
                    "reset_at": "2026-06-02T15:45:00+08:00",
                    "window_duration_minutes": 300,
                    "observed_at": "2026-06-02T10:45:00+08:00",
                    "source_type": "runtime_api",
                    "confidence": "observed",
                    "status": "ok",
                    "official": True,
                },
            ],
        })

        window = summary["limits"]["windows"][0]
        self.assertEqual(window["account_label"], "startimessocietegn@gmail.com")
        self.assertEqual(window["account_plan_label"], "Pro 20x")

    def test_merges_same_ai_account_metadata_from_hourly_and_account_registry(self) -> None:
        summary = build_mobile_summary({
            "generated_at": "2026-06-02T10:45:00+08:00",
            "summary": {"period": "today", "total_tokens": 0},
            "trend": {"points": []},
            "source_status": [],
            "groups": {},
            "items": [],
            "account_hourly": {
                "by_ai_account": [
                    {
                        "provider": "openai",
                        "account_id": "86b44ff3-d85f-4fa7-bbbb-1a662509b3b7",
                        "label": "startimessocietegn@gmail.com",
                    }
                ]
            },
            "ai_accounts": [
                {
                    "provider": "codex",
                    "account_id": "86b44ff3-d85f-4fa7-bbbb-1a662509b3b7",
                    "label": "startimessocietegn@gmail.com",
                    "subscription": "pro",
                }
            ],
            "limits": [
                {
                    "source_id": "codex-main",
                    "provider": "codex",
                    "window": "session",
                    "used_percent": 3,
                    "remaining_percent": 97,
                    "reset_at": "2026-06-02T15:45:00+08:00",
                    "window_duration_minutes": 300,
                    "observed_at": "2026-06-02T10:45:00+08:00",
                    "source_type": "runtime_api",
                    "confidence": "observed",
                    "status": "ok",
                    "official": True,
                },
            ],
        })

        window = summary["limits"]["windows"][0]
        self.assertEqual(window["account_label"], "startimessocietegn@gmail.com")
        self.assertEqual(window["account_plan_label"], "Pro 20x")

    def test_redacts_unsafe_account_labels(self) -> None:
        summary = build_mobile_summary({
            "generated_at": "2026-06-02T10:45:00+08:00",
            "summary": {"period": "today", "total_tokens": 1200},
            "trend": {"points": []},
            "source_status": [],
            "groups": {},
            "items": [],
            "limits": [
                {
                    "source_id": "codex-main",
                    "provider": "codex",
                    "window": "session",
                    "used_percent": 3,
                    "remaining_percent": 97,
                    "reset_at": "2026-06-02T15:45:00+08:00",
                    "window_duration_minutes": 300,
                    "observed_at": "2026-06-02T10:45:00+08:00",
                    "source_type": "runtime_api",
                    "confidence": "observed",
                    "status": "ok",
                    "official": True,
                    "account_email": "/Users/example/.codex/auth.json",
                    "account_label": "sk-secret-token",
                    "account_plan": "prolite",
                },
            ],
        })

        window = summary["limits"]["windows"][0]
        self.assertNotIn("account_label", window)
        self.assertEqual(window["account_plan_label"], "Pro 5x")

    def test_humanizes_safe_unknown_plan_labels_without_internal_separators(self) -> None:
        summary = build_mobile_summary({
            "generated_at": "2026-06-02T10:45:00+08:00",
            "summary": {"period": "today", "total_tokens": 1200},
            "trend": {"points": []},
            "source_status": [],
            "groups": {},
            "items": [],
            "limits": [
                {
                    "source_id": "codex-main",
                    "provider": "codex",
                    "window": "week",
                    "used_percent": 3,
                    "remaining_percent": 97,
                    "reset_at": "2026-06-08T00:00:00+08:00",
                    "window_duration_minutes": 10080,
                    "observed_at": "2026-06-02T10:45:00+08:00",
                    "source_type": "runtime_api",
                    "confidence": "observed",
                    "status": "ok",
                    "official": True,
                    "account_plan": "max_5x",
                },
            ],
        })

        self.assertEqual(summary["limits"]["windows"][0]["account_plan_label"], "Max 5x")

    def test_sources_only_include_non_zero_contributors_for_selected_period(self) -> None:
        summary = build_mobile_summary({
            "summary": {"period": "week", "total_tokens": 7000},
            "trend": {"points": []},
            "source_status": [
                {"source_id": f"source-{idx}", "machine": f"machine-{idx}", "os_user": f"user-{idx}", "status": "ok", "observed_at": "2026-06-02T10:40:00+08:00"}
                for idx in range(5)
            ],
            "groups": {
                "by_machine": [
                    {
                        "name": f"machine-{idx}",
                        "display_name": f"machine-{idx}",
                        "total_tokens": tokens,
                        "source_ids": [f"source-{idx}"],
                    }
                    for idx, tokens in enumerate([4000, 0, 1500, 0, 1500])
                ]
            },
            "items": [],
            "limits": [],
        })

        self.assertEqual([row["label"] for row in summary["breakdown"]["by_machine"]], ["machine-0", "machine-2", "machine-4"])
        self.assertEqual([source["source_id"] for source in summary["sources"]], ["source-0", "source-2", "source-4"])

    def test_failed_zero_source_remains_available_for_health_context(self) -> None:
        summary = build_mobile_summary({
            "summary": {"period": "today", "total_tokens": 4000},
            "trend": {"points": []},
            "source_status": [
                {"source_id": "active", "machine": "active-host", "os_user": "wang", "status": "ok", "observed_at": "2026-06-02T10:40:00+08:00"},
                {"source_id": "failed", "machine": "failed-host", "os_user": "old", "status": "provider_failed", "observed_at": "2026-06-02T09:40:00+08:00"},
                {"source_id": "idle", "machine": "idle-host", "os_user": "old", "status": "ok", "observed_at": "2026-06-02T09:40:00+08:00"},
            ],
            "groups": {
                "by_machine": [
                    {"name": "active-host", "display_name": "active-host", "total_tokens": 4000, "source_ids": ["active"]},
                    {"name": "failed-host", "display_name": "failed-host", "total_tokens": 0, "source_ids": ["failed"]},
                    {"name": "idle-host", "display_name": "idle-host", "total_tokens": 0, "source_ids": ["idle"]},
                ]
            },
            "items": [],
            "limits": [],
        })

        self.assertEqual([row["label"] for row in summary["breakdown"]["by_machine"]], ["active-host"])
        self.assertEqual([source["source_id"] for source in summary["sources"]], ["active", "failed"])

    def test_os_user_breakdown_filters_zero_token_users(self) -> None:
        summary = build_mobile_summary({
            "summary": {"period": "today", "total_tokens": 4000},
            "trend": {"points": []},
            "source_status": [],
            "groups": {
                "by_machine": [
                    {
                        "name": "active-host",
                        "display_name": "active-host",
                        "total_tokens": 4000,
                        "source_ids": ["active", "idle"],
                        "users": [
                            {"account": "wang", "total_tokens": 4000, "source_ids": ["active"]},
                            {"account": "LIUDS", "total_tokens": 0, "source_ids": ["idle"]},
                        ],
                    }
                ]
            },
            "items": [],
            "limits": [],
        })

        self.assertEqual([row["label"] for row in summary["breakdown"]["by_os_user"]], ["wang"])

    def test_sources_empty_when_every_contributor_is_zero(self) -> None:
        summary = build_mobile_summary({
            "summary": {"period": "month", "total_tokens": 0},
            "trend": {"points": []},
            "source_status": [
                {"source_id": "old", "machine": "old-host", "os_user": "LIUDS", "status": "ok", "observed_at": "2026-06-02T10:40:00+08:00"}
            ],
            "groups": {
                "by_machine": [
                    {"name": "old-host", "display_name": "old-host", "total_tokens": 0, "source_ids": ["old"]}
                ]
            },
            "items": [],
            "limits": [],
        })

        self.assertEqual(summary["breakdown"]["by_machine"], [])
        self.assertEqual(summary["sources"], [])


if __name__ == "__main__":
    unittest.main()
