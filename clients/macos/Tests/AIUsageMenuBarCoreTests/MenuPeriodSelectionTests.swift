import XCTest
@testable import AIUsageMenuBarCore

final class MenuPeriodSelectionTests: XCTestCase {
    func testOnlyDayWeekMonthAreSelectable() {
        XCTAssertEqual(MenuPeriodSelection.periodIDs, ["today", "week", "month"])
        XCTAssertEqual(MenuPeriodSelection(periodID: "all").periodID, "today")
    }

    func testEveryPeriodPreventsFutureAndCanReturnToCurrent() {
        for period in ["today", "week", "month"] {
            let current = MenuPeriodSelection(periodID: period)
            XCTAssertFalse(current.canGoLater, period)
            XCTAssertEqual(current.moving(1).offset, 0, period)
            let previous = current.moving(-1)
            XCTAssertEqual(previous.offset, -1, period)
            XCTAssertTrue(previous.canGoLater, period)
            XCTAssertEqual(previous.moving(1), current, period)
        }
    }

    func testDailyHistoryHasExactlySevenSelectableDays() {
        var selected = MenuPeriodSelection(periodID: "today")
        var offsets = [selected.offset]
        for _ in 0..<6 {
            XCTAssertTrue(selected.canGoEarlier)
            selected = selected.moving(-1)
            offsets.append(selected.offset)
        }
        XCTAssertEqual(offsets, [0, -1, -2, -3, -4, -5, -6])
        XCTAssertFalse(selected.canGoEarlier)
        XCTAssertEqual(selected.moving(-1).offset, -6)
        XCTAssertEqual(MenuPeriodSelection(periodID: "today", offset: -40).offset, -6)
        XCTAssertEqual(MenuPeriodSelection(periodID: "today", offset: 5).offset, 0)
    }

    func testWeeksAndMonthsCanGoPastSevenPeriodsWithUniqueCaches() {
        var keys = Set<String>()
        for period in ["week", "month"] {
            for offset in -12...0 {
                let selected = MenuPeriodSelection(periodID: period, offset: offset)
                XCTAssertEqual(selected.offset, offset)
                XCTAssertTrue(selected.canGoEarlier)
                keys.insert(selected.cacheKey)
            }
        }
        XCTAssertEqual(keys.count, 26)
    }
}
