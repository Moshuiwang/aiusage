import XCTest
@testable import AIUsageMenuBarCore

final class UpgradeCheckMessageTests: XCTestCase {
    func test_current_release_is_not_reported_as_failure() {
        XCTAssertEqual(UpgradeCheckMessage.text(status: "up_to_date", errorType: nil), "当前已是最新可用版本")
    }

    func test_failure_categories_have_distinct_safe_messages() {
        let kinds = ["not_configured", "download_failed", "verification_failed", "private-detail"]
        let messages = kinds.map { UpgradeCheckMessage.text(status: "error", errorType: $0) }
        XCTAssertEqual(messages.count, 4)
        XCTAssertEqual(Set(messages).count, 4)
        XCTAssertEqual(messages[0], "更新服务尚未配置，请联系发布管理员")
        XCTAssertEqual(messages[1], "无法获取正式发布清单或产物，请检查网络及正式 Release")
        XCTAssertEqual(messages[2], "发布清单或产物校验失败，当前版本已保留")
        XCTAssertEqual(messages[3], "无法完成更新检查，请稍后重试")
        XCTAssertFalse(messages.joined().contains("private-detail"))
    }
}
