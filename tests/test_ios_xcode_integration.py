from __future__ import annotations

import pathlib
import struct
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class IOSXcodeIntegrationTests(unittest.TestCase):
    def test_xcodegen_project_hosts_app_and_widget_targets(self) -> None:
        project_yml = ROOT / "mobile" / "ios-xcode" / "project.yml"
        self.assertTrue(project_yml.exists())

        content = project_yml.read_text(encoding="utf-8")
        self.assertIn("AIUsageMobileApp", content)
        self.assertIn("AIUsageMobileWidgetExtension", content)
        self.assertIn("AIUsageMobileCore", content)
        self.assertIn("com.wangzhipeng.aiusage.mobile", content)

    def test_app_and_widget_entrypoints_exist(self) -> None:
        expected = [
            ROOT / "mobile" / "ios-xcode" / "Sources" / "AIUsageMobileApp" / "AIUsageMobileApp.swift",
            ROOT / "mobile" / "ios-xcode" / "Sources" / "AIUsageMobileWidgetExtension" / "AIUsageMobileWidget.swift",
            ROOT / "mobile" / "ios-xcode" / "Resources" / "mobile-summary.json",
        ]
        for path in expected:
            with self.subTest(path=str(path)):
                self.assertTrue(path.exists())

    def test_app_target_declares_real_app_icon_asset(self) -> None:
        project_yml = ROOT / "mobile" / "ios-xcode" / "project.yml"
        content = project_yml.read_text(encoding="utf-8")
        self.assertIn("Resources/Assets.xcassets", content)
        self.assertIn("ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon", content)

        app_icon_dir = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Resources"
            / "Assets.xcassets"
            / "AppIcon.appiconset"
        )
        self.assertTrue((app_icon_dir / "Contents.json").exists())

        icon_1024 = app_icon_dir / "AppIcon-1024.png"
        self.assertTrue(icon_1024.exists())
        self.assertEqual(self._png_size(icon_1024), (1024, 1024))

    def test_device_install_guard_requires_live_token_and_exact_production_url(self) -> None:
        script = ROOT / "mobile" / "ios-xcode" / "install_device_with_live_config.py"
        self.assertTrue(script.exists())

        content = script.read_text(encoding="utf-8")
        required_guards = [
            "PRODUCTION_BASE_URL = \"https://vpn2.chunbai.com:8443\"",
            "SUMMARY_SMOKE_PATH = \"/api/mobile/summary?period=all\"",
            "verify_production_summary",
            "Authorization",
            "Bearer ",
            "read_token_from_vpn2_systemd",
            "systemctl",
            "show",
            "ai-usage-server",
            "--preflight-only",
            "write_temp_xcconfig",
            "https:/$()/vpn2.chunbai.com:8443",
            "verify_built_app_config",
            "AIUsageAPIBaseURL",
            "AIUsageAPIToken",
            "token_length",
            "raise RuntimeError(\"refusing to install",
            "install_app",
            "cleanup_secret_files",
        ]
        for guard in required_guards:
            with self.subTest(guard=guard):
                self.assertIn(guard, content)

    def test_swiftui_surface_matches_approved_mobile_prototype_shape(self) -> None:
        root_view = (
            ROOT
            / "mobile"
            / "ios"
            / "Sources"
            / "AIUsageMobileCore"
            / "AIUsageMobileRootView.swift"
        )
        app_entrypoint = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Sources"
            / "AIUsageMobileApp"
            / "AIUsageMobileApp.swift"
        )
        api_client = (
            ROOT
            / "mobile"
            / "ios"
            / "Sources"
            / "AIUsageMobileCore"
            / "MobileSummaryAPIClient.swift"
        )
        runtime_config = (
            ROOT
            / "mobile"
            / "ios"
            / "Sources"
            / "AIUsageMobileCore"
            / "MobileSummaryRuntimeConfig.swift"
        )
        content = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [root_view, app_entrypoint, api_client, runtime_config]
            if path.exists()
        )

        required_components = [
            "MobileSummaryAPIClient",
            "AI_USAGE_API_BASE_URL",
            "AI_USAGE_PERIOD",
            "AIUsageAPIBaseURL",
            "AIUsageAPIToken",
            "AIUsagePeriod",
            "https://vpn2.chunbai.com:8443",
            "AI_USAGE_ALLOW_NON_PROD_SERVER",
            "isProductionServer",
            "ProductionConnectionStatusView",
            "LiveSummaryContainerView",
            "PeriodSelector",
            "onPeriodSelected",
            "loadLiveSummary(period:",
            "MobileSummaryAPIConfig(",
            "MobileServerSettingsView",
            "MobileTokenStore",
            "KeychainTokenStore",
            "SecureField(\"Token\"",
            "saveSettings(",
            "defaults.removeObject(forKey: \"AIUsageAPIToken\")",
            "Widget runtime config sharing requires explicit App Group + Keychain access group design",
            "MetricTile",
            "MetricGrid",
            "cacheHitText",
            "lastServerReadText",
            "HomeHeader(",
            "onRefresh",
            "RefreshActionButton",
            "UsageTrendChart",
            "CustomGlassTabBar",
            "GlassSurface",
            "BrandIcon",
            "BrandIcon.kind(for:",
            "LiquidGlassTabButton",
            "BarTrendChart",
            "TrendPointSelection",
            "selectedPointIndicator",
            "DragGesture(minimumDistance: 0)",
            "nearestPoint(",
            "LimitReminderRow",
            "RefreshSummaryCard",
            "LimitAccountGroupCard",
            "QuotaPageHeader",
            "limitGroups",
            "UnifiedDetailLink",
            "MaterialCard",
            "safeAreaInset(edge: .bottom)",
            "initialTabID",
            "@State private var selectedPeriodID",
            "@Binding var selectedPeriodID",
            ".onChange(of: state.home.periodID)",
            "onPeriodSelected(period.id)",
            "guard selectedPeriodID != period.id else",
            "refreshingPeriodID",
            "cachedSummaries",
            "MobilePeriodSelection.decision",
            "keepVisibleSummary",
            ".onChange(of: selectedPeriodID)",
            "@State private var selectedPoint",
            "TrendTooltipBubble",
            "tooltipX(",
            ".onChange(of: points)",
            "Input \\(TokenFormat.compact(point.inputTokens))",
            "Output \\(TokenFormat.compact(point.outputTokens))",
            "Cache \\(TokenFormat.compact(point.cacheTokens))",
            "缓存 \\(point.cacheRatio)%",
            "@State private var selectedRow",
            "selectedRow = row",
            "BreakdownDrilldownView",
            "DrilldownSectionCard",
            "BreakdownDrilldown.sections",
            "static let allCases: [BreakdownDimension] = [.date, .machine, .account, .model, .agent]",
            "返回明细",
            "当前周期下钻",
            "查看明细",
        ]
        for component in required_components:
            with self.subTest(component=component):
                self.assertIn(component, content)

        self.assertNotIn("if let point = selectedPoint {\n                Text(trendDetailText(point))", content)
        self.assertNotIn("ForEach(Array(chartPoints.enumerated())", content)
        self.assertNotIn("MobileSummaryFixtureLoader.load()", content)
        self.assertNotIn("loadState = .fixture", content)
        self.assertNotIn("environment[\"AI_USAGE_API_TOKEN\"]", content)
        self.assertNotIn("bundle.object(forInfoDictionaryKey: \"AIUsageAPIToken\")", content)
        self.assertNotIn("defaults.string(forKey: \"AIUsageAPIToken\")", content)
        self.assertNotIn("summary = .empty(periodID: period)\n            loadState = .failed", content)
        self.assertNotIn(
            "withAnimation(.easeInOut(duration: 0.16)) {\n            summary = .empty(periodID: period)",
            content,
        )
        self.assertNotIn("TabView(selection:", content)
        self.assertNotIn("chart.line.uptrend.xyaxis", content)
        self.assertNotIn("linePath(points:", content)
        self.assertNotIn("areaPath(points:", content)
        self.assertNotIn('return "plus.circle"', content)
        self.assertNotIn("droplet", content.lower())
        self.assertLessEqual(content.count("List {"), 0)
        self.assertEqual(content.count("AI Usage"), 1)

    @staticmethod
    def _png_size(path: pathlib.Path) -> tuple[int, int]:
        with path.open("rb") as handle:
            header = handle.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n":
            raise AssertionError(f"{path} is not a PNG")
        return struct.unpack(">II", header[16:24])
