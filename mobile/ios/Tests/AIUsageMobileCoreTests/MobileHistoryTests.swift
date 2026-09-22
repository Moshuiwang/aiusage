import Foundation
import XCTest
@testable import AIUsageMobileCore

final class MobileHistoryTests: XCTestCase {
    func testNavigationStopsAtTodayAndSeventhDayButWeeksAndMonthsContinue() {
        let day = MobileHistorySelection()
        XCTAssertFalse(day.canGoLater)
        XCTAssertEqual(day.later.offset, 0)
        XCTAssertEqual(day.earlier.offset, -1)
        let oldest = MobileHistorySelection(period: "today", offset: -6)
        XCTAssertFalse(oldest.canGoEarlier)
        XCTAssertEqual(oldest.earlier.offset, -6)
        XCTAssertEqual(oldest.later.offset, -5)
        XCTAssertFalse(oldest.isCurrentDay)
        XCTAssertEqual(MobileHistorySelection(period: "today", offset: -99).offset, -6)
        for period in ["week", "month"] {
            let selection = MobileHistorySelection(period: period, offset: -30)
            XCTAssertTrue(selection.canGoEarlier)
            XCTAssertTrue(selection.canGoLater)
            XCTAssertEqual(selection.earlier.offset, -31)
            XCTAssertFalse(MobileHistorySelection(period: period, offset: 99).canGoLater)
        }
    }

    func testHistoryCacheSeparatesOffsetsAndRejectsLateResponsesIncludingReturnToSameDay() {
        var state = MobileHistoryState()
        let today = MobileHistorySelection()
        let yesterday = today.earlier
        let original = state.begin(today)
        let currentSummary = MobileSummary.deterministicTrendFixture(periodID: "today")
        XCTAssertTrue(state.accept(currentSummary, requestID: original))
        let historyRequest = state.begin(yesterday)
        XCTAssertNil(state.summary.generatedAt, "Do not label today's cached data as yesterday")
        let emptyHistorical = MobileSummary.empty(periodID: "today", generatedAt: "history")
        XCTAssertTrue(state.accept(emptyHistorical, requestID: historyRequest))
        let latest = state.begin(today)
        XCTAssertEqual(state.summary.period.totalTokens, currentSummary.period.totalTokens)
        XCTAssertFalse(state.accept(emptyHistorical, requestID: historyRequest))
        XCTAssertFalse(state.accept(emptyHistorical, requestID: original), "The same period is still an older request")
        XCTAssertEqual(state.summary.period.totalTokens, currentSummary.period.totalTokens)
        XCTAssertTrue(state.accept(currentSummary, requestID: latest))
        _ = state.begin(yesterday)
        XCTAssertEqual(state.summary.generatedAt, "history")
        _ = state.begin(MobileHistorySelection(period: "month", offset: -1))
        XCTAssertEqual(state.summary.period.id, "month")
        XCTAssertNil(state.summary.generatedAt)
    }

    func testTitlesUseAuthoritativeDatesAcrossYearAndMonthBoundaries() throws {
        let summary = MobileSummary.deterministicTrendFixture(periodID: "month")
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(summary)) as? [String: Any])
        var period = try XCTUnwrap(object["period"] as? [String: Any])
        period["start_date"] = "2025-12-01"
        period["end_date"] = "2025-12-31"
        object["period"] = period
        let oldMonth = try JSONDecoder().decode(MobileSummary.self, from: JSONSerialization.data(withJSONObject: object))
        XCTAssertEqual(MobilePeriodTitle.title(oldMonth.period, selection: MobileHistorySelection(period: "month", offset: -1)), "2025年12月")
        XCTAssertEqual(MobileViewModel.build(from: oldMonth).home.rangeText, "2025-12-01 - 2025-12-31")
        XCTAssertEqual(MobilePeriodTitle.title(summary.period, selection: MobileHistorySelection(period: "today", offset: -1)), "2026-07-18")
    }

    func testRelativeHistoryCacheExpiresAcrossShanghaiMidnight() throws {
        var state = MobileHistoryState()
        let before = ISO8601DateFormatter().date(from: "2026-07-18T23:59:00+08:00")!
        let after = before.addingTimeInterval(120)
        for period in ["today", "week", "month"] {
            let selection = MobileHistorySelection(period: period, offset: -1)
            let request = state.begin(selection, now: before)
            XCTAssertTrue(state.accept(.deterministicTrendFixture(periodID: period), requestID: request, now: before))
        }
        for period in ["today", "week", "month"] {
            _ = state.begin(MobileHistorySelection(period: period, offset: -1), now: after)
            XCTAssertNil(state.summary.generatedAt)
        }
    }

    func testWidgetMarksPreviousShanghaiDayStaleEvenWithinTwoHours() throws {
        let base = MobileSummary.deterministicTrendFixture(periodID: "today")
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(base)) as? [String: Any])
        object["generated_at"] = "2026-07-18T23:45:00+08:00"
        let summary = try JSONDecoder().decode(MobileSummary.self, from: JSONSerialization.data(withJSONObject: object))
        let now = ISO8601DateFormatter().date(from: "2026-07-19T00:15:00+08:00")!
        XCTAssertTrue(MobileSummaryCache.isStale(summary, now: now))
        XCTAssertEqual(WidgetSummaryBuilder.build(from: summary, now: now).status, .stale)
    }

    func testResponseCrossingShanghaiMidnightCannotPopulateRelativeCache() {
        var state = MobileHistoryState()
        let before = ISO8601DateFormatter().date(from: "2026-07-18T23:59:00+08:00")!
        let after = before.addingTimeInterval(120)
        let selection = MobileHistorySelection()
        let request = state.begin(selection, now: before)
        XCTAssertFalse(state.accept(.deterministicTrendFixture(periodID: "today"), requestID: request, now: after))
        XCTAssertNil(state.summary.generatedAt)
        let refreshed = state.begin(selection, now: after)
        XCTAssertTrue(state.accept(.empty(periodID: "today", generatedAt: "new-day"), requestID: refreshed, now: after))
        XCTAssertEqual(state.summary.generatedAt, "new-day")
    }

    func testFailedRefreshExpiresEveryRelativePeriodAtMidnightButPreservesSameDayCache() {
        let before = ISO8601DateFormatter().date(from: "2026-07-18T23:59:00+08:00")!
        let after = before.addingTimeInterval(120)
        let selections = [
            MobileHistorySelection(period: "today", offset: 0),
            MobileHistorySelection(period: "today", offset: -1),
            MobileHistorySelection(period: "today", offset: -6),
            MobileHistorySelection(period: "week", offset: 0),
            MobileHistorySelection(period: "week", offset: -1),
            MobileHistorySelection(period: "month", offset: 0),
            MobileHistorySelection(period: "month", offset: -1),
        ]
        XCTAssertEqual(selections.count, 7)
        for selection in selections {
            var state = MobileHistoryState(selection: selection)
            let cached = MobileSummary.deterministicTrendFixture(periodID: selection.period)
            let original = state.begin(selection, now: before)
            XCTAssertTrue(state.accept(cached, requestID: original, now: before))
            let refreshing = state.begin(selection, now: before)
            XCTAssertTrue(state.fail(requestID: refreshing, now: before))
            XCTAssertEqual(state.summary, cached, "Same-day failure must keep all cached fields")
            XCTAssertTrue(state.fail(requestID: refreshing, now: after))
            XCTAssertEqual(state.selection, selection)
            XCTAssertNil(state.summary.generatedAt, selection.cacheKey)
            XCTAssertNil(state.summary.period.date, selection.cacheKey)
            XCTAssertTrue(state.summary.sources.isEmpty, selection.cacheKey)
            XCTAssertFalse(MobileSummaryCache.isCompanionEligible(state.summary))
            _ = state.begin(selection, now: after)
            XCTAssertNil(state.summary.generatedAt, "The previous day's cached entry must be gone")
        }
    }

    func testObsoleteFailureCannotClearNewRequestsSuccessfulSummary() {
        let before = ISO8601DateFormatter().date(from: "2026-07-18T23:59:00+08:00")!
        let after = before.addingTimeInterval(120)
        var state = MobileHistoryState()
        let old = state.begin(MobileHistorySelection(), now: before)
        let selected = MobileHistorySelection(period: "month", offset: -1)
        let current = state.begin(selected, now: after)
        let summary = MobileSummary.deterministicTrendFixture(periodID: "month")
        XCTAssertTrue(state.accept(summary, requestID: current, now: after))
        XCTAssertFalse(state.fail(requestID: old, now: after))
        XCTAssertEqual(state.summary, summary)
        XCTAssertEqual(state.selection, selected)
    }

    func testOnlyThreeTimeTabsRemain() {
        XCTAssertEqual(PeriodTab.allCases.map(\.id), ["today", "week", "month"])
    }

    func testDefaultAndObsoleteSavedPeriodOpenToday() {
        let defaults = UserDefaults(suiteName: "MobileHistoryTests.\(UUID())")!
        XCTAssertEqual(MobileSummaryRuntimeConfig.initialPeriod(environment: [:], defaults: defaults), "today")
        defaults.set("all", forKey: "AIUsagePeriod")
        XCTAssertEqual(MobileSummaryRuntimeConfig.initialPeriod(environment: [:], defaults: defaults), "today")
    }

    func testHistoricalDayCannotMasqueradeAsTodayForCompanions() throws {
        let today = MobileSummary.deterministicTrendFixture(periodID: "today")
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(today)) as? [String: Any])
        var period = try XCTUnwrap(object["period"] as? [String: Any])
        period["date"] = "2026-07-17"
        object["period"] = period
        let historical = try JSONDecoder().decode(MobileSummary.self, from: JSONSerialization.data(withJSONObject: object))
        XCTAssertTrue(MobileSummaryCache.isCompanionEligible(today))
        XCTAssertFalse(MobileSummaryCache.isCompanionEligible(historical))
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("ios-history-\(UUID())")
        defer { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("summary.json")
        try MobileSummaryCache.write(historical, to: url)
        XCTAssertNil(MobileSummaryCache.readCompanionSummary(from: url))
        XCTAssertEqual(MobileSummaryCache.writeToAppGroup(historical).status, "not_attempted")
    }
}
