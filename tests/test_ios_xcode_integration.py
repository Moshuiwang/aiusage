from __future__ import annotations

import pathlib
import struct
import unittest
import zlib


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

    def test_ios_app_icons_are_fully_opaque_square_artwork(self) -> None:
        app_icon_dir = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Resources"
            / "Assets.xcassets"
            / "AppIcon.appiconset"
        )
        icon_paths = sorted(app_icon_dir.glob("*.png"))
        self.assertGreaterEqual(len(icon_paths), 10)
        for path in icon_paths:
            with self.subTest(filename=path.name):
                self.assertEqual(
                    self._png_alpha_extrema(path),
                    (255, 255),
                    "iOS AppIcon PNG must be fully opaque square artwork; transparent corners can flash a backing color during iOS exit animations.",
                )

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
        }
        for surface, path in surfaces.items():
            with self.subTest(surface=surface):
                content = path.read_text(encoding="utf-8")
                self.assertIn("AIUsageBrandMark", content)
                self.assertNotIn('Image(systemName: "chart.bar.xaxis")', content)
                self.assertNotIn("brand-placeholder", content)

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
                / "AIUsageWatchApp"
                / "AIUsageWatchSummaryView.swift"
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
            / "AIUsageWatchApp"
            / "AIUsageWatchApp.swift"
        )
        watch_store = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Sources"
            / "AIUsageWatchApp"
            / "WatchSummaryStore.swift"
        )
        watch_view = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Sources"
            / "AIUsageWatchApp"
            / "AIUsageWatchSummaryView.swift"
        )
        project_content = project_yml.read_text(encoding="utf-8")
        watch_content = "\n".join(
            path.read_text(encoding="utf-8") for path in [watch_app, watch_store, watch_view]
        )

        self.assertIn("AIUsageWatchApp", project_content)
        self.assertIn("platform: watchOS", project_content)
        self.assertIn("com.wangzhipeng.aiusage.mobile.watch", project_content)
        self.assertIn("WKCompanionAppBundleIdentifier: com.wangzhipeng.aiusage.mobile", project_content)
        self.assertIn("@main", watch_content)
        self.assertIn("AIUsageWatchSummaryView", watch_content)
        self.assertIn("WatchConnectivity", watch_content)
        self.assertIn("didReceiveApplicationContext", watch_content)
        self.assertIn("mobileSummary", watch_content)
        self.assertIn("WatchSummaryStore", watch_content)
        self.assertIn("decoded.period.id == \"today\"", watch_content)
        self.assertIn("isStale", watch_content)
        self.assertIn("updatedText", watch_content)
        self.assertIn('reloadTimelines(ofKind: "AIUsageCodexQuotaRingComplication")', watch_content)
        self.assertIn('reloadTimelines(ofKind: "AIUsageClaudeQuotaRingComplication")', watch_content)
        self.assertIn('reloadTimelines(ofKind: "AIUsageTodayChartComplication")', watch_content)
        self.assertNotIn('reloadTimelines(ofKind: "AIUsageWatchWidget")', watch_content)
        forbidden = [
            "ccusage",
            "SQLite",
            "~/.codex",
            "~/.claude",
            "/.codex",
            "/.claude",
            "Authorization",
            "Bearer",
            "URLSession",
            "ssh",
        ]
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
        self.assertIn("ensureTodayCompanionSummary", app_content)
        self.assertIn("transferCurrentComplicationUserInfo", app_content)

    def test_ios_background_refresh_updates_today_watch_summary(self) -> None:
        app_path = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Sources"
            / "AIUsageMobileApp"
            / "AIUsageMobileApp.swift"
        )
        plist_path = ROOT / "mobile" / "ios-xcode" / "Config" / "AIUsageMobileApp-Info.plist"
        project_yml = ROOT / "mobile" / "ios-xcode" / "project.yml"

        app_content = app_path.read_text(encoding="utf-8")
        plist_content = plist_path.read_text(encoding="utf-8")
        project_content = project_yml.read_text(encoding="utf-8")

        task_id = "com.wangzhipeng.aiusage.mobile.watch-refresh"
        self.assertIn("import BackgroundTasks", app_content)
        self.assertIn(task_id, app_content)
        self.assertIn(".backgroundTask(.appRefresh(WatchSummaryBackgroundRefresh.taskIdentifier))", app_content)
        self.assertIn("BGAppRefreshTaskRequest(identifier: taskIdentifier)", app_content)
        self.assertIn("MobileSummaryCache.companionPeriodID", app_content)
        self.assertIn("MobileSummaryAPIClient(config: config).load()", app_content)
        self.assertIn("MobileSummaryCache.writeToAppGroup(loadedSummary)", app_content)
        self.assertNotIn("try? MobileSummaryCache.writeToAppGroup", app_content)
        self.assertIn("watchPushStatus:", app_content)
        self.assertIn("cacheWriteResult", app_content)
        self.assertIn("WatchSummaryBridge.shared.push(loadedSummary)", app_content)
        self.assertIn("BGTaskSchedulerPermittedIdentifiers", plist_content)
        self.assertIn(task_id, plist_content)
        self.assertIn("UIBackgroundModes", plist_content)
        self.assertIn("fetch", plist_content)
        self.assertIn("BGTaskSchedulerPermittedIdentifiers:", project_content)
        self.assertIn("UIBackgroundModes:", project_content)

    def test_ios_background_refresh_is_not_scheduled_before_handler_registration(self) -> None:
        app_path = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Sources"
            / "AIUsageMobileApp"
            / "AIUsageMobileApp.swift"
        )
        app_content = app_path.read_text(encoding="utf-8")
        init_body = app_content[
            app_content.index("    init() {") : app_content.index("    var body: some Scene")
        ]

        self.assertNotIn("WatchSummaryBackgroundRefresh.schedule()", init_body)
        self.assertIn(".backgroundTask(.appRefresh(WatchSummaryBackgroundRefresh.taskIdentifier))", app_content)
        self.assertIn("scheduleWatchSummaryBackgroundRefresh()", app_content)

    def test_watch_companion_and_widget_targets_are_embedded_for_testflight(self) -> None:
        project_yml = ROOT / "mobile" / "ios-xcode" / "project.yml"
        content = project_yml.read_text(encoding="utf-8")

        mobile_target = content[content.index("  AIUsageMobileApp:") : content.index("  AIUsageMobileWidgetExtension:")]
        self.assertIn("target: AIUsageWatchApp", mobile_target)
        self.assertIn("embed: true", mobile_target)

        watch_target = content[content.index("  AIUsageWatchApp:") : content.index("  AIUsageWatchWidgetExtension:")]
        self.assertIn("target: AIUsageWatchWidgetExtension", watch_target)
        self.assertIn("embed: true", watch_target)
        self.assertIn("WKCompanionAppBundleIdentifier: com.wangzhipeng.aiusage.mobile", watch_target)
        self.assertIn("Config/AIUsageWatchApp.entitlements", watch_target)
        self.assertIn("Sources/AIUsageWatchApp", watch_target)
        self.assertNotIn("Sources/AIUsageMobileWidgetExtension/AIUsageWatchApp.swift", watch_target)

        widget_target = content[content.index("  AIUsageWatchWidgetExtension:") :]
        self.assertIn("type: app-extension", widget_target)
        self.assertIn("platform: watchOS", widget_target)
        self.assertIn("com.wangzhipeng.aiusage.mobile.watch.widget", widget_target)
        self.assertIn("Config/AIUsageWatchWidgetExtension.entitlements", widget_target)
        self.assertIn("Sources/AIUsageWatchWidgetExtension", widget_target)
        self.assertIn("NSExtensionPointIdentifier: com.apple.widgetkit-extension", widget_target)
        self.assertNotIn("Resources/mobile-summary.json", watch_target)

    def test_watch_app_and_watch_widget_share_app_group_cache(self) -> None:
        project_yml = ROOT / "mobile" / "ios-xcode" / "project.yml"
        watch_entitlements = ROOT / "mobile" / "ios-xcode" / "Config" / "AIUsageWatchApp.entitlements"
        watch_widget_entitlements = (
            ROOT / "mobile" / "ios-xcode" / "Config" / "AIUsageWatchWidgetExtension.entitlements"
        )
        watch_store = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Sources"
            / "AIUsageWatchApp"
            / "WatchSummaryStore.swift"
        )
        watch_widget = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Sources"
            / "AIUsageWatchWidgetExtension"
            / "AIUsageWatchWidget.swift"
        )
        watch_app = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Sources"
            / "AIUsageWatchApp"
            / "AIUsageWatchApp.swift"
        )

        for path in [watch_entitlements, watch_widget_entitlements, watch_store, watch_widget]:
            with self.subTest(path=str(path)):
                self.assertTrue(path.exists())

        app_group = "group.com.wangzhipeng.aiusage.watch"
        self.assertIn(app_group, project_yml.read_text(encoding="utf-8"))
        self.assertIn(app_group, watch_entitlements.read_text(encoding="utf-8"))
        self.assertIn(app_group, watch_widget_entitlements.read_text(encoding="utf-8"))

        store_content = watch_store.read_text(encoding="utf-8")
        self.assertIn("static let appGroupIdentifier = \"group.com.wangzhipeng.aiusage.watch\"", store_content)
        self.assertIn("containerURL(forSecurityApplicationGroupIdentifier:", store_content)
        self.assertIn("last-watch-summary.json", store_content)
        self.assertIn("last-watch-cache-receipt.json", store_content)
        self.assertIn("cacheWriteStatus", store_content)
        self.assertIn("summaryGeneratedAt", store_content)
        self.assertIn("cacheWrittenAt", store_content)
        self.assertIn("delivery", store_content)
        watch_app_content = watch_app.read_text(encoding="utf-8")
        self.assertIn("watchconnectivity_application_context", watch_app_content)
        self.assertLess(
            watch_app_content.index("self.summary = decoded"),
            watch_app_content.index('guard receipt.cacheWriteStatus == "ok"'),
        )
        self.assertNotIn("try? data.write", store_content)
        self.assertNotIn(".cachesDirectory", store_content)
        self.assertNotIn("AIUsageAPIToken", store_content)
        self.assertNotIn("Bearer", store_content)

        widget_content = watch_widget.read_text(encoding="utf-8")
        self.assertIn("WatchSummaryStore.read()", widget_content)
        self.assertIn(".accessoryRectangular", widget_content)
        self.assertIn(".accessoryCircular", widget_content)
        self.assertIn(".accessoryCorner", widget_content)
        self.assertIn(".accessoryInline", widget_content)
        self.assertIn("AIUsageCodexQuotaRingComplication", widget_content)
        self.assertIn("AIUsageClaudeQuotaRingComplication", widget_content)
        self.assertIn("AIUsageTodayChartComplication", widget_content)
        self.assertIn('configurationDisplayName("AI Usage Codex")', widget_content)
        self.assertIn('configurationDisplayName("AI Usage Claude")', widget_content)
        self.assertIn('configurationDisplayName("AI Usage Today")', widget_content)
        self.assertIn("FixedQuotaRingProvider(selection: .codex)", widget_content)
        self.assertIn("FixedQuotaRingProvider(selection: .claude)", widget_content)
        self.assertIn("TodayChartProvider", widget_content)
        self.assertIn("TodayChartComplicationView", widget_content)
        self.assertIn("ComplicationBarChart", widget_content)
        self.assertIn("widgetCurvesContent()", widget_content)
        self.assertIn("outerUsedPercent", widget_content)
        self.assertIn("innerUsedPercent", widget_content)
        self.assertIn("accountShortName", widget_content)
        self.assertIn("Circle().trim(from: 0, to: CGFloat(entry.state.outerUsedPercent)", widget_content)
        self.assertIn("Circle().trim(from: 0, to: CGFloat(entry.state.innerUsedPercent)", widget_content)
        self.assertIn("WatchSummaryFreshness.isStale(summary)", widget_content)
        self.assertIn("isStale: WatchSummaryFreshness.isStale(summary)", widget_content)
        self.assertIn('Text("stale")', widget_content)
        self.assertIn("state.isStale", widget_content)
        self.assertIn("TodayChartState", widget_content)
        self.assertIn("isStale: WatchSummaryFreshness.isStale(summary)", widget_content)
        self.assertNotIn(".gaugeStyle(.accessoryCircularCapacity)", widget_content)
        self.assertNotIn('Text("AI")', widget_content)
        self.assertIn('return "--"', store_content)
        self.assertIn("TokenFormat.compact(summary.period.totalTokens)", store_content)
        self.assertNotIn(".cachesDirectory", widget_content)
        forbidden = [
            "ccusage",
            "SQLite",
            "~/.codex",
            "~/.claude",
            "/.codex",
            "/.claude",
            "Authorization",
            "Bearer",
            "URLSession",
            "ssh",
        ]
        for token in forbidden:
            with self.subTest(token=token):
                self.assertNotIn(token, widget_content)

    def test_watch_decode_contract_matches_mobile_summary_fixture(self) -> None:
        fixture = (
            ROOT / "mobile" / "ios-xcode" / "Resources" / "mobile-summary.json"
        ).read_text(encoding="utf-8")
        store_content = (
            ROOT
            / "mobile"
            / "ios-xcode"
            / "Sources"
            / "AIUsageWatchApp"
            / "WatchSummaryStore.swift"
        ).read_text(encoding="utf-8")

        for key in [
            '"generated_at"',
            '"timezone"',
            '"period"',
            '"trend"',
            '"points"',
            '"bucket"',
            '"total_tokens"',
            '"input_tokens"',
            '"output_tokens"',
            '"cache_tokens"',
            '"cache_ratio"',
            '"breakdown"',
            '"by_machine"',
            '"limits"',
            '"windows"',
            '"remaining_percent"',
            '"reset_at"',
            '"sources"',
        ]:
            with self.subTest(fixture_key=key):
                self.assertIn(key, fixture)
        for coding_key in [
            'case generatedAt = "generated_at"',
            'case totalTokens = "total_tokens"',
            'case inputTokens = "input_tokens"',
            'case outputTokens = "output_tokens"',
            'case cacheTokens = "cache_tokens"',
            'case cacheRatio = "cache_ratio"',
            'case byMachine = "by_machine"',
            'case remainingPercent = "remaining_percent"',
            'case resetAt = "reset_at"',
        ]:
            with self.subTest(coding_key=coding_key):
                self.assertIn(coding_key, store_content)
        self.assertIn("decodeIfPresent(WatchTrend.self, forKey: .trend)", store_content)
        self.assertIn("WatchTrend(points: [])", store_content)

    def test_device_install_guard_requires_live_token_and_exact_production_url(self) -> None:
        script = ROOT / "mobile" / "ios-xcode" / "install_device_with_live_config.py"
        self.assertTrue(script.exists())

        content = script.read_text(encoding="utf-8")
        required_guards = [
            "PRODUCTION_BASE_URL = \"https://aiusage.chunbai.com\"",
            "SUMMARY_SMOKE_PATH = \"/api/mobile/summary?period=all\"",
            "verify_production_summary",
            "Authorization",
            "Bearer ",
            "User-Agent",
            "AIUsageMobileInstaller/1.0",
            "--preflight-only",
            "write_temp_xcconfig",
            "https:/$()/aiusage.chunbai.com",
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
        self.assertNotIn("vpn2", content)
        self.assertNotIn("systemctl", content)

    def test_bottom_navigation_uses_native_liquid_glass_tab_view(self) -> None:
        root_view = (
            ROOT
            / "mobile"
            / "ios"
            / "Sources"
            / "AIUsageMobileCore"
            / "AIUsageMobileRootView.swift"
        )
        content = root_view.read_text(encoding="utf-8")
        self.assertIn("struct NativeLiquidGlassPeriodTabs", content)
        self.assertIn("NativeLiquidGlassPeriodTabsCapability", content)
        self.assertIn("static let nativeLiquidGlassBehavior", content)
        self.assertIn("TabView(selection:", content)
        self.assertIn(".tabItem", content)
        self.assertIn("nativeLiquidGlassPeriodTabBehavior()", content)
        self.assertIn("tabBarMinimizeBehavior(.onScrollDown)", content)
        self.assertIn("PeriodTab.allCases", content)
        for title in ["今天", "周", "月", "全部"]:
            with self.subTest(title=title):
                self.assertIn(f'return "{title}"', content)
        self.assertIn('case .week:  return "gauge.with.dots.needle.33percent"', content)
        self.assertNotIn("Capsule().fill(Color.blue)", content)
        self.assertNotIn(".foregroundStyle(isSelected ? .white", content)
        self.assertNotIn(".background(.regularMaterial, in: Capsule())", content)
        self.assertNotIn("ZStack(alignment: .bottom)", content)

    def test_ios_sources_card_uses_source_level_usage_rows(self) -> None:
        root_view = (
            ROOT
            / "mobile"
            / "ios"
            / "Sources"
            / "AIUsageMobileCore"
            / "AIUsageMobileRootView.swift"
        )
        content = root_view.read_text(encoding="utf-8")
        card_start = content.index("struct PeriodSourcesCard")
        card_end = content.index("struct PeriodSourceRow", card_start)
        card_content = content[card_start:card_end]

        self.assertIn("sourceUsageRows(sources: sources, byMachine: byMachine)", card_content)
        self.assertIn("tokensBySource[contribution.sourceID", card_content)
        self.assertNotIn("SourcesDisplayState.visibleRows(byMachine)", card_content)

    def test_ios_source_row_keeps_user_usage_machine_and_update_time_separate(self) -> None:
        root_view = (
            ROOT
            / "mobile"
            / "ios"
            / "Sources"
            / "AIUsageMobileCore"
            / "AIUsageMobileRootView.swift"
        )
        content = root_view.read_text(encoding="utf-8")
        row_start = content.index("struct PeriodSourceRow")
        row_end = content.index("// MARK: - Model Usage Card", row_start)
        row_content = content[row_start:row_end]

        self.assertIn("private var displayUser", row_content)
        self.assertIn("private var machineName", row_content)
        self.assertIn("private var updateText", row_content)
        self.assertIn("Text(displayUser)", row_content)
        self.assertIn("Text(TokenFormat.compact(row.tokens))", row_content)
        self.assertIn("Text(machineName)", row_content)
        self.assertIn("Text(updateText)", row_content)
        self.assertGreaterEqual(row_content.count("HStack"), 2)
        self.assertIn(".truncationMode(.middle)", row_content)
        self.assertIn(".layoutPriority(1)", row_content)
        self.assertIn(".fixedSize(horizontal: true, vertical: false)", row_content)
        self.assertNotIn("parts.joined(separator:", row_content)

    @staticmethod
    def _png_size(path: pathlib.Path) -> tuple[int, int]:
        with path.open("rb") as handle:
            header = handle.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n":
            raise AssertionError(f"{path} is not a PNG")
        return struct.unpack(">II", header[16:24])

    @staticmethod
    def _png_alpha_extrema(path: pathlib.Path) -> tuple[int, int]:
        with path.open("rb") as handle:
            data = handle.read()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise AssertionError(f"{path} is not a PNG")
        pos = 8
        color_type = None
        bit_depth = None
        width = height = None
        compressed = bytearray()
        while pos < len(data):
            length = struct.unpack(">I", data[pos : pos + 4])[0]
            chunk_type = data[pos + 4 : pos + 8]
            chunk_data = data[pos + 8 : pos + 8 + length]
            pos += 12 + length
            if chunk_type == b"IHDR":
                width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk_data[:10])
            elif chunk_type == b"IDAT":
                compressed.extend(chunk_data)
            elif chunk_type == b"IEND":
                break
        if color_type not in (4, 6):
            return (255, 255)
        if bit_depth != 8 or width is None or height is None:
            raise AssertionError(f"{path} uses unsupported PNG alpha format")
        channels = 4 if color_type == 6 else 2
        stride = width * channels
        raw = zlib.decompress(bytes(compressed))
        previous = [0] * stride
        alphas: list[int] = []
        idx = 0
        for _ in range(height):
            filter_type = raw[idx]
            idx += 1
            row = list(raw[idx : idx + stride])
            idx += stride
            IOSXcodeIntegrationTests._unfilter_png_row(row, previous, filter_type, channels)
            alphas.extend(row[channels - 1 :: channels])
            previous = row
        return (min(alphas), max(alphas))

    @staticmethod
    def _unfilter_png_row(row: list[int], previous: list[int], filter_type: int, bpp: int) -> None:
        def paeth(a: int, b: int, c: int) -> int:
            p = a + b - c
            pa = abs(p - a)
            pb = abs(p - b)
            pc = abs(p - c)
            if pa <= pb and pa <= pc:
                return a
            if pb <= pc:
                return b
            return c

        for i, value in enumerate(row):
            left = row[i - bpp] if i >= bpp else 0
            up = previous[i]
            upper_left = previous[i - bpp] if i >= bpp else 0
            if filter_type == 1:
                row[i] = (value + left) & 0xFF
            elif filter_type == 2:
                row[i] = (value + up) & 0xFF
            elif filter_type == 3:
                row[i] = (value + ((left + up) // 2)) & 0xFF
            elif filter_type == 4:
                row[i] = (value + paeth(left, up, upper_left)) & 0xFF
            elif filter_type != 0:
                raise AssertionError(f"unsupported PNG filter {filter_type}")
