import XCTest
@testable import AIUsageMenuBarCore

/// #176：期间菜单只读已有缓存，不发请求；行数、标题/副标题、命中/未命中、offset 语义漂移。
final class PeriodMenuBuilderTests: XCTestCase {
    // now 固定在 2026-09-26（周六）12:00 +08:00，方便算 周一起始 / 月初。
    private let fixedNowISO = "2026-09-26T12:00:00+08:00"

    func testTodayHasSevenRowsOffsetZeroToMinusSix() throws {
        let rows = PeriodMenuBuilder.rows(
            periodID: "today", now: try date(fixedNowISO), timezone: "Asia/Shanghai",
            cached: { _ in nil }
        )
        XCTAssertEqual(rows.count, 7)
        XCTAssertEqual(rows.map(\.selection.offset), [0, -1, -2, -3, -4, -5, -6])
    }

    func testWeekHasSixRowsOffsetZeroToMinusFive() throws {
        let rows = PeriodMenuBuilder.rows(
            periodID: "week", now: try date(fixedNowISO), timezone: "Asia/Shanghai",
            cached: { _ in nil }
        )
        XCTAssertEqual(rows.count, 6)
        XCTAssertEqual(rows.map(\.selection.offset), [0, -1, -2, -3, -4, -5])
    }

    func testMonthHasSixRowsOffsetZeroToMinusFive() throws {
        let rows = PeriodMenuBuilder.rows(
            periodID: "month", now: try date(fixedNowISO), timezone: "Asia/Shanghai",
            cached: { _ in nil }
        )
        XCTAssertEqual(rows.count, 6)
        XCTAssertEqual(rows.map(\.selection.offset), [0, -1, -2, -3, -4, -5])
    }

    func testTodayTitlesAndSubtitles() throws {
        let rows = PeriodMenuBuilder.rows(
            periodID: "today", now: try date(fixedNowISO), timezone: "Asia/Shanghai",
            cached: { _ in nil }
        )
        XCTAssertEqual(rows.map(\.title), ["今天", "昨天", "前天", "9月23日", "9月22日", "9月21日", "9月20日"])
        XCTAssertEqual(rows.map(\.subtitle), ["9月26日", "9月25日", "9月24日", "9月23日", "9月22日", "9月21日", "9月20日"])
    }

    func testWeekTitlesAndSubtitles() throws {
        // 2026-09-26 是周六，本周一是 2026-09-21。
        let rows = PeriodMenuBuilder.rows(
            periodID: "week", now: try date(fixedNowISO), timezone: "Asia/Shanghai",
            cached: { _ in nil }
        )
        XCTAssertEqual(rows[0].title, "本周")
        XCTAssertEqual(rows[0].subtitle, "9月21日–26日") // 本周（offset 0）到今天为止
        XCTAssertEqual(rows[1].title, "上周")
        XCTAssertEqual(rows[1].subtitle, "9月14日–20日")
        XCTAssertEqual(rows[2].title, "9月7日–13日")
        XCTAssertEqual(rows[2].subtitle, "9月7日–13日")
    }

    func testMonthTitlesAndSubtitles() throws {
        let rows = PeriodMenuBuilder.rows(
            periodID: "month", now: try date(fixedNowISO), timezone: "Asia/Shanghai",
            cached: { _ in nil }
        )
        XCTAssertEqual(rows[0].title, "本月")
        XCTAssertEqual(rows[0].subtitle, "9月1日–26日")
        XCTAssertEqual(rows[1].title, "上月")
        XCTAssertEqual(rows[1].subtitle, "8月1日–31日")
        XCTAssertEqual(rows[2].title, "2026年7月")
        XCTAssertEqual(rows[2].subtitle, "7月1日–31日")
    }

    func testCacheHitShowsExactTotalAndSegments() throws {
        let cachedSummary = try summary(
            periodID: "today", date: "2026-09-25", startDate: "2026-09-25",
            totalTokens: 4200,
            points: [point(bucket: "2026-09-25T10:00:00+08:00", tokens: 4200, claude: 4200)]
        )
        let rows = PeriodMenuBuilder.rows(
            periodID: "today", now: try date(fixedNowISO), timezone: "Asia/Shanghai",
            cached: { selection in selection.offset == -1 ? cachedSummary : nil }
        )
        let row = rows[1]
        XCTAssertEqual(row.totalText, "4.2K")
        XCTAssertEqual(row.segments.map(\.provider), [.claude])
        XCTAssertEqual(row.segments.map(\.tokens), [4200])
    }

    func testCacheMissShowsDash() throws {
        let rows = PeriodMenuBuilder.rows(
            periodID: "today", now: try date(fixedNowISO), timezone: "Asia/Shanghai",
            cached: { _ in nil }
        )
        XCTAssertTrue(rows.allSatisfy { $0.totalText == "—" })
        XCTAssertTrue(rows.allSatisfy { $0.segments.isEmpty })
    }

    /// offset 语义漂移：缓存 key "today:-1" 里的 summary 实际 date 是「前天」（说明缓存是昨天存的，
    /// 今天已经跨天，-1 现在应该指昨天而不是前天）——必须判定未命中，不能被 offset 字面值骗过。
    func testStaleOffsetCacheWithDriftedActualDateIsTreatedAsMiss() throws {
        let driftedSummary = try summary(
            periodID: "today", date: "2026-09-24", startDate: "2026-09-24",
            totalTokens: 999,
            points: []
        )
        let rows = PeriodMenuBuilder.rows(
            periodID: "today", now: try date(fixedNowISO), timezone: "Asia/Shanghai",
            cached: { selection in selection.offset == -1 ? driftedSummary : nil }
        )
        XCTAssertEqual(rows[1].totalText, "—", "offset -1 期望起始日期是 09-25，缓存里实际是 09-24，必须判未命中")
    }

    // MARK: - helpers

    private func summary(
        periodID: String,
        date: String?,
        startDate: String?,
        totalTokens: Int,
        points: [MobileTrendPoint]
    ) throws -> MobileSummary {
        MobileSummary(
            schemaVersion: 1,
            client: "macos",
            generatedAt: "2026-09-25T12:00:00+08:00",
            timezone: "Asia/Shanghai",
            period: MobilePeriod(
                id: periodID, date: date, startDate: startDate, endDate: startDate,
                totalTokens: totalTokens, inputTokens: totalTokens, outputTokens: 0,
                cacheTokens: 0, cacheRatio: 0, machine: nil, account: nil
            ),
            trend: MobileTrend(period: periodID, granularity: periodID == "today" ? "hour" : "day", startDate: startDate, endDate: startDate, points: points),
            sources: [],
            breakdown: MobileBreakdown(byMachine: [], byOSUser: [], byAgent: [], byModel: [], byDate: []),
            limits: MobileLimits(observedCount: 0, totalCount: 0, windows: [])
        )
    }

    private func point(bucket: String, tokens: Int, claude: Int = 0, codex: Int = 0, gemini: Int = 0) -> MobileTrendPoint {
        MobileTrendPoint(
            bucket: bucket, label: bucket, tokens: tokens,
            inputTokens: tokens, outputTokens: 0, cacheTokens: 0, cacheRatio: 0,
            claudeTokens: claude, codexTokens: codex, geminiTokens: gemini
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
