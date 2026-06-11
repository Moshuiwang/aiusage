from __future__ import annotations

import unittest

from ai_usage_widget.mobile_summary import build_mobile_summary


class TestMobileSummaryLimits(unittest.TestCase):
    def test_observed_count_only_counts_official_observed_limit_windows(self) -> None:
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
        self.assertEqual(summary["limits"]["total_count"], 4)
        self.assertEqual(
            [(row["source_id"], row["confidence"], row["official"]) for row in summary["limits"]["windows"]],
            [
                ("codex-main", "observed", True),
                ("local-estimate", "observed", False),
                ("claude-weekly", "missing", False),
                ("codex-stale", "observed", True),
            ],
        )


if __name__ == "__main__":
    unittest.main()
