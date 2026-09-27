import XCTest
@testable import AIUsageMenuBarCore

final class AppVersionTextTests: XCTestCase {
    func testIncludesShortVersionBuildAndCommit() {
        let text = AppVersionText.make(shortVersion: "2.0.0", build: "293", commit: "6694a5f")
        XCTAssertEqual(text, "版本 2.0.0 (293 · 6694a5f)")
    }

    func testOmitsCommitWhenMissing() {
        let text = AppVersionText.make(shortVersion: "2.0.0", build: "293", commit: nil)
        XCTAssertEqual(text, "版本 2.0.0 (293)")
    }

    func testOmitsCommitWhenEmpty() {
        let text = AppVersionText.make(shortVersion: "2.0.0", build: "293", commit: "")
        XCTAssertEqual(text, "版本 2.0.0 (293)")
    }

    func testFallsBackToUnknownWhenEverythingMissing() {
        let text = AppVersionText.make(shortVersion: nil, build: nil, commit: nil)
        XCTAssertEqual(text, "版本 未知")
    }

    func testFallsBackToUnknownWhenShortVersionEmpty() {
        let text = AppVersionText.make(shortVersion: "", build: "293", commit: "6694a5f")
        XCTAssertEqual(text, "版本 未知")
    }
}
