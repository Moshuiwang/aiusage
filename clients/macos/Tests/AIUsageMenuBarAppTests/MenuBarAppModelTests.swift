import AIUsageMenuBarCore
import Foundation
@testable import AIUsageMenuBarApp
import XCTest

@MainActor
final class MenuBarAppModelTests: XCTestCase {
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
            paths: RuntimePaths(root: URL(fileURLWithPath: "/tmp/ai-usage-menu-test")),
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

    func testAllFourPeriodsKeepIndependentFreshCaches() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let periods = ["today": 100, "week": 200, "month": 300, "all": 400]
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
            paths: RuntimePaths(root: URL(fileURLWithPath: "/tmp/ai-usage-menu-test")),
            config: testConfig(defaultPeriod: "today"),
            cachedSummaries: cached,
            cacheFreshnessInterval: 300,
            now: { now },
            loadSummary: loader.load
        )

        for period in ["today", "week", "month", "all"] {
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
            paths: RuntimePaths(root: URL(fileURLWithPath: "/tmp/ai-usage-menu-test")),
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
            paths: RuntimePaths(root: URL(fileURLWithPath: "/tmp/ai-usage-menu-test")),
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
            paths: RuntimePaths(root: URL(fileURLWithPath: "/tmp/ai-usage-menu-test")),
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
            paths: RuntimePaths(root: URL(fileURLWithPath: "/tmp/ai-usage-menu-test")),
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
            paths: RuntimePaths(root: URL(fileURLWithPath: "/tmp/ai-usage-menu-test")),
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
        XCTAssertEqual(model.summary.period.id, "all")
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
            paths: RuntimePaths(root: URL(fileURLWithPath: "/tmp/ai-usage-menu-test")),
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
            paths: RuntimePaths(root: URL(fileURLWithPath: "/tmp/ai-usage-menu-test")),
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

    func load(config: MobileSummaryClientConfig) async throws -> MobileSummary {
        defer {
            completedPeriods.insert(config.period)
        }
        configs[config.period] = config
        return try await withCheckedThrowingContinuation { continuation in
            continuations[config.period] = continuation
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
