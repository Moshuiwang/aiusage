from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "ai_usage_widget" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


class TestDashboardStaticContracts(unittest.TestCase):
    def test_web_header_uses_dual_ring_brand_mark(self) -> None:
        html = _read("index.html")
        css = _read("dashboard.css")

        self.assertIn("AIUsageBrandMark", html)
        self.assertIn("brand-mark__outer-ring", html)
        self.assertIn("brand-mark__inner-ring", html)
        self.assertIn(".dashboard-brand", css)
        self.assertIn(".brand-mark__outer-ring", css)
        self.assertIn(".brand-mark__inner-ring", css)
        self.assertNotIn("chart.bar.xaxis", html)

    def test_web_dashboard_matches_latest_handoff_structure(self) -> None:
        html = _read("index.html")
        css = _read("dashboard.css")
        js = _read("dashboard.js")

        for marker in [
            'class="web-nav"',
            'id="themeToggle"',
            'id="heroDelta"',
            'id="streamChart"',
            'id="limitsGrid"',
            'id="sourceCards"',
        ]:
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

        for token in [
            "--claude-orange: #DA7756",
            "--openai-blue: #0a84ff",
            "--bg-body: #f5f5f7",
            "grid-template-columns: minmax(0, 1fr) 300px",
            "height: 56px",
            "position: sticky",
        ]:
            with self.subTest(token=token):
                self.assertIn(token, css)

        self.assertIn("renderQuotaCards", js)
        self.assertIn("renderSourceCards", js)
        self.assertIn("renderBarTrend", js)
        self.assertIn("document.body.toggleAttribute(\"data-dark\")", js)

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

    def test_web_source_cards_include_visible_non_ok_zero_usage_sources(self) -> None:
        js = _read("dashboard.js")

        self.assertIn("mergeSourceCards", js)
        self.assertIn("renderSourceCards(data.hosts, latestSnapshot.source_status || [])", js)
        self.assertIn("source.status !== \"ok\"", js)
        self.assertIn("source-card--status", js)
        self.assertIn("statusLabel(source.status)", js)
        self.assertIn("const maxCards = 4", js)
        self.assertIn("const statusBudget = Math.min(2, statusCards.length, maxCards)", js)
        self.assertIn("return statusCards.slice(0, statusBudget).concat(usageCards).slice(0, maxCards)", js)
        self.assertNotIn("cards.slice(0, 4).forEach", js)

    def test_web_hero_badge_does_not_fake_period_delta(self) -> None:
        html = _read("index.html")
        js = _read("dashboard.js")

        self.assertIn("Live", html)
        self.assertIn("renderDelta(latestSnapshot.generated_at)", js)
        self.assertIn("el.heroDelta.textContent = \"Live\"", js)
        self.assertNotIn("((current - previous) / previous)", js)

    def test_stream_chart_uses_integer_nice_ticks(self) -> None:
        js = _read("dashboard.js")

        self.assertIn("niceChartTicks", js)
        self.assertIn("formatAxisTick", js)
        self.assertIn("Math.ceil", js)
        self.assertNotIn("fmt(max / 2)", js)


if __name__ == "__main__":
    unittest.main()
