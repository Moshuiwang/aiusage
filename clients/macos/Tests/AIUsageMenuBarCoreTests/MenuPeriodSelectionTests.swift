import XCTest
@testable import AIUsageMenuBarCore

final class MenuPeriodSelectionTests: XCTestCase {
    func testOnlyDayWeekMonthAreSelectable() {
        XCTAssertEqual(MenuPeriodSelection.periodIDs, ["today", "week", "month"])
        XCTAssertEqual(MenuPeriodSelection(periodID: "all").periodID, "today")
    }

    // #177：canGoEarlier/canGoLater/moving 随 historyNavigation（左右翻页）一起删除；
    // 这里只保留仍在用的 offset 裁剪规则（today: -6...0，week/month: ...0）。
    func testTodayOffsetClampsToExactlySevenSelectableDays() {
        XCTAssertEqual(MenuPeriodSelection(periodID: "today", offset: -40).offset, -6)
        XCTAssertEqual(MenuPeriodSelection(periodID: "today", offset: 5).offset, 0)
        XCTAssertEqual(MenuPeriodSelection(periodID: "today", offset: -6).offset, -6)
        XCTAssertEqual(MenuPeriodSelection(periodID: "today", offset: 0).offset, 0)
    }

    func testWeeksAndMonthsCanGoPastSevenPeriodsWithUniqueCachesAndClampFuture() {
        var keys = Set<String>()
        for period in ["week", "month"] {
            for offset in -12...0 {
                let selected = MenuPeriodSelection(periodID: period, offset: offset)
                XCTAssertEqual(selected.offset, offset)
                keys.insert(selected.cacheKey)
            }
            // week/month 没有 today 那样的 -6 下限，但同样不允许未来（offset 一律裁到 0）。
            XCTAssertEqual(MenuPeriodSelection(periodID: period, offset: 3).offset, 0)
        }
        XCTAssertEqual(keys.count, 26)
    }
}
