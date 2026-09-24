import XCTest
@testable import AIUsageMobileCore

final class MobileSummaryTests: XCTestCase {
    func testDecodesMobileSummaryContractFixture() throws {
        let summary = try loadFixture()

        XCTAssertEqual(summary.schemaVersion, 1)
        XCTAssertEqual(summary.client, "ios")
        XCTAssertEqual(summary.period.id, "week")
        XCTAssertEqual(summary.period.startDate, "2026-05-27")
        XCTAssertEqual(summary.period.endDate, "2026-06-02")
        XCTAssertEqual(summary.period.totalTokens, 5000)
        XCTAssertEqual(summary.period.cacheTokens, 800)
        XCTAssertEqual(summary.trend.points.last?.bucket, "2026-06-02")
        XCTAssertEqual(summary.trend.points.last?.cacheRatio, 17)
        XCTAssertEqual(summary.sources.first?.machine, "linux-dev")
        XCTAssertEqual(summary.breakdown.byMachine.first?.label, "linux-dev")
        XCTAssertEqual(summary.breakdown.byOSUser.first?.label, "wang")
        XCTAssertEqual(summary.breakdown.byModel.first?.label, "gpt-5")
        XCTAssertEqual(summary.limits.observedCount, 1)
        XCTAssertEqual(summary.limits.totalCount, 2)
    }

    func testBuildsHomeStateForSwiftUIShell() throws {
        let summary = try loadFixture()
        let state = MobileViewModel.build(from: summary)

        XCTAssertEqual(state.home.title, "AI Usage")
        XCTAssertEqual(state.home.totalText, "5.0K")
        XCTAssertEqual(state.home.rangeText, "2026-05-27 - 2026-06-02")
        XCTAssertEqual(state.home.healthText, "2/2 sources")
        XCTAssertEqual(state.home.primaryLimitText, "codex session · 60% left")
        XCTAssertEqual(state.home.topSources.map(\.label), ["linux-dev", "macbook-pro"])
        XCTAssertEqual(state.sources.count, 2)
        XCTAssertEqual(state.breakdown.byAgent.first?.label, "codex")
        XCTAssertEqual(state.limits.windows.last?.confidence, "missing")
    }

    func testLimitGroupsOnlyCountOfficialObservedWindowsAsTrusted() throws {
        let summary = try loadFixtureWithOnlyNonOfficialObservedLimit()
        let state = MobileViewModel.build(from: summary)

        XCTAssertEqual(state.home.primaryLimitText, "No observed quota")
        XCTAssertEqual(state.home.refreshGroups.first?.statText, "0/1 可信")
    }

    func testDecodesQuotaAccountAndPlanLabels() throws {
        let data = """
        {
          "source_id": "codex-main",
          "provider": "codex",
          "window": "session",
          "used_percent": 3.0,
          "remaining_percent": 97.0,
          "reset_at": "2026-06-02T15:45:00+08:00",
          "window_duration_minutes": 300,
          "observed_at": "2026-06-02T10:45:00+08:00",
          "source_type": "runtime_api",
          "confidence": "observed",
          "status": "ok",
          "official": true,
          "account_label": "startimessocietegn@gmail.com",
          "account_plan_label": "Pro 20x"
        }
        """.data(using: .utf8)!

        let window = try JSONDecoder().decode(MobileLimitWindow.self, from: data)

        XCTAssertEqual(window.accountLabel, "startimessocietegn@gmail.com")
        XCTAssertEqual(window.accountPlanLabel, "Pro 20x")
    }

    func testLimitGroupsExposeAccountLabelsFromWindows() throws {
        let window = MobileLimitWindow(
            sourceID: "codex-main",
            provider: "codex",
            window: "session",
            usedPercent: 3,
            remainingPercent: 97,
            resetAt: "2026-06-02T15:45:00+08:00",
            windowDurationMinutes: 300,
            observedAt: "2026-06-02T10:45:00+08:00",
            sourceType: "runtime_api",
            confidence: "observed",
            status: "ok",
            official: true,
            accountLabel: "startimessocietegn@gmail.com",
            accountPlanLabel: "Pro 20x"
        )

        let group = try XCTUnwrap(limitGroups(from: [window]).first)

        XCTAssertEqual(group.accountLabel, "startimessocietegn@gmail.com")
        XCTAssertEqual(group.accountPlanLabel, "Pro 20x")
    }

    func testAccountLabelTextCompactsLongEmailsInTheMiddle() {
        XCTAssertEqual(AccountLabelText.compactEmail("wangzhipeng2010@gmail.com"), "wang****010@gmail.com")
        XCTAssertEqual(AccountLabelText.compactEmail("startimessocietegn@gmail.com"), "star****egn@gmail.com")
        XCTAssertEqual(AccountLabelText.compactEmail("short@example.com"), "short@example.com")
    }

    func testFiveHourDisplayStateShowsResetZeroWhenObservedAtZeroPercent() {
        let window = MobileLimitWindow(
            sourceID: "claude-main",
            provider: "claude",
            window: "session",
            usedPercent: 0,
            remainingPercent: 100,
            resetAt: nil,
            windowDurationMinutes: 300,
            observedAt: "2026-06-02T10:45:00+08:00",
            sourceType: "oauth_usage_api",
            confidence: "observed",
            status: "ok",
            official: true,
            accountLabel: nil,
            accountPlanLabel: nil
        )

        XCTAssertEqual(QuotaWindowDisplayState.fiveHour(window: window).rowText, "5h 0% 已重置")
    }

    func testFiveHourDisplayStateKeepsUnknownRowWhenMissing() {
        XCTAssertEqual(QuotaWindowDisplayState.fiveHour(window: nil).rowText, "5h -- --")
    }

    func testSourcesViewStateFiltersZeroRowsAndDoesNotLimitToThree() {
        let rows = [
            breakdownRow("one", tokens: 100, sourceID: "s1"),
            breakdownRow("zero", tokens: 0, sourceID: "s0"),
            breakdownRow("two", tokens: 90, sourceID: "s2"),
            breakdownRow("three", tokens: 80, sourceID: "s3"),
            breakdownRow("four", tokens: 70, sourceID: "s4"),
        ]

        let visible = SourcesDisplayState.visibleRows(rows)

        XCTAssertEqual(visible.map(\.label), ["one", "two", "three", "four"])
    }

    func testHealthTextCountsFailedSourcesEvenWhenHiddenFromPeriodSources() {
        let summary = MobileSummary(
            schemaVersion: 1,
            client: "ios",
            generatedAt: "2026-06-21T10:00:00+08:00",
            timezone: "Asia/Shanghai",
            period: MobilePeriod(
                id: "today",
                date: "2026-06-21",
                startDate: nil,
                endDate: nil,
                totalTokens: 4000,
                inputTokens: 2000,
                outputTokens: 2000,
                cacheTokens: 0,
                cacheRatio: 0,
                machine: nil,
                account: nil
            ),
            trend: MobileTrend(
                period: "today",
                granularity: "hour",
                startDate: nil,
                endDate: nil,
                points: []
            ),
            sources: [
                mobileSource("active", status: "ok"),
                mobileSource("failed", status: "provider_failed")
            ],
            breakdown: MobileBreakdown(
                byMachine: [breakdownRow("active", tokens: 4000, sourceID: "active")],
                byOSUser: [],
                byAgent: [],
                byModel: [],
                byDate: []
            ),
            limits: MobileLimits(observedCount: 0, totalCount: 0, windows: [])
        )

        let state = MobileViewModel.build(from: summary)

        XCTAssertEqual(state.sources.map(\.sourceID), ["active"])
        XCTAssertEqual(state.home.healthText, "1 source issues")
    }

    func testSourceUpdateDateTextIncludesDayContext() {
        let now = makeDate("2026-06-21T10:00:00+08:00")

        XCTAssertEqual(SourceUpdateDateText.format("2026-06-21T09:42:00+08:00", now: now, timezone: "Asia/Shanghai"), "今天 09:42")
        XCTAssertEqual(SourceUpdateDateText.format("2026-06-20T22:10:00+08:00", now: now, timezone: "Asia/Shanghai"), "昨天 22:10")
        XCTAssertEqual(SourceUpdateDateText.format("2026-06-19T18:30:00+08:00", now: now, timezone: "Asia/Shanghai"), "06-19 18:30")
        XCTAssertEqual(SourceUpdateDateText.format("2025-12-31T18:30:00+08:00", now: now, timezone: "Asia/Shanghai"), "2025-12-31 18:30")
    }

    func testTokenFormatting() {
        XCTAssertEqual(TokenFormat.compact(999), "999")
        XCTAssertEqual(TokenFormat.compact(5_000), "5.0K")
        XCTAssertEqual(TokenFormat.compact(1_250_000), "1.2M")
        XCTAssertEqual(TokenFormat.compact(4_239_515_996), "4.2B")
    }

    func testBuildsEmptySummaryForSelectedLoadingPeriod() {
        let summary = MobileSummary.empty(periodID: "month")
        let state = MobileViewModel.build(from: summary)

        XCTAssertEqual(summary.period.id, "month")
        XCTAssertEqual(summary.period.totalTokens, 0)
        XCTAssertEqual(summary.period.inputTokens, 0)
        XCTAssertEqual(summary.period.outputTokens, 0)
        XCTAssertEqual(summary.period.cacheTokens, 0)
        XCTAssertEqual(summary.trend.period, "month")
        XCTAssertEqual(summary.trend.granularity, "day")
        XCTAssertTrue(summary.trend.points.isEmpty)
        XCTAssertTrue(summary.sources.isEmpty)
        XCTAssertTrue(summary.breakdown.byMachine.isEmpty)
        XCTAssertEqual(summary.limits.observedCount, 0)
        XCTAssertEqual(summary.limits.totalCount, 0)
        XCTAssertTrue(summary.limits.windows.isEmpty)
        XCTAssertEqual(state.home.periodID, "month")
        XCTAssertEqual(state.home.totalText, "0")
        XCTAssertTrue(state.home.trendPoints.isEmpty)
    }

    func testTrendPointSelectionDefaultsToLastNonZeroPoint() {
        let points = [
            trendPoint(bucket: "09:00", tokens: 100),
            trendPoint(bucket: "10:00", tokens: 0),
            trendPoint(bucket: "11:00", tokens: 250),
            trendPoint(bucket: "12:00", tokens: 0)
        ]

        XCTAssertEqual(TrendPointSelection.defaultPoint(in: points)?.bucket, "11:00")
    }

    func testTrendPointSelectionFindsNearestDragLocation() {
        let points = [
            trendPoint(bucket: "09:00", tokens: 100),
            trendPoint(bucket: "10:00", tokens: 200),
            trendPoint(bucket: "11:00", tokens: 300),
            trendPoint(bucket: "12:00", tokens: 400)
        ]

        XCTAssertEqual(
            TrendPointSelection.nearestPoint(in: points, xLocation: 77, width: 120)?.bucket,
            "11:00"
        )
    }

    func testTrendChartPresentationKeepsCompleteWeekMonthAndAllRanges() {
        for count in [7, 30, 76] {
            let points = (0..<count).map { index in
                trendPoint(bucket: String(format: "2026-%03d", index + 1), tokens: index + 1)
            }
            let visible = TrendChartPresentation.points(from: points)

            XCTAssertEqual(visible.count, count)
            XCTAssertEqual(visible.first?.bucket, points.first?.bucket)
            XCTAssertEqual(visible.last?.bucket, points.last?.bucket)
            XCTAssertEqual(visible.map(\.tokens).reduce(0, +), points.map(\.tokens).reduce(0, +))
        }
    }

    func testTrendTooltipShowsExactTotalAndAgentSegments() {
        let point = MobileTrendPoint(
            bucket: "2026-06-02",
            label: "06-02",
            tokens: 403_524_234,
            inputTokens: 0,
            outputTokens: 0,
            cacheTokens: 0,
            cacheRatio: 0,
            claudeTokens: 300_000_000,
            codexTokens: 100_000_000,
            geminiTokens: 2_000_000,
            unknownTokens: 1_524_234
        )

        let lines = TrendChartPresentation.tooltipLines(for: point)

        XCTAssertEqual(lines.label, "06-02")
        XCTAssertEqual(lines.total, "403.5M · 403,524,234")
        XCTAssertEqual(lines.claude, "Claude 300,000,000")
        XCTAssertEqual(lines.codex, "Codex 100,000,000")
        XCTAssertEqual(lines.gemini, "Gemini 2,000,000")
        XCTAssertEqual(lines.unknown, "未知 1,524,234")
    }

    func testTrendPointDecodesMissingSegmentsAsUnknownForOldCacheCompatibility() throws {
        let data = """
        {"bucket":"2026-06-02","label":"06-02","tokens":42,"input_tokens":42,"output_tokens":0,"cache_tokens":0,"cache_ratio":0}
        """.data(using: .utf8)!

        let point = try JSONDecoder().decode(MobileTrendPoint.self, from: data)

        XCTAssertEqual(point.claudeTokens, 0)
        XCTAssertEqual(point.codexTokens, 0)
        XCTAssertEqual(point.unknownTokens, 42)
    }

    func testDeterministicTrendFixtureCoversWeekMonthAndAllForSimulatorAcceptance() {
        for (period, count) in [("week", 7), ("month", 30), ("all", 76)] {
            let summary = MobileSummary.deterministicTrendFixture(periodID: period)

            XCTAssertEqual(summary.period.id, period)
            XCTAssertEqual(summary.trend.points.count, count)
            XCTAssertGreaterThan(summary.period.totalTokens, 0)
            XCTAssertEqual(summary.trend.points.map(\.tokens).reduce(0, +), summary.period.totalTokens)
            XCTAssertTrue(summary.trend.points.allSatisfy {
                $0.claudeTokens + $0.codexTokens + $0.unknownTokens == $0.tokens
            })
        }
    }

    func testCompanionCacheRejectsNonTodaySummaryForWidgets() throws {
        let summary = try loadFixture()
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let cacheURL = directory.appendingPathComponent(MobileSummaryCache.fileName)

        try MobileSummaryCache.write(summary, to: cacheURL)

        XCTAssertNil(MobileSummaryCache.readCompanionSummary(from: cacheURL))
    }

    func testCompanionCacheRoundTripsTodaySummaryForWidgets() throws {
        let summary = try makeTodaySummary()
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString, isDirectory: true)
        let cacheURL = directory.appendingPathComponent(MobileSummaryCache.fileName)

        try MobileSummaryCache.write(summary, to: cacheURL)
        let cached = try XCTUnwrap(MobileSummaryCache.readCompanionSummary(from: cacheURL))

        XCTAssertEqual(cached.period.id, "today")
        XCTAssertEqual(cached.period.totalTokens, 5000)
        XCTAssertEqual(cached.breakdown.byMachine.map(\.label), ["linux-dev", "macbook-pro"])
        XCTAssertEqual(cached.limits.observedCount, 1)
    }

    func testCompanionCacheUsesDevicectlReadableAppGroupCachesPath() {
        XCTAssertEqual(MobileSummaryCache.appGroupDirectoryPath, "Library/Caches")
        XCTAssertEqual(MobileSummaryCache.fileName, "last-mobile-summary.json")
    }

    private func loadFixture() throws -> MobileSummary {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "mobile-summary", withExtension: "json"))
        let data = try Data(contentsOf: url)
        return try JSONDecoder().decode(MobileSummary.self, from: data)
    }

    private func loadFixtureWithOnlyNonOfficialObservedLimit() throws -> MobileSummary {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "mobile-summary", withExtension: "json"))
        let data = try Data(contentsOf: url)
        var json = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
        var limits = json["limits"] as? [String: Any] ?? [:]
        limits["observed_count"] = 0
        limits["windows"] = [
            [
                "source_id": "local-estimate",
                "provider": "codex",
                "window": "week",
                "used_percent": 50.0,
                "remaining_percent": 50.0,
                "reset_at": "2026-06-08T00:00:00+08:00",
                "window_duration_minutes": 10080,
                "observed_at": "2026-06-03T09:31:00+08:00",
                "source_type": "ccusage_daily",
                "confidence": "observed",
                "status": "ok",
                "official": false
            ]
        ]
        json["limits"] = limits
        let modified = try JSONSerialization.data(withJSONObject: json, options: [.sortedKeys])
        return try JSONDecoder().decode(MobileSummary.self, from: modified)
    }

    private func makeTodaySummary() throws -> MobileSummary {
        let summary = try loadFixture()
        return MobileSummary(
            schemaVersion: summary.schemaVersion,
            client: summary.client,
            generatedAt: "2026-06-02T10:45:00+08:00",
            timezone: summary.timezone,
            period: MobilePeriod(
                id: "today",
                date: "2026-06-02",
                startDate: nil,
                endDate: nil,
                totalTokens: summary.period.totalTokens,
                inputTokens: summary.period.inputTokens,
                outputTokens: summary.period.outputTokens,
                cacheTokens: summary.period.cacheTokens,
                cacheRatio: summary.period.cacheRatio,
                machine: nil,
                account: nil
            ),
            trend: MobileTrend(
                period: "today",
                granularity: "hour",
                startDate: "2026-06-02T00:00:00+08:00",
                endDate: "2026-06-02T23:00:00+08:00",
                points: summary.trend.points
            ),
            sources: summary.sources,
            breakdown: summary.breakdown,
            limits: summary.limits
        )
    }

    private func trendPoint(bucket: String, tokens: Int) -> MobileTrendPoint {
        MobileTrendPoint(
            bucket: bucket,
            label: bucket,
            tokens: tokens,
            inputTokens: tokens,
            outputTokens: 0,
            cacheTokens: 0,
            cacheRatio: 0
        )
    }

    private func breakdownRow(_ label: String, tokens: Int, sourceID: String) -> MobileBreakdownRow {
        MobileBreakdownRow(
            id: label,
            label: label,
            tokens: tokens,
            sourceIDs: [sourceID],
            contributions: [MobileBreakdownContribution(sourceID: sourceID, tokens: tokens)]
        )
    }

    private func mobileSource(_ sourceID: String, status: String) -> MobileSource {
        MobileSource(
            sourceID: sourceID,
            machine: "\(sourceID)-host",
            osUser: "wang",
            platform: "darwin",
            displayName: "\(sourceID)-host · wang",
            status: status,
            lastObservedAt: "2026-06-21T09:42:00+08:00",
            lastPushedAt: "2026-06-21T09:42:00+08:00",
            errorMessage: nil
        )
    }

    private func makeDate(_ value: String) -> Date {
        let formatter = ISO8601DateFormatter()
        return formatter.date(from: value)!
    }
}
