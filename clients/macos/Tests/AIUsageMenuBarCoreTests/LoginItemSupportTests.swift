import XCTest
@testable import AIUsageMenuBarCore

final class LoginItemSupportTests: XCTestCase {
    func testSupportedForAppBundle() {
        let url = URL(fileURLWithPath: "/Applications/AI Usage Menu Bar.app", isDirectory: true)
        XCTAssertTrue(LoginItemSupport.isSupported(bundleURL: url))
    }

    func testNotSupportedWhenBundleURLIsNil() {
        XCTAssertFalse(LoginItemSupport.isSupported(bundleURL: nil))
    }

    func testNotSupportedForNonAppBundle() {
        // swift run / 测试环境下 Bundle.main.bundleURL 通常是可执行文件本身或 .build 目录，不是 .app。
        let url = URL(fileURLWithPath: "/Users/dev/repo/.build/debug/AIUsageMenuBar", isDirectory: false)
        XCTAssertFalse(LoginItemSupport.isSupported(bundleURL: url))
    }
}
