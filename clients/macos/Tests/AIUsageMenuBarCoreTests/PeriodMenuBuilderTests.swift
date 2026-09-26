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

    // #177：「选择其他日期…」把 DatePicker 选中日期换算成当前粒度 offset。
    func testOffsetForDateConvertsDayWeekMonthGranularities() throws {
        let now = try date(fixedNowISO)
        XCTAssertEqual(
            PeriodMenuBuilder.offset(forDate: try date("2026-09-24T00:00:00+08:00"), periodID: "today", now: now, timezone: "Asia/Shanghai"),
            -2
        )
        XCTAssertEqual(
            PeriodMenuBuilder.offset(forDate: try date("2026-09-14T00:00:00+08:00"), periodID: "week", now: now, timezone: "Asia/Shanghai"),
            -1
        )
        XCTAssertEqual(
            PeriodMenuBuilder.offset(forDate: try date("2026-08-15T00:00:00+08:00"), periodID: "month", now: now, timezone: "Asia/Shanghai"),
            -1
        )
    }

    // #177 Opus 审查追加：未来日期一律裁到 0（今天/本周/本月），不能算出正的未来 offset。
    func testOffsetForDateClampsFutureDatesToZero() throws {
        let now = try date(fixedNowISO) // 2026-09-26（周六）
        XCTAssertEqual(
            PeriodMenuBuilder.offset(forDate: try date("2026-09-27T00:00:00+08:00"), periodID: "today", now: now, timezone: "Asia/Shanghai"),
            0
        )
        XCTAssertEqual(
            PeriodMenuBuilder.offset(forDate: try date("2026-10-05T00:00:00+08:00"), periodID: "week", now: now, timezone: "Asia/Shanghai"),
            0
        )
        XCTAssertEqual(
            PeriodMenuBuilder.offset(forDate: try date("2026-12-01T00:00:00+08:00"), periodID: "month", now: now, timezone: "Asia/Shanghai"),
            0
        )
    }

    // #177 Opus 审查追加：周从周一开始，选中「周日」必须归到上一个周一开始的那一周，不是下一周。
    func testOffsetForDateSundayBelongsToWeekStartingPriorMonday() throws {
        let now = try date(fixedNowISO) // 周六 2026-09-26，本周一是 2026-09-21
        // 2026-09-20 是周日，属于 09-14（周一）～09-20（周日）那一周，与直接选 09-14 结果一致（-1）。
        XCTAssertEqual(
            PeriodMenuBuilder.offset(forDate: try date("2026-09-20T00:00:00+08:00"), periodID: "week", now: now, timezone: "Asia/Shanghai"),
            -1
        )
    }

    // #177 Opus 审查追加：月份差跨年份边界要正确计入年份差，不能只比较月份数字。
    func testOffsetForDateMonthDiffCrossesYearBoundary() throws {
        let now = try date(fixedNowISO) // 2026-09-26
        // 2025-09-01 到 2026-09-26：跨一个整年，应为 12 个月前。
        XCTAssertEqual(
            PeriodMenuBuilder.offset(forDate: try date("2025-09-01T00:00:00+08:00"), periodID: "month", now: now, timezone: "Asia/Shanghai"),
            -12
        )
    }

    // #177 Opus 审查追加：DatePicker 给的是设备本地日历语义的 Date，不能直接当服务时区的绝对时刻算。
    // 设备在东京时区选中"今天"的本地日期，用户在上海服务时区看仍必须是"今天"（offset 0），
    // 而不是因为绝对时刻换算成上海时间已经是前一天而被误判成"昨天"（offset -1）。
    func testOffsetForPickedDateReinterpretsDeviceLocalDateInServerTimezone() throws {
        var tokyoCalendar = Calendar(identifier: .gregorian)
        tokyoCalendar.timeZone = try XCTUnwrap(TimeZone(identifier: "Asia/Tokyo"))
        let now = try date(fixedNowISO) // 2026-09-26T12:00:00+08:00（上海服务时区的"现在"，即"今天"）
        // 设备在东京时区，本地日历显示的是 2026-09-26 00:00（用户眼中选中的是"今天"）；
        // 这个绝对时刻按上海时区解释是 2026-09-25 23:00（前一天）。
        let pickedInTokyo = try date("2026-09-26T00:00:00+09:00")

        let naive = PeriodMenuBuilder.offset(forDate: pickedInTokyo, periodID: "today", now: now, timezone: "Asia/Shanghai")
        XCTAssertEqual(naive, -1, "不做设备日历重建时，绝对时刻换算会把东京的今天误判成上海的昨天")

        let reinterpreted = PeriodMenuBuilder.offsetForPickedDate(
            pickedInTokyo, periodID: "today", now: now, timezone: "Asia/Shanghai", deviceCalendar: tokyoCalendar
        )
        XCTAssertEqual(reinterpreted, 0, "先按设备本地日历取年月日、再在服务时区重建后，必须仍是今天")
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
