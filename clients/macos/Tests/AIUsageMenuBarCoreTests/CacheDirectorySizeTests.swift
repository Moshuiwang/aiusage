import XCTest
@testable import AIUsageMenuBarCore

final class CacheDirectorySizeTests: XCTestCase {
    private var tempDir: URL!

    override func setUpWithError() throws {
        tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("cache-dir-size-tests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tempDir)
    }

    func testReturnsZeroWhenDirectoryDoesNotExist() {
        let missing = tempDir.appendingPathComponent("does-not-exist", isDirectory: true)
        XCTAssertEqual(CacheDirectorySize.compute(at: missing), 0)
    }

    func testSumsRegularFilesIncludingSubdirectories() throws {
        try Data(repeating: 0, count: 100).write(to: tempDir.appendingPathComponent("a.json"))
        let sub = tempDir.appendingPathComponent("sub", isDirectory: true)
        try FileManager.default.createDirectory(at: sub, withIntermediateDirectories: true)
        try Data(repeating: 0, count: 250).write(to: sub.appendingPathComponent("b.json"))

        XCTAssertEqual(CacheDirectorySize.compute(at: tempDir), 350)
    }

    func testDoesNotCountSiblingFilesOutsideTheDirectory() throws {
        // #178：只统计 RuntimePaths.periodCacheDirectoryURL（summaries/），config.json / menu-bar.log
        // 放在 root 下与 summaries 平级，调用方必须只传 summaries 目录进来，本测试锁住「只算传入目录」。
        let root = tempDir.deletingLastPathComponent()
        let siblingLog = tempDir.appendingPathComponent("../sibling-\(UUID().uuidString).log")
        try Data(repeating: 0, count: 999).write(to: siblingLog)
        defer { try? FileManager.default.removeItem(at: siblingLog) }
        _ = root

        try Data(repeating: 0, count: 10).write(to: tempDir.appendingPathComponent("only.json"))

        XCTAssertEqual(CacheDirectorySize.compute(at: tempDir), 10)
    }
}
