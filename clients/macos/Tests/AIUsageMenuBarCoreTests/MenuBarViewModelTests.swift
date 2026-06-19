import XCTest
@testable import AIUsageMenuBarCore

final class MenuBarViewModelTests: XCTestCase {
    func testBuildsCompactStatusAndPopoverSections() throws {
        let summary = try loadFixture()

        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "week")

        XCTAssertEqual(state.statusTitle, "5.0K")
        XCTAssertEqual(state.periodLabel, "本周")
        XCTAssertEqual(state.heroTotalText, "5.0K")
        XCTAssertEqual(state.tokenBreakdownText, "输入 2.8K · 输出 1.4K · Cache 800")
        XCTAssertEqual(state.healthText, "2/2 正常")
        XCTAssertEqual(state.primaryLimitText, "Codex session · 60% 可用")
        XCTAssertTrue(state.lastUpdatedText.hasSuffix("前"), "Expected relative time, got: \(state.lastUpdatedText)")
        XCTAssertEqual(state.sources.map(\.title), ["wang", "wang"])
        XCTAssertEqual(state.sources.first?.subtitle, "linux-dev · linux · 10:40 更新")
        XCTAssertEqual(state.limitRows.first?.title, "Codex session")
        XCTAssertEqual(state.limitRows.first?.subtitle, "60% 可用 · 40% 已用 · observed")
        XCTAssertEqual(state.limitRows.first?.value, "15:40 重置")
        XCTAssertEqual(state.breakdownSections.map(\.title), ["机器", "账户", "Agent", "模型", "日期"])
        XCTAssertEqual(state.breakdownSections.first?.rows.map(\.title), ["linux-dev", "macbook-pro"])
        XCTAssertEqual(state.breakdownSections.first?.rows.first?.subtitle, "1 个来源")
        XCTAssertEqual(state.trendBars.map(\.label), ["06-01", "06-02"])
        XCTAssertEqual(state.trendBars.last?.ratio, 1.0)
    }

    func testTrendAxisUsesSparseFullRangeLabelsLikeMobileApp() throws {
        let summary = try loadFixture()
        let hourlyTrend = MobileTrend(
            period: "today",
            granularity: "hour",
            startDate: "2026-06-02",
            endDate: "2026-06-02",
            points: (0..<24).map { hour in
                MobileTrendPoint(
                    bucket: String(format: "2026-06-02T%02d:00:00+08:00", hour),
                    label: String(format: "2026-06-02T%02d:00:00+08:00", hour),
                    tokens: hour + 1,
                    inputTokens: 0,
                    outputTokens: 0,
                    cacheTokens: 0,
                    cacheRatio: 0
                )
            }
        )
        let today = MobileSummary(
            schemaVersion: summary.schemaVersion,
            client: summary.client,
            generatedAt: summary.generatedAt,
            timezone: summary.timezone,
            period: summary.period,
            trend: hourlyTrend,
            sources: summary.sources,
            breakdown: summary.breakdown,
            limits: summary.limits
        )

        let state = MenuBarViewModel.build(from: today, selectedPeriodID: "today")

        XCTAssertEqual(state.trendBars.count, 24)
        XCTAssertEqual(state.trendBars[0].label, "00:00")
        XCTAssertEqual(state.trendBars[12].label, "12:00")
        XCTAssertEqual(state.trendBars[23].label, "23:00")
        XCTAssertTrue(state.trendBars[1].label.isEmpty)
        XCTAssertEqual(state.trendBars[1].tooltipTitle, "01:00")

        let weeklyTrend = MobileTrend(
            period: "week",
            granularity: "day",
            startDate: "2026-05-28",
            endDate: "2026-06-03",
            points: ["2026-05-28", "2026-05-29", "2026-05-30", "2026-05-31", "2026-06-01", "2026-06-02", "2026-06-03"].enumerated().map { index, bucket in
                MobileTrendPoint(
                    bucket: bucket,
                    label: bucket,
                    tokens: index + 1,
                    inputTokens: 0,
                    outputTokens: 0,
                    cacheTokens: 0,
                    cacheRatio: 0
                )
            }
        )
        let week = MobileSummary(
            schemaVersion: summary.schemaVersion,
            client: summary.client,
            generatedAt: summary.generatedAt,
            timezone: summary.timezone,
            period: summary.period,
            trend: weeklyTrend,
            sources: summary.sources,
            breakdown: summary.breakdown,
            limits: summary.limits
        )
        let weekState = MenuBarViewModel.build(from: week, selectedPeriodID: "week")
        XCTAssertEqual(weekState.trendBars.map(\.label), ["05-28", "", "", "05-31", "", "", "06-03"])
    }

    func testQuotaRingsUseLatestObservedAvailabilityPerProviderWindow() throws {
        let summary = try loadFixture()
        let duplicateLimits = MobileLimits(
            observedCount: 4,
            totalCount: 4,
            windows: [
                MobileLimitWindow(
                    sourceID: "claude-main",
                    provider: "claude",
                    window: "session",
                    usedPercent: 92,
                    remainingPercent: 8,
                    resetAt: "2026-05-24T14:40:00+00:00",
                    windowDurationMinutes: 300,
                    observedAt: "2026-06-18T10:00:00+08:00",
                    sourceType: "active_limits_cache",
                    confidence: "observed",
                    status: "ok",
                    official: true
                ),
                MobileLimitWindow(
                    sourceID: "claude-main",
                    provider: "claude",
                    window: "session",
                    usedPercent: 96,
                    remainingPercent: 4,
                    resetAt: "2026-06-19T18:09:00+08:00",
                    windowDurationMinutes: 300,
                    observedAt: "2026-06-19T20:26:45+08:00",
                    sourceType: "official_cli_limit_message",
                    confidence: "observed",
                    status: "ok",
                    official: true
                ),
                MobileLimitWindow(
                    sourceID: "claude-main",
                    provider: "claude",
                    window: "week",
                    usedPercent: 47,
                    remainingPercent: 53,
                    resetAt: "2026-06-21T01:59:00+08:00",
                    windowDurationMinutes: 10080,
                    observedAt: "2026-06-19T20:26:45+08:00",
                    sourceType: "official_cli_limit_message",
                    confidence: "observed",
                    status: "ok",
                    official: true
                ),
                MobileLimitWindow(
                    sourceID: "codex-main",
                    provider: "codex",
                    window: "session",
                    usedPercent: 59,
                    remainingPercent: 41,
                    resetAt: "2026-06-19T14:42:15+00:00",
                    windowDurationMinutes: 300,
                    observedAt: "2026-06-19T20:26:45+08:00",
                    sourceType: "runtime_api",
                    confidence: "observed",
                    status: "ok",
                    official: true
                ),
            ]
        )
        let state = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion,
                client: summary.client,
                generatedAt: summary.generatedAt,
                timezone: summary.timezone,
                period: summary.period,
                trend: summary.trend,
                sources: summary.sources,
                breakdown: summary.breakdown,
                limits: duplicateLimits
            ),
            selectedPeriodID: "today"
        )

        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.outerPctText, "4%")
        XCTAssertEqual(claude.innerPctText, "53%")
        XCTAssertEqual(claude.outerFraction, 0.04, accuracy: 0.001)

        let codex = try XCTUnwrap(state.quotaRings.first { $0.id == "codex" })
        XCTAssertEqual(codex.outerPctText, "41%")
        XCTAssertEqual(codex.outerFraction, 0.41, accuracy: 0.001)
    }

    func testTrendSelectionFollowsMouseLocation() throws {
        let summary = try loadFixture()
        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "week")

        XCTAssertEqual(
            MenuTrendSelection.nearestBar(in: state.trendBars, xLocation: 1, width: 200)?.id,
            state.trendBars[0].id
        )
        XCTAssertEqual(
            MenuTrendSelection.nearestBar(in: state.trendBars, xLocation: 180, width: 200)?.id,
            state.trendBars[1].id
        )
    }

    func testRuntimeDefaultsStayOutOfDocuments() {
        let home = URL(fileURLWithPath: "/Users/product")

        let root = RuntimePaths.defaultRoot(homeDirectory: home)
        let paths = RuntimePaths(root: root)

        XCTAssertEqual(
            root.path,
            "/Users/product/Library/Application Support/ai-usage-widget/macos-menu-bar"
        )
        XCTAssertFalse(root.path.contains("/Documents/"))
        XCTAssertEqual(paths.configURL.lastPathComponent, "config.json")
        XCTAssertEqual(paths.cacheURL.lastPathComponent, "last-summary.json")
        XCTAssertEqual(paths.logURL.lastPathComponent, "menu-bar.log")
    }

    private func loadFixture() throws -> MobileSummary {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "mobile-summary", withExtension: "json"))
        let data = try Data(contentsOf: url)
        return try JSONDecoder().decode(MobileSummary.self, from: data)
    }
}
