import XCTest
@testable import AIUsageWidgetCore

final class UsageSummaryTests: XCTestCase {
    func testBuildsTodayTotalsAndGroups() throws {
        let snapshot = LatestSnapshot(
            generatedAt: "2026-05-22T13:03:51+08:00",
            timezone: "Asia/Shanghai",
            items: [
                UsageItem(
                    machine: "macbook",
                    account: "local",
                    agent: "all",
                    date: "2026-05-22",
                    inputTokens: 10,
                    outputTokens: 20,
                    cacheCreationTokens: 0,
                    cacheReadTokens: 30,
                    totalTokens: 60
                ),
                UsageItem(
                    machine: "dev-server",
                    account: "wang",
                    agent: "codex",
                    date: "2026-05-22",
                    inputTokens: 1,
                    outputTokens: 2,
                    cacheCreationTokens: 3,
                    cacheReadTokens: 4,
                    totalTokens: 10
                ),
                UsageItem(
                    machine: "macbook",
                    account: "local",
                    agent: "all",
                    date: "2026-05-21",
                    inputTokens: 100,
                    outputTokens: 200,
                    cacheCreationTokens: 0,
                    cacheReadTokens: 300,
                    totalTokens: 600
                )
            ],
            sourceStatus: [
                SourceStatus(sourceID: "mac-local", status: "ok", errorType: nil, message: nil),
                SourceStatus(sourceID: "linux-wang", status: "failed", errorType: "ssh_failed", message: nil),
                SourceStatus(sourceID: "disabled", status: "disabled", errorType: nil, message: nil)
            ]
        )

        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        let date = DateComponents(
            calendar: calendar,
            timeZone: calendar.timeZone,
            year: 2026,
            month: 5,
            day: 22,
            hour: 12
        ).date!

        let summary = UsageSummaryBuilder.build(from: snapshot, now: date, calendar: calendar)

        XCTAssertEqual(summary.today, "2026-05-22")
        XCTAssertEqual(summary.totalTokens, 70)
        XCTAssertEqual(summary.machineTotals, [
            GroupTotal(name: "macbook", totalTokens: 60),
            GroupTotal(name: "dev-server", totalTokens: 10)
        ])
        XCTAssertEqual(summary.accountTotals.first, GroupTotal(name: "local", totalTokens: 60))
        XCTAssertEqual(summary.agentTotals.first, GroupTotal(name: "all", totalTokens: 60))
        XCTAssertEqual(summary.failedSources.map(\.sourceID), ["linux-wang"])
        XCTAssertEqual(summary.okSourceCount, 1)
        XCTAssertEqual(summary.totalSourceCount, 2)
    }

    func testTokenFormatting() {
        XCTAssertEqual(TokenFormat.compact(999), "999")
        XCTAssertEqual(TokenFormat.compact(12_345), "12.3K")
        XCTAssertEqual(TokenFormat.compact(12_345_678), "12.3M")
    }
}
