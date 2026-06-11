import XCTest
@testable import AIUsageMobileCore

final class WidgetSummaryTests: XCTestCase {
    func testWidgetPrefersObservedOfficialLimit() throws {
        let summary = try loadFixture()
        let state = WidgetSummaryBuilder.build(from: summary)

        XCTAssertTrue(state.usesObservedLimit)
        XCTAssertEqual(state.primaryText, "60%")
        XCTAssertEqual(state.secondaryText, "codex session left")
        XCTAssertEqual(state.status, .ok)
        XCTAssertEqual(state.statusText, "2/2 sources")
    }

    func testWidgetFallsBackToUsageWhenLimitsAreMissing() throws {
        let summary = try loadFixtureWithoutObservedLimits()
        let state = WidgetSummaryBuilder.build(from: summary)

        XCTAssertFalse(state.usesObservedLimit)
        XCTAssertEqual(state.primaryText, "5.0K")
        XCTAssertEqual(state.secondaryText, "week tokens")
        XCTAssertEqual(state.status, .issue)
        XCTAssertEqual(state.statusText, "1 source issue")
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
}
