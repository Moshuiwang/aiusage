import AppKit
import XCTest
@testable import AIUsageMenuBarApp

final class MoreMenuBuilderTests: XCTestCase {
    private final class FakeTarget: NSObject {
        @objc func sync() {}
        @objc func toggleLoginItem() {}
        @objc func quit() {}
    }

    func testExactItemListAndOrder() {
        let target = FakeTarget()
        let menu = MoreMenuBuilder.build(
            info: ["版本 2.0.0 (293 · 6694a5f)", "本地缓存 404 KB", "同步源 3 个 · 2 个在线"],
            isLoginItemChecked: false,
            isLoginItemSupported: true,
            target: target,
            syncAction: #selector(FakeTarget.sync),
            loginItemAction: #selector(FakeTarget.toggleLoginItem),
            quitAction: #selector(FakeTarget.quit)
        )

        // 结构下限：恰好 8 项，顺序固定；这条断言同时守住「不包含打开完整面板/检查更新/设置/在 Finder 中显示」——
        // 这四个功能被明确排除在 #178 范围外，多加任何一项都会让 count 或 titles 不匹配而变红。
        XCTAssertEqual(menu.items.count, 8)
        XCTAssertEqual(
            menu.items.map(\.title),
            [
                "版本 2.0.0 (293 · 6694a5f)",
                "本地缓存 404 KB",
                "同步源 3 个 · 2 个在线",
                "",
                "立即同步",
                "登录时启动",
                "",
                "完全退出 AI Usage",
            ]
        )
    }

    func testInfoRowsAreDisabledAndNotCheckable() {
        let target = FakeTarget()
        let menu = MoreMenuBuilder.build(
            info: ["版本 2.0.0 (293)", "本地缓存 0 KB", "同步源 0 个 · 0 个在线"],
            isLoginItemChecked: false,
            isLoginItemSupported: true,
            target: target,
            syncAction: #selector(FakeTarget.sync),
            loginItemAction: #selector(FakeTarget.toggleLoginItem),
            quitAction: #selector(FakeTarget.quit)
        )

        for item in menu.items[0...2] {
            XCTAssertFalse(item.isEnabled, "信息行必须是禁用项：\(item.title)")
        }
        XCTAssertTrue(menu.items[3].isSeparatorItem)
        XCTAssertTrue(menu.items[6].isSeparatorItem)
    }

    func testSyncItemHasCommandRShortcutAndIsWiredToTarget() {
        let target = FakeTarget()
        let menu = MoreMenuBuilder.build(
            info: ["v", "c", "s"],
            isLoginItemChecked: false,
            isLoginItemSupported: true,
            target: target,
            syncAction: #selector(FakeTarget.sync),
            loginItemAction: #selector(FakeTarget.toggleLoginItem),
            quitAction: #selector(FakeTarget.quit)
        )

        let syncItem = menu.items[4]
        XCTAssertEqual(syncItem.keyEquivalent, "r")
        XCTAssertEqual(syncItem.keyEquivalentModifierMask, [.command])
        XCTAssertTrue(syncItem.target === target)
        XCTAssertEqual(syncItem.action, #selector(FakeTarget.sync))
        XCTAssertTrue(syncItem.isEnabled)
    }

    func testQuitItemHasCommandQShortcutAndIsWiredToTarget() {
        let target = FakeTarget()
        let menu = MoreMenuBuilder.build(
            info: ["v", "c", "s"],
            isLoginItemChecked: false,
            isLoginItemSupported: true,
            target: target,
            syncAction: #selector(FakeTarget.sync),
            loginItemAction: #selector(FakeTarget.toggleLoginItem),
            quitAction: #selector(FakeTarget.quit)
        )

        let quitItem = menu.items[7]
        XCTAssertEqual(quitItem.keyEquivalent, "q")
        XCTAssertEqual(quitItem.keyEquivalentModifierMask, [.command])
        XCTAssertTrue(quitItem.target === target)
        XCTAssertEqual(quitItem.action, #selector(FakeTarget.quit))
    }

    func testLoginItemReflectsCheckedStateAndSupportGating() {
        let target = FakeTarget()
        let checkedMenu = MoreMenuBuilder.build(
            info: ["v", "c", "s"],
            isLoginItemChecked: true,
            isLoginItemSupported: true,
            target: target,
            syncAction: #selector(FakeTarget.sync),
            loginItemAction: #selector(FakeTarget.toggleLoginItem),
            quitAction: #selector(FakeTarget.quit)
        )
        XCTAssertEqual(checkedMenu.items[5].state, .on)
        XCTAssertTrue(checkedMenu.items[5].isEnabled)

        let unsupportedMenu = MoreMenuBuilder.build(
            info: ["v", "c", "s"],
            isLoginItemChecked: false,
            isLoginItemSupported: false,
            target: target,
            syncAction: #selector(FakeTarget.sync),
            loginItemAction: #selector(FakeTarget.toggleLoginItem),
            quitAction: #selector(FakeTarget.quit)
        )
        // swift run / 测试环境下 Bundle.main.bundleURL 不是 .app：登录项必须置灰，不能让用户点出一个必然失败的操作。
        XCTAssertFalse(unsupportedMenu.items[5].isEnabled)
        XCTAssertEqual(unsupportedMenu.items[5].state, .off)
    }
}
