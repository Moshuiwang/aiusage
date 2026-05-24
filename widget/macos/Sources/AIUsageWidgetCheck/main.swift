import AIUsageWidgetCore
import Foundation

func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    if !condition() {
        fputs("check failed: \(message)\n", stderr)
        exit(1)
    }
}

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

expect(summary.today == "2026-05-22", "today date")
expect(summary.totalTokens == 70, "today total")
expect(summary.machineTotals == [
    GroupTotal(name: "macbook", totalTokens: 60),
    GroupTotal(name: "dev-server", totalTokens: 10)
], "machine totals")
expect(summary.failedSources.map(\.sourceID) == ["linux-wang"], "failed sources")
expect(summary.okSourceCount == 1, "ok source count")
expect(summary.totalSourceCount == 2, "total source count")
expect(TokenFormat.compact(12_345_678) == "12.3M", "compact token format")

print("AIUsageWidgetCheck OK")
