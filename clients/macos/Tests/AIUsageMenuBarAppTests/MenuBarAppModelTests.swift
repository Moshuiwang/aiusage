import AIUsageMenuBarCore
import AppKit
import Foundation
@testable import AIUsageMenuBarApp
import SwiftUI
import XCTest

@MainActor
final class MenuBarAppModelTests: XCTestCase {
    func testHostedPopoverShowsContentOnFirstLayout() throws {
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(),
            cachedSummary: try summary(periodID: "today", totalTokens: 349_100_000)
        )
        let hosting = NSHostingController(rootView: MenuBarPopoverView(model: model))
        let popover = NSPopover()
        popover.contentViewController = hosting
        hosting.loadViewIfNeeded()
        hosting.view.frame.size.width = MenuBarPopoverLayout.width
        hosting.view.layoutSubtreeIfNeeded()
        popover.contentSize = MenuBarPopoverLayout.size(contentHeight: hosting.view.fittingSize.height)

        XCTAssertGreaterThan(popover.contentSize.height, 220, "first layout must include the period picker and summary, not just the header")
        let scrollViews = descendants(of: hosting.view).compactMap { $0 as? NSScrollView }
        XCTAssertEqual(scrollViews.count, 1, "the actual hosted popover must contain one scrollable content region")
        XCTAssertGreaterThan(scrollViews.first?.frame.height ?? 0, 120)
    }

    func testHostedPopoverKeepsOwnerFixtureContentVisibleAfterMeasurement() throws {
        let fixtureURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("AIUsageMenuBarCoreTests/Fixtures/navigation-models-owner.json")
        let summary = try JSONDecoder().decode(MobileSummary.self, from: Data(contentsOf: fixtureURL))
        XCTAssertGreaterThan(summary.sources.count, 0)
        XCTAssertGreaterThan(summary.breakdown.byModel.count, 0)
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(), cachedSummary: summary
        )
        let popover = NSPopover()
        var hosting: NSHostingController<MenuBarPopoverView>!
        hosting = NSHostingController(rootView: MenuBarPopoverView(model: model, onContentHeightChange: {
            hosting.view.layoutSubtreeIfNeeded()
            popover.contentSize = MenuBarPopoverLayout.size(contentHeight: hosting.view.fittingSize.height)
        }))
        popover.contentViewController = hosting
        hosting.loadViewIfNeeded()
        hosting.view.frame.size.width = MenuBarPopoverLayout.width
        hosting.view.layoutSubtreeIfNeeded()
        popover.contentSize = MenuBarPopoverLayout.size(contentHeight: hosting.view.fittingSize.height)
        RunLoop.main.run(until: Date().addingTimeInterval(0.1))
        hosting.view.layoutSubtreeIfNeeded()

        let scrollViews = descendants(of: hosting.view).compactMap { $0 as? NSScrollView }
        XCTAssertEqual(scrollViews.count, 1)
        XCTAssertGreaterThan(scrollViews.first?.frame.height ?? 0, 120)
        XCTAssertGreaterThan(popover.contentSize.height, 220)
        XCTAssertLessThanOrEqual(popover.contentSize.height, (NSScreen.main?.visibleFrame.height ?? 800) + 1)
    }

    func testShownPopoverKeepsContentViewport() throws {
        _ = NSApplication.shared
        let fixtureURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("AIUsageMenuBarCoreTests/Fixtures/navigation-models-owner.json")
        let summary = try JSONDecoder().decode(MobileSummary.self, from: Data(contentsOf: fixtureURL))
        XCTAssertGreaterThan(summary.sources.count, 0)
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(),
            cachedSummary: summary
        )
        let hosting = NSHostingController(rootView: MenuBarPopoverView(model: model))
        let popover = NSPopover()
        popover.contentViewController = hosting
        hosting.loadViewIfNeeded()
        hosting.view.frame.size.width = MenuBarPopoverLayout.width
        hosting.view.layoutSubtreeIfNeeded()
        popover.contentSize = MenuBarPopoverLayout.size(contentHeight: hosting.view.fittingSize.height)

        let anchorWindow = NSWindow(
            contentRect: NSRect(x: -10_000, y: -10_000, width: 20, height: 20),
            styleMask: .borderless, backing: .buffered, defer: false
        )
        anchorWindow.isReleasedWhenClosed = false
        let anchor = NSButton(frame: NSRect(x: 0, y: 0, width: 20, height: 20))
        anchorWindow.contentView?.addSubview(anchor)
        anchorWindow.orderFront(nil)
        defer { popover.close(); anchorWindow.close() }
        popover.show(relativeTo: anchor.bounds, of: anchor, preferredEdge: .minY)
        RunLoop.main.run(until: Date().addingTimeInterval(0.05))

        XCTAssertTrue(popover.isShown)
        XCTAssertNotNil(hosting.view.window)
        let scrollViews = descendants(of: hosting.view).compactMap { $0 as? NSScrollView }
        XCTAssertEqual(scrollViews.count, 1)
        let scroll = try XCTUnwrap(scrollViews.first)
        let document = try XCTUnwrap(scroll.documentView)
        XCTAssertGreaterThan(scroll.frame.height, 120)
        XCTAssertGreaterThan(document.frame.height, scroll.contentView.bounds.height + 100)
        let bottom = document.frame.height - scroll.contentView.bounds.height
        scroll.contentView.scroll(to: NSPoint(x: 0, y: bottom))
        scroll.reflectScrolledClipView(scroll.contentView)
        XCTAssertGreaterThanOrEqual(scroll.contentView.bounds.maxY, document.frame.maxY - 1)
    }

    func testHostedPopoverKeepsViewportThroughLoadAndHistorySwitch() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(),
            cachedSummaries: ["week": CachedMenuSummary(
                summary: try summary(periodID: "week", totalTokens: 700), fetchedAt: now
            )], now: { now }, loadSummary: loader.load
        )
        let popover = NSPopover()
        let hosting = NSHostingController(rootView: MenuBarPopoverView(model: model))
        popover.contentViewController = hosting
        hosting.loadViewIfNeeded()
        hosting.view.frame.size.width = MenuBarPopoverLayout.width

        func assertVisibleViewport(_ phase: String) {
            hosting.view.layoutSubtreeIfNeeded()
            popover.contentSize = MenuBarPopoverLayout.size(contentHeight: hosting.view.fittingSize.height)
            let scroll = descendants(of: hosting.view).compactMap { $0 as? NSScrollView }
            XCTAssertEqual(scroll.count, 1, phase)
            XCTAssertGreaterThan(scroll.first?.frame.height ?? 0, 120, phase)
            XCTAssertGreaterThan(popover.contentSize.height, 220, phase)
        }

        assertVisibleViewport("first open without cached data")
        model.refresh()
        try await loader.waitForRequestCount(1)
        assertVisibleViewport("loading")
        await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 349_100_000))
        await waitUntil { model.hasLoadedUsableSummary && !model.isLoading }
        assertVisibleViewport("loaded summary")
        model.refresh(periodID: "week")
        XCTAssertEqual(model.summary.period.id, "week")
        assertVisibleViewport("weekly history")
    }

    private func descendants(of view: NSView) -> [NSView] {
        [view] + view.subviews.flatMap(descendants)
    }

    func testPopoverLayoutUsesMeasuredContentHeight() {
        XCTAssertEqual(MenuBarPopoverLayout.size(contentHeight: 642).height, 642)
    }

    func testStatusItemPresentationKeepsMenuBarEntryNumeric() throws {
        let state = MenuBarViewModel.build(
            from: try summary(periodID: "today", totalTokens: 366_442_154),
            selectedPeriodID: "today"
        )

        XCTAssertEqual(MenuBarStatusItemPresentation.title(for: state), "366.4M")
        XCTAssertEqual(MenuBarStatusItemPresentation.tooltip(for: state), "AI Usage · 今天 366.4M")
    }

    func testStatusItemPresentationUsesNewAutosaveNameForVisiblePlacement() {
        XCTAssertEqual(
            MenuBarStatusItemPresentation.autosaveName,
            "com.chunbai.aiusage.menubar.status.numeric.v3"
        )
    }

    func testStatusItemPresentationAllowsUserRecoveryFromMenuBarRemoval() {
        XCTAssertEqual(
            MenuBarStatusItemPresentation.behavior,
            .removalAllowed
        )
    }

    func testSwitchToFreshCachedPeriodDoesNotRequestNetwork() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            cachedSummaries: [
                "week": CachedMenuSummary(
                    summary: try summary(periodID: "week", totalTokens: 700),
                    fetchedAt: now.addingTimeInterval(-60)
                )
            ],
            cacheFreshnessInterval: 300,
            now: { now },
            loadSummary: loader.load
        )

        model.refresh(periodID: "week")
        await yieldToMainActor()

        XCTAssertEqual(model.selectedPeriodID, "week")
        XCTAssertEqual(model.summary.period.id, "week")
        XCTAssertEqual(model.summary.period.totalTokens, 700)
        XCTAssertFalse(model.isLoading)
        let requestCount = await loader.requestCount()
        XCTAssertEqual(requestCount, 0)
    }

    func testThreeVisiblePeriodsKeepIndependentFreshCaches() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let periods = ["today": 100, "week": 200, "month": 300]
        let cached = try Dictionary(uniqueKeysWithValues: periods.map { period, total in
            (
                period,
                CachedMenuSummary(
                    summary: try summary(periodID: period, totalTokens: total),
                    fetchedAt: now.addingTimeInterval(-60)
                )
            )
        })
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            cachedSummaries: cached,
            cacheFreshnessInterval: 300,
            now: { now },
            loadSummary: loader.load
        )

        for period in ["today", "week", "month"] {
            model.refresh(periodID: period)
            await yieldToMainActor()
            XCTAssertEqual(model.selectedPeriodID, period)
            XCTAssertEqual(model.summary.period.id, period)
            XCTAssertEqual(model.summary.period.totalTokens, periods[period])
            XCTAssertNil(model.errorMessage)
        }

        let requestCount = await loader.requestCount()
        XCTAssertEqual(requestCount, 0)
    }

    func testSwitchToExpiredCachedPeriodShowsCacheThenRefreshesInBackground() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            cachedSummaries: [
                "week": CachedMenuSummary(
                    summary: try summary(periodID: "week", totalTokens: 700),
                    fetchedAt: now.addingTimeInterval(-600)
                )
            ],
            cacheFreshnessInterval: 300,
            now: { now },
            loadSummary: loader.load
        )

        model.refresh(periodID: "week")
        try await loader.waitForRequestCount(1)

        XCTAssertEqual(model.summary.period.id, "week")
        XCTAssertEqual(model.summary.period.totalTokens, 700)
        XCTAssertTrue(model.isLoading)

        await loader.complete(period: "week", summary: try summary(periodID: "week", totalTokens: 900))
        await waitUntil {
            model.summary.period.totalTokens == 900 && model.isLoading == false
        }
    }

    func testExpiredCachedPeriodSurvivesBackgroundRefreshFailure() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            cachedSummaries: [
                "month": CachedMenuSummary(
                    summary: try summary(periodID: "month", totalTokens: 1200),
                    fetchedAt: now.addingTimeInterval(-600)
                )
            ],
            cacheFreshnessInterval: 300,
            now: { now },
            loadSummary: loader.load
        )

        model.refresh(periodID: "month")
        try await loader.waitForRequestCount(1)
        await loader.fail(period: "month")
        await waitUntil {
            model.isLoading == false
        }

        XCTAssertEqual(model.summary.period.id, "month")
        XCTAssertEqual(model.summary.period.totalTokens, 1200)
        XCTAssertTrue(model.errorMessage?.hasPrefix("刷新失败，正在显示缓存：") == true)
    }

    func testSuccessfulQuotaRemainsVisibleWhenFreshSummaryReportsQuotaFailure() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let lastSuccessfulWindow = MobileLimitWindow(
            sourceID: "claude-main",
            provider: "claude",
            window: "session",
            usedPercent: 4,
            remainingPercent: 96,
            resetAt: "2026-06-25T15:00:00+08:00",
            windowDurationMinutes: 300,
            observedAt: "2026-06-25T11:00:00+08:00",
            sourceType: "official_cli",
            confidence: "observed",
            status: "ok",
            official: true
        )
        let cached = try summary(
            periodID: "today",
            totalTokens: 100,
            providerSlots: [
                MobileProviderSlot(
                    provider: "claude",
                    usage: MobileProviderUsage(
                        status: "available", totalTokens: 100, inputTokens: 20,
                        outputTokens: 10, cacheTokens: 70
                    ),
                    quota: MobileProviderQuota(
                        status: "available", reason: nil,
                        lastVerifiedAt: lastSuccessfulWindow.observedAt,
                        sourceID: lastSuccessfulWindow.sourceID,
                        sourceType: lastSuccessfulWindow.sourceType,
                        windows: [lastSuccessfulWindow]
                    )
                )
            ]
        )
        let refreshed = try summary(
            periodID: "today",
            totalTokens: 200,
            providerSlots: [
                MobileProviderSlot(
                    provider: "claude",
                    usage: MobileProviderUsage(
                        status: "available", totalTokens: 200, inputTokens: 40,
                        outputTokens: 20, cacheTokens: 140
                    ),
                    quota: MobileProviderQuota(
                        status: "missing", reason: "unavailable",
                        lastVerifiedAt: lastSuccessfulWindow.observedAt,
                        sourceID: lastSuccessfulWindow.sourceID,
                        sourceType: lastSuccessfulWindow.sourceType,
                        windows: []
                    )
                )
            ]
        )
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            cachedSummaries: [
                "today": CachedMenuSummary(summary: cached, fetchedAt: now.addingTimeInterval(-600))
            ],
            cacheFreshnessInterval: 300,
            now: { now },
            loadSummary: loader.load
        )

        model.refresh(force: true)
        try await loader.waitForRequestCount(1)
        await loader.complete(period: "today", summary: refreshed)
        await waitUntil {
            model.isLoading == false
        }

        let claude = try XCTUnwrap(model.summary.providerSlots.first { $0.provider == "claude" })
        XCTAssertEqual(model.summary.period.totalTokens, 200)
        XCTAssertEqual(claude.usage.totalTokens, 200)
        XCTAssertEqual(claude.quota.status, "missing")
        XCTAssertEqual(claude.quota.windows, [lastSuccessfulWindow])
    }

    func testPopoverQuitActionTerminatesApplication() throws {
        try XCTSkipIf(
            ProcessInfo.processInfo.environment["CI"] == "true",
            "requires a macOS WindowServer session"
        )
        var didQuit = false
        let controller = StatusBarController(
            paths: try temporaryRuntimePaths(),
            quitApplication: {
                didQuit = true
            }
        )

        controller.quitFromPopover()

        XCTAssertTrue(didQuit)
    }

    func testIgnoresStaleRefreshAfterPeriodSwitch() async throws {
        let loader = ControlledSummaryLoader()
        let config = MenuBarRuntimeConfig(
            serverURL: "https://aiusage.chunbai.com",
            token: "test-token",
            dashboardURL: nil,
            defaultPeriod: "all"
        )
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: config,
            cachedSummary: MobileSummary.empty(periodID: "all"),
            loadSummary: loader.load
        )

        model.refresh(periodID: "today")
        model.refresh(periodID: "week")
        try await loader.waitForRequestCount(2)

        await loader.complete(period: "today", summary: MobileSummary.empty(periodID: "today"))
        try await loader.waitForCompleted("today")
        await yieldToMainActor()
        XCTAssertEqual(model.summary.period.id, "week")
        XCTAssertTrue(model.isLoading)

        await loader.complete(period: "week", summary: MobileSummary.empty(periodID: "week"))
        await waitUntil {
            model.summary.period.id == "week" && model.isLoading == false
        }
    }

    func testIgnoresStaleFailureAfterNewerRefreshSucceeds() async throws {
        let loader = ControlledSummaryLoader()
        let config = MenuBarRuntimeConfig(
            serverURL: "https://aiusage.chunbai.com",
            token: "test-token",
            dashboardURL: nil,
            defaultPeriod: "all"
        )
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: config,
            cachedSummary: MobileSummary.empty(periodID: "all"),
            loadSummary: loader.load
        )

        model.refresh(periodID: "today")
        model.refresh(periodID: "week")
        try await loader.waitForRequestCount(2)

        await loader.complete(period: "week", summary: MobileSummary.empty(periodID: "week"))
        await waitUntil {
            model.summary.period.id == "week" && model.isLoading == false
        }

        await loader.fail(period: "today")
        try await loader.waitForCompleted("today")
        await yieldToMainActor()
        XCTAssertNil(model.errorMessage)
        XCTAssertEqual(model.summary.period.id, "week")
    }

    func testShowsCachedDataWarningWhenRefreshFails() async throws {
        let loader = ControlledSummaryLoader()
        let config = MenuBarRuntimeConfig(
            serverURL: "https://aiusage.chunbai.com",
            token: "test-token",
            dashboardURL: nil,
            defaultPeriod: "today"
        )
        let cached = MobileSummary.empty(periodID: "today")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: config,
            cachedSummary: cached,
            loadSummary: loader.load
        )

        model.refresh()
        try await loader.waitForRequestCount(1)
        await loader.fail(period: "today")
        await waitUntil {
            model.isLoading == false
        }

        XCTAssertTrue(model.errorMessage?.hasPrefix("刷新失败，正在显示缓存：") == true)
        XCTAssertTrue(model.errorMessage?.contains("-1001") == true)
        XCTAssertEqual(model.summary, cached)
    }

    func testRefreshUsesUpdatedRuntimeConfigWithoutRestart() async throws {
        let loader = ControlledSummaryLoader()
        let paths = try temporaryRuntimePaths()
        try FileManager.default.createDirectory(at: paths.root, withIntermediateDirectories: true)
        let updatedConfig = """
        {
          "dashboard_url": "https://aiusage.chunbai.com/dashboard",
          "default_period": "today",
          "refresh_interval_seconds": 600,
          "server_url": "https://aiusage.chunbai.com",
          "token": "new-token"
        }
        """
        try updatedConfig.write(to: paths.configURL, atomically: true, encoding: .utf8)
        let staleConfig = MenuBarRuntimeConfig(
            serverURL: "https://vpn2.chunbai.com:8443",
            token: "old-token",
            dashboardURL: nil,
            defaultPeriod: "today"
        )
        let model = MenuBarAppModel(
            paths: paths,
            config: staleConfig,
            cachedSummary: MobileSummary.empty(periodID: "today"),
            loadSummary: loader.load
        )

        model.refresh()
        try await loader.waitForRequestCount(1)
        let requestConfig = try await loader.config(for: "today")

        XCTAssertEqual(requestConfig.baseURL.absoluteString, "https://aiusage.chunbai.com")
        XCTAssertEqual(requestConfig.bearerToken, "new-token")
        XCTAssertEqual(model.dashboardURL?.absoluteString, "https://aiusage.chunbai.com/dashboard")
    }

    func testSwitchingToFreshCacheInvalidatesAnOlderFailure() async throws {
        let loader = ControlledSummaryLoader()
        let now = Date()
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(),
            cachedSummaries: ["week": CachedMenuSummary(summary: try summary(periodID: "week", totalTokens: 700), fetchedAt: now)],
            now: { now }, loadSummary: loader.load
        )
        model.refresh(periodID: "today", force: true)
        try await loader.waitForRequestCount(1)
        model.refresh(periodID: "week")
        await loader.fail(period: "today")
        try await loader.waitForCompleted("today")
        await yieldToMainActor()
        XCTAssertEqual(model.summary.period.totalTokens, 700)
        XCTAssertNil(model.errorMessage, "A request for another selection must not show an error here")
        XCTAssertFalse(model.isLoading)
    }

    func testUncachedSelectionNeverShowsAnotherPeriodsNumbers() async throws {
        let loader = ControlledSummaryLoader()
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(),
            cachedSummary: try summary(periodID: "today", totalTokens: 123), loadSummary: loader.load
        )
        model.refresh(periodID: "month")
        try await loader.waitForRequestCount(1)
        XCTAssertEqual(model.summary.period.id, "month")
        XCTAssertEqual(model.summary.period.totalTokens, 0)
        await loader.fail(period: "month")
        try await loader.waitForCompleted("month")
        await yieldToMainActor()
        XCTAssertTrue(model.errorMessage?.hasPrefix("读取失败") == true)
    }

    func testHistoryKeepsSeparateCacheAndTodaysMenuBarValue() async throws {
        let loader = ControlledSummaryLoader()
        let paths = try temporaryRuntimePaths()
        let model = MenuBarAppModel(paths: paths, config: testConfig(), loadSummary: loader.load)
        model.refresh()
        try await loader.waitForRequestCount(1)
        await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 100))
        await waitUntil { !model.isLoading }
        model.movePeriod(-1)
        try await loader.waitForRequestCount(1)
        let request = try await loader.config(for: "today:-1")
        XCTAssertEqual(request.offset, -1)
        XCTAssertEqual(model.selectedOffset, -1)
        XCTAssertFalse(model.hasLoadedUsableSummary)
        await loader.complete(period: "today:-1", summary: try summary(periodID: "today", totalTokens: 900))
        await waitUntil { !model.isLoading }
        XCTAssertEqual(model.summary.period.totalTokens, 900)
        XCTAssertEqual(model.statusState.statusTitle, "100")
        XCTAssertEqual(SummaryCache.load(from: paths.cacheURL(forPeriod: "today", offset: 0))?.period.totalTokens, 100)
        XCTAssertEqual(SummaryCache.load(from: paths.cacheURL(forPeriod: "today", offset: -1))?.period.totalTokens, 900)
        model.movePeriod(1)
        XCTAssertEqual(model.summary.period.totalTokens, 100)
        XCTAssertEqual(model.selectedOffset, 0)
        XCTAssertFalse(model.isLoading)
        let count = await loader.requestCount()
        XCTAssertEqual(count, 2)
    }

    func testStaleSamePeriodHistoryResponseCannotReplaceNewerSelection() async throws {
        let loader = ControlledSummaryLoader()
        let model = MenuBarAppModel(paths: try temporaryRuntimePaths(), config: testConfig(), loadSummary: loader.load)
        model.refresh(periodID: "month", offset: -1)
        model.movePeriod(-1)
        try await loader.waitForRequestCount(2)
        await loader.complete(period: "month:-2", summary: try summary(periodID: "month", totalTokens: 200))
        await waitUntil { !model.isLoading }
        await loader.complete(period: "month:-1", summary: try summary(periodID: "month", totalTokens: 900))
        try await loader.waitForCompleted("month:-1")
        await yieldToMainActor()
        XCTAssertEqual(model.selectedOffset, -2)
        XCTAssertEqual(model.summary.period.totalTokens, 200)
        model.refresh(periodID: "week")
        XCTAssertEqual(model.selectedOffset, 0)
        try await loader.waitForRequestCount(1)
        await loader.complete(period: "week", summary: try summary(periodID: "week", totalTokens: 100))
        await waitUntil { !model.isLoading }
    }

    func testYesterdayRelativeCacheExpiresAtServiceMidnight() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-26T00:01:00+08:00")
        let cachedAt = try date("2026-06-25T23:59:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(),
            cachedSummaries: ["today:-1": CachedMenuSummary(summary: try summary(periodID: "today", totalTokens: 999), fetchedAt: cachedAt)],
            now: { now }, loadSummary: loader.load
        )
        model.movePeriod(-1)
        try await loader.waitForRequestCount(1)
        XCTAssertFalse(model.hasLoadedUsableSummary)
        XCTAssertEqual(model.summary.period.totalTokens, 0)
        await loader.complete(period: "today:-1", summary: try summary(periodID: "today", totalTokens: 100))
        await waitUntil { !model.isLoading }
        XCTAssertEqual(model.summary.period.totalTokens, 100)
    }

    func testStartupDoesNotPresentPreviousDaysCacheAsToday() throws {
        let now = try date("2026-06-26T00:01:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(),
            cachedSummaries: ["today": CachedMenuSummary(
                summary: try summary(periodID: "today", totalTokens: 999),
                fetchedAt: try date("2026-06-25T23:59:00+08:00"))],
            now: { now }
        )
        XCTAssertNil(model.todaySummary)
        XCTAssertFalse(model.hasLoadedUsableSummary)
    }

    func testFreshCacheFastPathInvalidatesSameSelectionRequest() async throws {
        for shouldFail in [false, true] {
            let loader = ControlledSummaryLoader()
            let now = Date()
            let model = MenuBarAppModel(
                paths: try temporaryRuntimePaths(), config: testConfig(),
                cachedSummaries: ["today": CachedMenuSummary(summary: try summary(periodID: "today", totalTokens: 100), fetchedAt: now)],
                now: { now }, loadSummary: loader.load
            )
            model.refresh(force: true)
            try await loader.waitForRequestCount(1)
            model.refresh()
            XCTAssertFalse(model.isLoading)
            if shouldFail { await loader.fail(period: "today") }
            else { await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 999)) }
            try await loader.waitForCompleted("today")
            await yieldToMainActor()
            XCTAssertEqual(model.summary.period.totalTokens, 100)
            XCTAssertEqual(model.todaySummary?.period.totalTokens, 100)
            XCTAssertNil(model.errorMessage)
        }
    }

    func testRequestCrossingMidnightReloadsBeforeShowingYesterdayAsToday() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T23:59:59+08:00")
        let model = MenuBarAppModel(paths: try temporaryRuntimePaths(), config: testConfig(), now: { clock }, loadSummary: loader.load)
        model.refresh()
        try await loader.waitForRequestCount(1)
        clock = try date("2026-06-26T00:00:01+08:00")
        await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 999))
        try await loader.waitForTotalRequestCount(2)
        XCTAssertNil(model.todaySummary)
        XCTAssertFalse(model.hasLoadedUsableSummary)
        XCTAssertTrue(model.isLoading)
        await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 100))
        await waitUntil { !model.isLoading }
        XCTAssertEqual(model.todaySummary?.period.totalTokens, 100)
    }

    func testBackgroundTodayReadCrossingMidnightReloadsAndKeepsHistorySelected() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T23:59:59+08:00")
        let model = MenuBarAppModel(paths: try temporaryRuntimePaths(), config: testConfig(defaultPeriod: "month"), now: { clock }, loadSummary: loader.load)
        model.refreshToday()
        try await loader.waitForRequestCount(1)
        clock = try date("2026-06-26T00:00:01+08:00")
        await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 999))
        try await loader.waitForTotalRequestCount(2)
        XCTAssertNil(model.todaySummary)
        XCTAssertEqual(model.selectedPeriodID, "month")
        await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 100))
        await waitUntil { model.todaySummary?.period.totalTokens == 100 }
        XCTAssertEqual(model.selectedPeriodID, "month")
    }

    func testFailedRefreshCrossingMidnightClearsExpiredSelectionAndTodayValue() async throws {
        for selected in [MenuPeriodSelection(periodID: "today"), MenuPeriodSelection(periodID: "today", offset: -1), MenuPeriodSelection(periodID: "week"), MenuPeriodSelection(periodID: "month", offset: -1)] {
            let loader = ControlledSummaryLoader()
            var clock = try date("2026-06-25T23:59:59+08:00")
            var cached = ["today": CachedMenuSummary(summary: try summary(periodID: "today", totalTokens: 999), fetchedAt: clock)]
            cached[selected.cacheKey] = CachedMenuSummary(summary: try summary(periodID: selected.periodID, totalTokens: 900), fetchedAt: clock)
            let model = MenuBarAppModel(paths: try temporaryRuntimePaths(), config: testConfig(), cachedSummaries: cached, now: { clock }, loadSummary: loader.load)
            model.refresh(periodID: selected.periodID, offset: selected.offset, force: true)
            try await loader.waitForRequestCount(1)
            XCTAssertTrue(model.hasLoadedUsableSummary)
            clock = clock.addingTimeInterval(2)
            await loader.fail(period: selected.cacheKey)
            await waitUntil { !model.isLoading }
            XCTAssertEqual(model.selection, selected)
            XCTAssertNil(model.summary.period.date)
            XCTAssertEqual(model.summary.period.totalTokens, 0)
            XCTAssertFalse(model.hasLoadedUsableSummary)
            XCTAssertNil(model.todaySummary)
            XCTAssertTrue(model.errorMessage?.hasPrefix("读取失败") == true)
        }
    }

    func testFailedBackgroundTodayRefreshCrossingMidnightClearsOldValues() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T23:59:59+08:00")
        let model = MenuBarAppModel(paths: try temporaryRuntimePaths(), config: testConfig(defaultPeriod: "month"), cachedSummaries: [
            "today": CachedMenuSummary(summary: try summary(periodID: "today", totalTokens: 999), fetchedAt: clock),
            "month": CachedMenuSummary(summary: try summary(periodID: "month", totalTokens: 900), fetchedAt: clock)
        ], now: { clock }, loadSummary: loader.load)
        model.refreshToday()
        try await loader.waitForRequestCount(1)
        clock = clock.addingTimeInterval(2)
        await loader.fail(period: "today")
        try await loader.waitForCompleted("today")
        await yieldToMainActor()
        XCTAssertEqual(model.selectedPeriodID, "month")
        XCTAssertEqual(model.selectedOffset, 0)
        XCTAssertNil(model.todaySummary)
        XCTAssertFalse(model.hasLoadedUsableSummary)
        XCTAssertNil(model.summary.period.date)
    }

    func testLateBackgroundFailureDoesNotClearNewDayHistoryResult() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T23:59:59+08:00")
        let model = MenuBarAppModel(paths: try temporaryRuntimePaths(), config: testConfig(defaultPeriod: "month"), cachedSummaries: [
            "today": CachedMenuSummary(summary: try summary(periodID: "today", totalTokens: 999), fetchedAt: clock)
        ], now: { clock }, loadSummary: loader.load)
        model.refreshToday()
        try await loader.waitForRequestCount(1)
        clock = clock.addingTimeInterval(2)
        model.refresh(periodID: "week", offset: -1, force: true)
        try await loader.waitForRequestCount(2)
        await loader.complete(period: "week:-1", summary: try summary(periodID: "week", totalTokens: 700))
        await waitUntil { !model.isLoading }
        await loader.fail(period: "today")
        try await loader.waitForCompleted("today")
        await yieldToMainActor()
        XCTAssertEqual(model.selection, MenuPeriodSelection(periodID: "week", offset: -1))
        XCTAssertNil(model.todaySummary)
        XCTAssertTrue(model.hasLoadedUsableSummary)
        XCTAssertEqual(model.summary.period.totalTokens, 700)
    }

    func testInvalidBackgroundPeriodCrossingMidnightClearsToday() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T23:59:59+08:00")
        let model = MenuBarAppModel(paths: try temporaryRuntimePaths(), config: testConfig(defaultPeriod: "month"), cachedSummaries: [
            "today": CachedMenuSummary(summary: try summary(periodID: "today", totalTokens: 999), fetchedAt: clock)
        ], now: { clock }, loadSummary: loader.load)
        model.refreshToday()
        try await loader.waitForRequestCount(1)
        clock = clock.addingTimeInterval(2)
        await loader.complete(period: "today", summary: try summary(periodID: "week", totalTokens: 900))
        try await loader.waitForCompleted("today")
        await yieldToMainActor()
        XCTAssertNil(model.todaySummary)
        XCTAssertEqual(model.selectedPeriodID, "month")
    }

    private func waitUntil(
        timeoutIterations: Int = 50,
        _ predicate: @MainActor () -> Bool,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        for _ in 0..<timeoutIterations {
            if predicate() {
                return
            }
            try? await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("Timed out waiting for expected model state", file: file, line: line)
    }

    private func yieldToMainActor() async {
        for _ in 0..<5 {
            await Task.yield()
        }
    }

    private func temporaryRuntimePaths() throws -> RuntimePaths {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("ai-usage-menu-\(UUID().uuidString)", isDirectory: true)
        addTeardownBlock {
            try? FileManager.default.removeItem(at: root)
        }
        return RuntimePaths(root: root)
    }

    private func testConfig(defaultPeriod: String = "today") -> MenuBarRuntimeConfig {
        MenuBarRuntimeConfig(
            serverURL: "https://aiusage.chunbai.com",
            token: "test-token",
            dashboardURL: nil,
            defaultPeriod: defaultPeriod
        )
    }

    private func summary(
        periodID: String,
        totalTokens: Int,
        providerSlots: [MobileProviderSlot] = []
    ) throws -> MobileSummary {
        let json = """
        {
          "schema_version": 1,
          "client": "macos",
          "generated_at": "2026-06-25T12:00:00+08:00",
          "timezone": "Asia/Shanghai",
          "period": {
            "id": "\(periodID)",
            "date": "2026-06-25",
            "start_date": "2026-06-25",
            "end_date": "2026-06-25",
            "total_tokens": \(totalTokens),
            "input_tokens": \(totalTokens),
            "output_tokens": 0,
            "cache_tokens": 0,
            "cache_ratio": 0,
            "machine": null,
            "account": null
          },
          "trend": {
            "period": "\(periodID)",
            "granularity": "\(periodID == "today" ? "hour" : "day")",
            "start_date": "2026-06-25",
            "end_date": "2026-06-25",
            "points": []
          },
          "sources": [],
          "breakdown": {
            "by_machine": [],
            "by_os_user": [],
            "by_agent": [],
            "by_model": [],
            "by_date": []
          },
          "limits": {
            "observed_count": 0,
            "total_count": 0,
            "windows": []
          }
        }
        """
        let base = try JSONDecoder().decode(MobileSummary.self, from: Data(json.utf8))
        return MobileSummary(
            schemaVersion: base.schemaVersion,
            client: base.client,
            generatedAt: base.generatedAt,
            timezone: base.timezone,
            period: base.period,
            trend: base.trend,
            sources: base.sources,
            breakdown: base.breakdown,
            limits: base.limits,
            providerSlots: providerSlots,
            providerUsageCoverage: base.providerUsageCoverage
        )
    }

    private func date(_ iso: String) throws -> Date {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let value = formatter.date(from: iso) {
            return value
        }
        formatter.formatOptions = [.withInternetDateTime]
        return try XCTUnwrap(formatter.date(from: iso))
    }
}

private actor ControlledSummaryLoader {
    private var continuations: [String: CheckedContinuation<MobileSummary, Error>] = [:]
    private var configs: [String: MobileSummaryClientConfig] = [:]
    private var completedPeriods: Set<String> = []
    private var totalRequests = 0

    func load(config: MobileSummaryClientConfig) async throws -> MobileSummary {
        totalRequests += 1
        let key = config.offset == 0 ? config.period : "\(config.period):\(config.offset)"
        defer {
            completedPeriods.insert(key)
        }
        configs[key] = config
        return try await withCheckedThrowingContinuation { continuation in
            continuations[key] = continuation
        }
    }

    func complete(period: String, summary: MobileSummary) {
        continuations.removeValue(forKey: period)?.resume(returning: summary)
    }

    func fail(period: String) {
        continuations.removeValue(forKey: period)?.resume(throwing: URLError(.timedOut))
    }

    func waitForRequestCount(_ count: Int) async throws {
        for _ in 0..<50 {
            if continuations.count >= count {
                return
            }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("Timed out waiting for \(count) requests")
    }

    func waitForTotalRequestCount(_ count: Int) async throws {
        for _ in 0..<50 {
            if totalRequests >= count { return }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("Timed out waiting for \(count) total requests")
    }

    func waitForCompleted(_ period: String) async throws {
        for _ in 0..<50 {
            if completedPeriods.contains(period) {
                return
            }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("Timed out waiting for \(period) completion")
    }

    func requestCount() -> Int {
        configs.count
    }

    func config(for period: String) throws -> MobileSummaryClientConfig {
        guard let config = configs[period] else {
            throw XCTSkip("No request config recorded for \(period)")
        }
        return config
    }
}
