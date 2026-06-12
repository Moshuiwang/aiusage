from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "ai_usage_widget" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


class TestDashboardStaticContracts(unittest.TestCase):
    def test_mobile_hero_total_block_does_not_reserve_desktop_width(self) -> None:
        css = _read("dashboard.css")

        self.assertIn("@media (max-width: 860px)", css)
        self.assertIn(".hero-total-block", css)
        self.assertIn("flex: 0 1 auto", css)
        self.assertIn("width: 100%", css)
        self.assertIn("min-width: 0", css)

    def test_limits_are_grouped_fresh_and_timestamped(self) -> None:
        js = _read("dashboard.js")

        self.assertIn("normalizeLimitRows", js)
        self.assertIn("renderLimitGroup", js)
        self.assertIn("isExpiredLimit", js)
        self.assertIn("最近更新", js)
        self.assertIn("limit-group", js)
        self.assertIn("source_id", js)

    def test_sources_are_sorted_online_first_with_user_at_host_identity(self) -> None:
        js = _read("dashboard.js")

        self.assertIn("sortSourcesForDisplay", js)
        self.assertIn("formatSourceIdentity", js)
        self.assertIn("@", js)
        self.assertIn("statusRank", js)

    def test_stream_chart_uses_integer_nice_ticks(self) -> None:
        js = _read("dashboard.js")

        self.assertIn("niceChartTicks", js)
        self.assertIn("formatAxisTick", js)
        self.assertIn("Math.ceil", js)
        self.assertNotIn("fmt(max / 2)", js)


if __name__ == "__main__":
    unittest.main()
