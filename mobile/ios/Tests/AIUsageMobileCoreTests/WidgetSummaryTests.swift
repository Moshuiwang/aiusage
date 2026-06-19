import XCTest
@testable import AIUsageMobileCore

final class WidgetSummaryTests: XCTestCase {
    func testWidgetUsesUsageAsPrimaryMetricEvenWhenLimitsExist() throws {
        let summary = try makeTodaySummary()
        let state = WidgetSummaryBuilder.build(
            from: summary,
            now: date("2026-06-02T11:15:00+08:00")
        )

        XCTAssertFalse(state.usesObservedLimit)
        XCTAssertEqual(state.primaryText, "5.0K")
        XCTAssertEqual(state.secondaryText, "Input 2.8K · Output 1.4K · Cache 800")
        XCTAssertEqual(state.periodText, "Today")
        XCTAssertEqual(state.updatedText, "06/02 10:45")
        XCTAssertEqual(state.status, .ok)
        XCTAssertEqual(state.statusText, "2/2 sources")
    }

    func testWidgetFallsBackToUsageWhenLimitsAreMissing() throws {
        let summary = try makeTodaySummary(from: loadFixtureWithoutObservedLimits())
        let state = WidgetSummaryBuilder.build(
            from: summary,
            now: date("2026-06-02T11:15:00+08:00")
        )

        XCTAssertFalse(state.usesObservedLimit)
        XCTAssertEqual(state.primaryText, "5.0K")
        XCTAssertEqual(state.secondaryText, "Input 2.8K · Output 1.4K · Cache 800")
        XCTAssertEqual(state.status, .issue)
        XCTAssertEqual(state.statusText, "1 source issue")
    }

    func testWidgetMarksOldTodayCacheAsStale() throws {
        let summary = try makeTodaySummary()
        let state = WidgetSummaryBuilder.build(
            from: summary,
            now: date("2026-06-02T14:46:00+08:00")
        )

        XCTAssertEqual(state.status, .stale)
        XCTAssertEqual(state.statusText, "缓存过期")
        XCTAssertEqual(state.periodText, "Today")
        XCTAssertEqual(state.updatedText, "06/02 10:45")
    }

    func testWidgetTreatsNonTodaySummaryAsUnsafeForGlance() throws {
        let summary = try loadFixture()
        let state = WidgetSummaryBuilder.build(
            from: summary,
            now: date("2026-06-02T11:15:00+08:00")
        )

        XCTAssertEqual(state.status, .issue)
        XCTAssertEqual(state.statusText, "非今日缓存")
        XCTAssertEqual(state.periodText, "Week")
    }

    private func loadFixture() throws -> MobileSummary {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "mobile-summary", withExtension: "json"))
        let data = try Data(contentsOf: url)
        return try JSONDecoder().decode(MobileSummary.self, from: data)
    }

    private func loadFixtureWithoutObservedLimits() throws -> MobileSummary {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "mobile-summary", withExtension: "json"))
        let data = try Data(contentsOf: url)
        var json = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
        var limits = json["limits"] as? [String: Any] ?? [:]
        limits["observed_count"] = 0
        limits["windows"] = [
            [
                "source_id": "claude-weekly",
                "provider": "claude",
                "window": "week",
                "used_percent": 0.0,
                "remaining_percent": 0.0,
                "reset_at": "2026-06-02T10:45:00+08:00",
                "window_duration_minutes": 10080,
                "observed_at": "2026-06-02T10:45:00+08:00",
                "source_type": "oauth_usage_api",
                "confidence": "missing",
                "status": "provider_failed",
                "official": false
            ]
        ]
        json["limits"] = limits
        var sources = json["sources"] as? [[String: Any]] ?? []
        if !sources.isEmpty {
            sources[0]["status"] = "command_failed"
        }
        json["sources"] = sources
        let modified = try JSONSerialization.data(withJSONObject: json, options: [.sortedKeys])
        return try JSONDecoder().decode(MobileSummary.self, from: modified)
    }

    private func makeTodaySummary(from summary: MobileSummary? = nil) throws -> MobileSummary {
        let source = try summary ?? loadFixture()
        return MobileSummary(
            schemaVersion: source.schemaVersion,
            client: source.client,
            generatedAt: "2026-06-02T10:45:00+08:00",
            timezone: source.timezone,
            period: MobilePeriod(
                id: "today",
                date: "2026-06-02",
                startDate: nil,
                endDate: nil,
                totalTokens: source.period.totalTokens,
                inputTokens: source.period.inputTokens,
                outputTokens: source.period.outputTokens,
                cacheTokens: source.period.cacheTokens,
                cacheRatio: source.period.cacheRatio,
                machine: nil,
                account: nil
            ),
            trend: MobileTrend(
                period: "today",
                granularity: "hour",
                startDate: "2026-06-02T00:00:00+08:00",
                endDate: "2026-06-02T23:00:00+08:00",
                points: source.trend.points
            ),
            sources: source.sources,
            breakdown: source.breakdown,
            limits: source.limits
        )
    }

    private func date(_ value: String) -> Date {
        let formatter = ISO8601DateFormatter()
        return formatter.date(from: value) ?? Date(timeIntervalSince1970: 0)
    }
}
