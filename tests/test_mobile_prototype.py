import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE_DIR = ROOT / "docs" / "prototypes" / "mobile-app"
HIFI_DIR = ROOT / "docs" / "prototypes" / "ios-high-fidelity"


class MobilePrototypeTests(unittest.TestCase):
    def test_mobile_prototype_files_exist(self) -> None:
        expected = [
            "index.html",
            "styles.css",
            "app.js",
            "fixture.json",
            "README.md",
        ]
        for name in expected:
            with self.subTest(name=name):
                self.assertTrue((PROTOTYPE_DIR / name).exists())

    def test_fixture_is_mock_snapshot_with_expected_domains(self) -> None:
        data = json.loads((PROTOTYPE_DIR / "fixture.json").read_text(encoding="utf-8"))

        self.assertTrue(data["prototype_only"])
        self.assertIn("generated_at", data)
        self.assertIn("summary", data)
        self.assertIn("periods", data)
        self.assertIn("trend", data)
        self.assertIn("sources", data)
        self.assertIn("breakdowns", data)
        self.assertIn("breakdown_detail", data)
        self.assertIn("glossary", data)
        self.assertIn("limits", data)
        self.assertNotIn("ios_widget", data)
        self.assertEqual(data["glossary"]["account"], "OS user")
        self.assertEqual(data["breakdown_detail"]["account"]["children"][0], "date")
        self.assertNotIn("machine", data["breakdown_detail"]["account"]["children"])

        self.assertGreater(data["summary"]["today_total_tokens"], 0)
        for period in ["today", "week", "month", "all"]:
            self.assertIn(period, data["periods"])
            self.assertGreater(data["periods"][period]["total_tokens"], 0)
            self.assertIn(period, data["trend"])
            self.assertGreaterEqual(len(data["trend"][period]), 4)
            for point in data["trend"][period]:
                self.assertIn("input_tokens", point)
                self.assertIn("output_tokens", point)
                self.assertIn("cache_tokens", point)
                self.assertIn("cache_ratio", point)

        self.assertEqual(data["periods"]["week"]["label"], "周")
        self.assertEqual(data["periods"]["month"]["label"], "月")
        self.assertIn("05-28", data["periods"]["week"]["range_label"])
        self.assertIn("05-05", data["periods"]["month"]["range_label"])

        self.assertGreaterEqual(len(data["sources"]), 3)
        for period in ["today", "week", "month", "all"]:
            self.assertIn(period, data["breakdowns"])
            self.assertIn("machine", data["breakdowns"][period])
            self.assertIn("agent", data["breakdowns"][period])
            self.assertIn("model", data["breakdowns"][period])
            self.assertIn("date", data["breakdowns"][period])

        states = {source["status"] for source in data["sources"]}
        self.assertIn("ok", states)
        self.assertIn("stale", states)
        self.assertIn("command_failed", states)

        confidences = {window["confidence"] for window in data["limits"]["windows"]}
        self.assertIn("observed", confidences)
        self.assertIn("missing", confidences)

        providers = {window["provider"] for window in data["limits"]["windows"]}
        accounts = {window["account_label"] for window in data["limits"]["windows"]}
        windows = {window["window"] for window in data["limits"]["windows"]}
        self.assertIn("Codex", providers)
        self.assertIn("Claude Code", providers)
        self.assertGreaterEqual(len(accounts), 2)
        self.assertIn("5h", windows)
        self.assertIn("weekly", windows)

    def test_html_exposes_four_mobile_views_and_no_production_endpoint(self) -> None:
        html = (PROTOTYPE_DIR / "index.html").read_text(encoding="utf-8")

        for view_id in ["home", "sources", "breakdown", "limits"]:
            self.assertIn(f'data-view="{view_id}"', html)
            self.assertIn(f'data-tab="{view_id}"', html)

        self.assertIn('name="viewport"', html)
        self.assertIn("viewport-fit=cover", html)
        self.assertIn('data-visual-version="v10"', html)
        self.assertIn('data-current-view="home"', html)
        self.assertIn('data-material="liquid-glass"', html)
        self.assertIn("ios-navigation", html)
        self.assertIn("navigation-title", html)
        self.assertIn("home-only-header", html)
        self.assertIn("system-status", html)
        self.assertIn("home-indicator", html)
        self.assertNotIn("widget-preview", html)
        self.assertNotIn('id="widgetSmallTotal"', html)
        self.assertNotIn('id="widgetMediumLimit"', html)
        self.assertNotIn("sf-symbol", html)
        self.assertIn("view-masthead", html)
        self.assertIn("secondary-summary", html)
        for label in ["首页", "来源", "明细", "额度", "采集列表", "额度列表"]:
            self.assertIn(label, html)
        self.assertNotIn(">Sources<", html)
        self.assertNotIn(">Limits<", html)
        self.assertIn('id="sourceHealthScore"', html)
        self.assertIn('id="breakdownPeriodMeta"', html)
        self.assertIn('id="limitsObservedScore"', html)
        self.assertNotIn("今日观测", html)
        self.assertIn("fixture.json", html)
        for period in ["today", "week", "month", "all"]:
            self.assertIn(f'data-period="{period}"', html)
        self.assertIn('id="usageTrend"', html)
        self.assertIn('id="trendTooltip"', html)
        self.assertIn('data-tab-shortcut="breakdown"', html)
        self.assertIn('id="limitReminderSwitch"', html)
        self.assertIn("reminder-switch", html)
        self.assertIn("OS User", html)
        self.assertIn('id="breakdownDetailPanel"', html)
        self.assertIn('id="detailClose"', html)
        self.assertNotIn("/api/summary", html)
        self.assertNotIn("usage.sqlite", html)
        self.assertNotIn("ccusage", html)
        self.assertNotIn("ssh", html.lower())

    def test_js_keeps_prototype_read_only_and_renders_fixture_fields(self) -> None:
        js = (PROTOTYPE_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn('fetch("fixture.json"', js)
        self.assertIn("renderHome", js)
        for label in ["正常", "过期", "失败", "缺失", "可信"]:
            self.assertIn(label, js)
        for label in ["观测", "上报", "剩余", "重置"]:
            self.assertIn(label, js)
        self.assertIn("renderPeriodMetrics", js)
        self.assertIn("renderTrend", js)
        self.assertIn("renderTrendTooltip", js)
        self.assertIn("showTrendTooltip", js)
        self.assertIn("setView(button.dataset.tabShortcut)", js)
        self.assertIn("document.body.dataset.currentView", js)
        self.assertIn("window.scrollTo(0, 0)", js)
        self.assertIn("reminder", js.lower())
        self.assertIn("cache_ratio", js)
        self.assertIn("renderSources", js)
        self.assertIn("个来源", js)
        self.assertIn("renderBreakdown", js)
        self.assertIn("按机器", js)
        self.assertIn("按系统账户", js)
        self.assertIn("按模型", js)
        self.assertIn("showBreakdownDetail", js)
        self.assertIn("hideBreakdownDetail", js)
        self.assertIn("breakdown_detail", js)
        self.assertIn("sourceHealthScore", js)
        self.assertIn("breakdownPeriodMeta", js)
        self.assertIn("limitsObservedScore", js)
        self.assertNotIn("renderWidgetPreview", js)
        self.assertNotIn("widgetSmallTotal", js)
        self.assertNotIn("widgetMediumLimit", js)
        self.assertIn("renderLimits", js)
        self.assertIn("可信窗口", js)
        self.assertIn("缺失窗口", js)
        self.assertIn("OAuth weekly 用量来源未配置", js)
        self.assertIn("周日", js)
        self.assertNotIn("remaining · reset", js)
        self.assertNotIn("Observed ${", js)
        self.assertNotIn("Pushed ${", js)
        self.assertIn("data-provenance", js)
        self.assertNotIn("POST", js)
        self.assertNotIn("/ingest", js)
        self.assertNotIn("/api/summary", js)

    def test_css_targets_phone_width_and_stable_tab_bar(self) -> None:
        css = (PROTOTYPE_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertIn("max-width: 430px", css)
        self.assertIn("color-scheme: light dark", css)
        self.assertIn("@media (prefers-color-scheme: light)", css)
        self.assertIn("@media (prefers-color-scheme: dark)", css)
        self.assertIn("--system-background", css)
        self.assertIn("--label", css)
        self.assertIn("--secondary-label", css)
        self.assertIn("--system-blue", css)
        self.assertIn("env(safe-area-inset-top)", css)
        self.assertIn("env(safe-area-inset-bottom)", css)
        self.assertIn("-webkit-backdrop-filter", css)
        self.assertIn(".system-status", css)
        self.assertIn(".ios-navigation", css)
        self.assertIn(".navigation-title", css)
        self.assertIn('body:not([data-current-view="home"]) .home-only-header', css)
        self.assertIn(".dynamic-island", css)
        self.assertIn(".home-indicator", css)
        self.assertNotIn(".widget-preview", css)
        self.assertNotIn(".widget-card", css)
        self.assertNotIn(".sf-symbol", css)
        self.assertIn("position: sticky", css)
        self.assertIn("padding-bottom: 68px", css)
        self.assertIn(".tab-bar", css)
        self.assertIn(".period-selector", css)
        self.assertIn(".health-compact", css)
        self.assertIn(".usage-trend", css)
        self.assertIn(".trend-tooltip", css)
        self.assertIn(".action-link", css)
        self.assertIn(".reminder-switch", css)
        self.assertIn(".detail-panel", css)
        self.assertIn(".detail-backdrop", css)
        self.assertIn("--app-bg", css)
        self.assertIn("--card-bg", css)
        self.assertIn("--accent", css)
        self.assertIn(".phone-shell::before", css)
        self.assertIn(".hero-panel::after", css)
        self.assertIn(".view-masthead", css)
        self.assertIn(".secondary-summary", css)
        self.assertIn("min-height: 74px", css)
        self.assertIn(".masthead-stat", css)
        self.assertIn(".status-dot", css)
        self.assertIn(".tab-bar button[aria-current=\"page\"] span", css)
        self.assertIn("@media", css)

    def test_ios_high_fidelity_app_is_generated_from_wireframe_structure(self) -> None:
        html = (HIFI_DIR / "index.html").read_text(encoding="utf-8")
        css = (HIFI_DIR / "styles.css").read_text(encoding="utf-8")
        js = (HIFI_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn("AI Usage", html)
        self.assertIn('aria-label="AI Usage App"', html)
        self.assertIn('data-material="native-glass"', html)
        for view_id in ["home", "sources", "breakdown", "limits"]:
            self.assertIn(f'data-view="{view_id}"', html)
            self.assertIn(f'data-tab="{view_id}"', html)
        for label in ["首页", "额度", "明细", "来源", "刷新时间", "采集列表", "用量明细"]:
            self.assertIn(label, html)

        self.assertIn("backdrop-filter", css)
        self.assertIn("tabbar", css)
        self.assertIn("quota-gauge", css)
        self.assertIn("agent-logo", css)
        self.assertNotIn("Droplet", html)
        self.assertNotIn("blood", html.lower())
        self.assertNotIn("5.2-9.4", html)

        self.assertIn("drawTrend", js)
        self.assertIn("ctx.roundRect", js)
        self.assertNotIn("ctx.lineTo(point.x", js)
        self.assertNotIn("line chart", js.lower())


if __name__ == "__main__":
    unittest.main()
