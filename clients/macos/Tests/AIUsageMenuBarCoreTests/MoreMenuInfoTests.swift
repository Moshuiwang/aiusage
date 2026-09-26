import XCTest
@testable import AIUsageMenuBarCore

final class MoreMenuInfoTests: XCTestCase {
    private func source(id: String, status: String) -> MobileSource {
        MobileSource(
            sourceID: id, machine: nil, osUser: nil, platform: nil, displayName: nil,
            status: status, lastObservedAt: nil, lastPushedAt: nil, errorMessage: nil
        )
    }

    func testFirstLineIsThePassedInVersionText() {
        let lines = MoreMenuInfo.build(sources: [], cacheBytes: 0, versionText: "版本 2.0.0 (293 · 6694a5f)")
        XCTAssertEqual(lines.first, "版本 2.0.0 (293 · 6694a5f)")
    }

    func testCountsOnlyOkSourcesAsOnline() {
        let sources = [
            source(id: "a", status: "ok"),
            source(id: "b", status: "ok"),
            source(id: "c", status: "stale"),
        ]
        let lines = MoreMenuInfo.build(sources: sources, cacheBytes: 0, versionText: "v")
        XCTAssertEqual(lines[2], "同步源 3 个 · 2 个在线")
    }

    func testZeroSourcesReportsZeroOfZero() {
        let lines = MoreMenuInfo.build(sources: [], cacheBytes: 0, versionText: "v")
        XCTAssertEqual(lines[2], "同步源 0 个 · 0 个在线")
    }

    func testCacheLineUsesByteCountFormatterFileStyle() {
        let expected = { () -> String in
            let formatter = ByteCountFormatter()
            formatter.countStyle = .file
            formatter.allowedUnits = [.useAll]
            return formatter.string(fromByteCount: 414_310)
        }()
        let lines = MoreMenuInfo.build(sources: [], cacheBytes: 414_310, versionText: "v")
        XCTAssertEqual(lines[1], "本地缓存 \(expected)")
    }

    func testNegativeCacheBytesClampToZeroInsteadOfCrashingFormatter() {
        let lines = MoreMenuInfo.build(sources: [], cacheBytes: -5, versionText: "v")
        XCTAssertTrue(lines[1].hasPrefix("本地缓存"))
    }

    func testReturnsExactlyThreeLinesInFixedOrder() {
        // 结构下限：这里锁「恰好三行、顺序固定」，防止有人悄悄多加一行或调换顺序。
        let lines = MoreMenuInfo.build(sources: [source(id: "a", status: "ok")], cacheBytes: 1, versionText: "v")
        XCTAssertEqual(lines.count, 3)
    }
}
