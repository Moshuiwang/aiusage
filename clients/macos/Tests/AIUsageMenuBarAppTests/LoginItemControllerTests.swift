import XCTest
@testable import AIUsageMenuBarApp

final class LoginItemControllerTests: XCTestCase {
    private final class FakeLoginItemManaging: LoginItemManaging {
        var status: LoginItemStatus
        var registerCallCount = 0
        var unregisterCallCount = 0
        var registerError: Error?
        var unregisterError: Error?

        init(status: LoginItemStatus) { self.status = status }

        func register() throws {
            registerCallCount += 1
            if let registerError { throw registerError }
            status = .enabled
        }

        func unregister() throws {
            unregisterCallCount += 1
            if let unregisterError { throw unregisterError }
            status = .disabled
        }
    }

    private struct StubError: Error {}

    func testNeedsApprovalOnlyWhenSystemRequiresApproval() {
        XCTAssertTrue(LoginItemController(manager: FakeLoginItemManaging(status: .requiresApproval)).needsApproval)
        XCTAssertFalse(LoginItemController(manager: FakeLoginItemManaging(status: .enabled)).needsApproval)
        XCTAssertFalse(LoginItemController(manager: FakeLoginItemManaging(status: .disabled)).needsApproval)
    }

    func testIsCheckedReflectsEnabledStatus() {
        let fake = FakeLoginItemManaging(status: .enabled)
        let controller = LoginItemController(manager: fake)
        XCTAssertTrue(controller.isChecked)

        fake.status = .disabled
        XCTAssertFalse(controller.isChecked)
    }

    func testToggleFromDisabledRegisters() throws {
        let fake = FakeLoginItemManaging(status: .disabled)
        let controller = LoginItemController(manager: fake)

        try controller.toggle()

        XCTAssertEqual(fake.registerCallCount, 1)
        XCTAssertEqual(fake.unregisterCallCount, 0)
        XCTAssertTrue(controller.isChecked)
    }

    func testToggleFromEnabledUnregisters() throws {
        let fake = FakeLoginItemManaging(status: .enabled)
        let controller = LoginItemController(manager: fake)

        try controller.toggle()

        XCTAssertEqual(fake.unregisterCallCount, 1)
        XCTAssertEqual(fake.registerCallCount, 0)
        XCTAssertFalse(controller.isChecked)
    }

    func testToggleFailurePropagatesAndLeavesStatusUnchanged() {
        let fake = FakeLoginItemManaging(status: .disabled)
        fake.registerError = StubError()
        let controller = LoginItemController(manager: fake)

        XCTAssertThrowsError(try controller.toggle())
        XCTAssertEqual(fake.registerCallCount, 1)
        // 注册失败：manager 内部状态没被我们的 fake 改到 enabled（真实 SMAppService 失败也不会切到 enabled）。
        XCTAssertFalse(controller.isChecked)
    }
}
