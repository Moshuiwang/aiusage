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

    def test_ios_xcode_project_uses_company_development_team(self) -> None:
        project_yml = ROOT / "mobile" / "ios-xcode" / "project.yml"
        project_pbxproj = (
            ROOT / "mobile" / "ios-xcode" / "AIUsageMobile.xcodeproj" / "project.pbxproj"
        )

        self.assertIn(
            "DEVELOPMENT_TEAM: HL4BQ6T4HU",
            project_yml.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "DEVELOPMENT_TEAM = HL4BQ6T4HU;",
            project_pbxproj.read_text(encoding="utf-8"),
        )

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

    def test_multi_platform_brand_icon_assets_are_wired(self) -> None:
        token_svg = ROOT / "packages" / "design-tokens" / "ai-usage-icon.svg"
        self.assertTrue(token_svg.exists())
        svg = token_svg.read_text(encoding="utf-8")
        for token in [
            "#DA7756",
            "#0a84ff",
            "#1e2035",
            "#0c0d18",
            'r="38"',
            'stroke-width="11"',
            'stroke-dasharray="167.1 238.8"',
            'r="20"',
            'stroke-width="9"',
            'stroke-dasharray="56.5 125.7"',
            'r="3.5"',
            'id="outer-ring"',
            'id="inner-ring"',
            'id="center-dot"',
        ]:
            with self.subTest(token=token):
                self.assertIn(token, svg)
        self.assertNotIn("linearGradient", svg)
        self.assertNotIn("center-pulse", svg)

        app_icon_dir = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Resources"
            / "Assets.xcassets"
            / "AppIcon.appiconset"
        )
        self.assertTrue((app_icon_dir / "AIUsageIconSource.svg").exists())

        contents = (app_icon_dir / "Contents.json").read_text(encoding="utf-8")
        for filename, size in [
            ("AppIcon-20@2x.png", (40, 40)),
            ("AppIcon-20@3x.png", (60, 60)),
            ("AppIcon-29@2x.png", (58, 58)),
            ("AppIcon-29@3x.png", (87, 87)),
            ("AppIcon-40@2x.png", (80, 80)),
            ("AppIcon-40@3x.png", (120, 120)),
            ("AppIcon-60@2x.png", (120, 120)),
            ("AppIcon-60@3x.png", (180, 180)),
            ("AppIcon-1024.png", (1024, 1024)),
        ]:
            with self.subTest(filename=filename):
                self.assertIn(filename, contents)
                self.assertEqual(self._png_size(app_icon_dir / filename), size)

        mac_icon = ROOT / "clients" / "macos" / "Resources" / "AIUsageMenuBar.icns"
        self.assertTrue(mac_icon.exists())
        self.assertGreater(mac_icon.stat().st_size, 10_000)

    def test_brand_surfaces_do_not_use_placeholder_chart_icon(self) -> None:
        surfaces = {
            "web": ROOT / "src" / "ai_usage_widget" / "static" / "index.html",
            "ios": ROOT / "mobile" / "ios" / "Sources" / "AIUsageMobileCore" / "AIUsageMobileRootView.swift",
            "widget": (
                ROOT
                / "mobile"
                / "ios"
                / "Sources"
                / "AIUsageMobileCore"
                / "WidgetSummary.swift"
            ),
            "macos": (
                ROOT
                / "clients"
                / "macos"
                / "Sources"
                / "AIUsageMenuBarApp"
                / "MenuBarPopoverView.swift"
            ),
        }
        for surface, path in surfaces.items():
            with self.subTest(surface=surface):
                content = path.read_text(encoding="utf-8")
                self.assertIn("AIUsageBrandMark", content)
                self.assertNotIn('Image(systemName: "chart.bar.xaxis")', content)
                self.assertNotIn("brand-placeholder", content)

    def test_ios_home_uses_multi_platform_design_dashboard_components(self) -> None:
        root_view = ROOT / "mobile" / "ios" / "Sources" / "AIUsageMobileCore" / "AIUsageMobileRootView.swift"
        content = root_view.read_text(encoding="utf-8")
        for component in [
            "CrossPlatformHomeHeader",
            "CrossPlatformHeroPanel",
            "CrossPlatformQuotaSection",
            "CrossPlatformSourcesSection",
        ]:
            with self.subTest(component=component):
                self.assertIn(component, content)
        self.assertNotIn("Color.blue.opacity(0.20)", content)

    def test_mobile_app_widget_and_watch_share_brand_mark(self) -> None:
        surfaces = {
            "ios_home": ROOT / "mobile" / "ios" / "Sources" / "AIUsageMobileCore" / "AIUsageMobileRootView.swift",
            "widget": (
                ROOT
                / "mobile"
                / "ios"
                / "Sources"
                / "AIUsageMobileCore"
                / "WidgetSummary.swift"
            ),
            "watch": (
                ROOT
                / "mobile"
                / "ios-xcode"
                / "Sources"
                / "AIUsageMobileWidgetExtension"
                / "AIUsageWatchApp.swift"
            ),
        }
        for surface, path in surfaces.items():
            with self.subTest(surface=surface):
                content = path.read_text(encoding="utf-8")
                self.assertIn("AIUsageBrandMark", content)
                self.assertNotIn('Image(systemName: "chart.bar.xaxis")', content)

    def test_widget_supports_small_medium_and_large(self) -> None:
        widget = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Sources"
            / "AIUsageMobileWidgetExtension"
            / "AIUsageMobileWidget.swift"
        )
        content = widget.read_text(encoding="utf-8")
        self.assertIn(".systemSmall", content)
        self.assertIn(".systemMedium", content)
        self.assertIn(".systemLarge", content)
        self.assertIn("AIUsageLargeWidgetContentView", content)

        widget_summary = (
            ROOT
            / "mobile"
            / "ios"
            / "Sources"
            / "AIUsageMobileCore"
            / "WidgetSummary.swift"
        ).read_text(encoding="utf-8")
        medium_start = widget_summary.find("struct AIUsageMediumWidgetContentView")
        large_start = widget_summary.find("struct AIUsageLargeWidgetContentView")
        medium_content = widget_summary[medium_start:large_start]
        self.assertIn("state.statusText", medium_content)
        self.assertIn("state.updatedText", medium_content)

    def test_ios_app_and_widget_share_live_summary_cache(self) -> None:
        project_yml = ROOT / "mobile" / "ios-xcode" / "project.yml"
        app = ROOT / "mobile" / "ios-xcode" / "Sources" / "AIUsageMobileApp" / "AIUsageMobileApp.swift"
        widget = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Sources"
            / "AIUsageMobileWidgetExtension"
            / "AIUsageMobileWidget.swift"
        )
        cache = ROOT / "mobile" / "ios" / "Sources" / "AIUsageMobileCore" / "MobileSummaryCache.swift"

        self.assertTrue(cache.exists())
        project_content = project_yml.read_text(encoding="utf-8")
        self.assertIn("group.com.wangzhipeng.aiusage", project_content)
        self.assertIn("AIUsageMobileApp.entitlements", project_content)
        self.assertIn("AIUsageMobileWidgetExtension.entitlements", project_content)

        app_content = app.read_text(encoding="utf-8")
        self.assertIn("shareWithCompanionIfNeeded", app_content)
        self.assertIn("MobileSummaryCache.isCompanionEligible", app_content)
        self.assertIn("MobileSummaryCache.writeToAppGroup", app_content)

        widget_content = widget.read_text(encoding="utf-8")
        self.assertIn("MobileSummaryCache.readFromAppGroup", widget_content)
        self.assertIn("MobileSummaryFixture.empty", widget_content)
        self.assertNotIn("bundle.url(forResource: \"mobile-summary\"", widget_content)

    def test_watch_target_is_read_only_summary_app(self) -> None:
        project_yml = ROOT / "mobile" / "ios-xcode" / "project.yml"
        watch_app = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Sources"
            / "AIUsageMobileWidgetExtension"
            / "AIUsageWatchApp.swift"
        )
        project_content = project_yml.read_text(encoding="utf-8")
        watch_content = watch_app.read_text(encoding="utf-8")

        self.assertIn("AIUsageWatchApp", project_content)
        self.assertIn("platform: watchOS", project_content)
        self.assertIn("com.wangzhipeng.aiusage.watch", project_content)
        self.assertIn("@main", watch_content)
        self.assertIn("AIUsageWatchSummaryView", watch_content)
        self.assertIn("WatchConnectivity", watch_content)
        self.assertIn("didReceiveApplicationContext", watch_content)
        self.assertIn("mobileSummary", watch_content)
        self.assertIn("WatchSummaryStore", watch_content)
        self.assertIn("decoded.period.id == \"today\"", watch_content)
        self.assertIn("isStale", watch_content)
        self.assertIn("updatedText", watch_content)
        forbidden = ["ccusage", "SQLite", ".codex", ".claude", "Authorization", "Bearer", "URLSession", "ssh"]
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, watch_content)

        app_content = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Sources"
            / "AIUsageMobileApp"
            / "AIUsageMobileApp.swift"
        ).read_text(encoding="utf-8")
        self.assertIn("WatchSummaryBridge.shared.activate", app_content)
        self.assertIn("WatchSummaryBridge.shared.push", app_content)

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
            "bundle.object(forInfoDictionaryKey: \"AIUsageAPIToken\")",
            "Widget runtime config sharing requires explicit App Group + Keychain access group design",
            "CrossPlatformHomeHeader",
            "CrossPlatformHeroPanel",
            "CompactHandoffBarChart",
            "CrossPlatformQuotaSection",
            "CrossPlatformSourcesSection",
            "lastServerReadText",
            "AIUsageBrandMark(size: 30)",
            "onRefresh",
            "RefreshActionButton",
            "CustomGlassTabBar",
            "GlassSurface",
            "BrandIcon",
            "BrandIcon.kind(for:",
            "LiquidGlassTabButton",
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
            "state.tokenBreakdownText",
            ".frame(height: 52, alignment: .bottom)",
            "state.topSources",
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
