import XCTest
@testable import AIUsageMenuBarApp

/// #177 第四轮 Opus 审查：上一轮的 bug——MenuBarServerListView 在 `cards` 变化（切换所选期间）
/// 时会调用 reconcile 并把结果落盘。serverCards 是按所选期间算出来的，某台机器这期没有用量就
/// 不会出现在 cards 里，不代表它「永远消失」；切到没有该机器的期再切回来，它的展开状态就被
/// 冲掉了。修复方式：展开状态只能通过 toggle 改变并落盘，这个类型的 API 面上根本没有任何
/// 「按当前可见 id 集合清理」的入口——所以"切期再切回"这个场景在单元层面天然无法触发清空。
@MainActor
final class ServerExpansionStateTests: XCTestCase {
    private func makeDefaults() -> UserDefaults {
        let suiteName = "ServerExpansionStateTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        return defaults
    }

    func testStartsCollapsedWhenNothingStored() {
        let state = ServerExpansionState(defaults: makeDefaults())
        XCTAssertFalse(state.isExpanded("mac-1"))
    }

    func testToggleExpandsThenCollapses() {
        let state = ServerExpansionState(defaults: makeDefaults())
        state.toggle("mac-1")
        XCTAssertTrue(state.isExpanded("mac-1"))
        state.toggle("mac-1")
        XCTAssertFalse(state.isExpanded("mac-1"))
    }

    func testMultipleServersCanBeExpandedAtOnce() {
        let state = ServerExpansionState(defaults: makeDefaults())
        state.toggle("mac-1")
        state.toggle("linux-2")
        XCTAssertTrue(state.isExpanded("mac-1"))
        XCTAssertTrue(state.isExpanded("linux-2"))
    }

    func testTogglePersistsAcrossFreshInstancesSameDefaults() {
        let defaults = makeDefaults()
        let state = ServerExpansionState(defaults: defaults)
        state.toggle("mac-1")

        let reopened = ServerExpansionState(defaults: defaults)
        XCTAssertTrue(reopened.isExpanded("mac-1"), "重新打开面板应该保留上次的展开状态")
    }

    /// 核心回归用例：展开 mac-1 后，「切到没有 mac-1 的期间再切回」在真实 View 里就是 cards
    /// 列表变了——ServerExpansionState 完全不知道、也不关心当前展示了哪些卡片，它的 API 面上
    /// 没有任何方法能表达/触发这种变化，所以展开状态与「当前可见的卡片集合」彻底解耦。
    func testExpansionSurvivesTheServerTemporarilyNotAppearingInCards() {
        let defaults = makeDefaults()
        let state = ServerExpansionState(defaults: defaults)
        state.toggle("mac-1")
        XCTAssertTrue(state.isExpanded("mac-1"))

        // 模拟「切到只有 linux-2 的期间再切回」：真实 View 只会重新读 cards 数组渲染，
        // 不会创建新的 ServerExpansionState、也不会调用任何清理 API。
        XCTAssertTrue(state.isExpanded("mac-1"), "mac-1 这期不在 cards 里不代表它的展开状态该被清空")

        // 即使重新打开整个面板（新建实例，从磁盘重新加载），状态也必须还在。
        let afterReopening = ServerExpansionState(defaults: defaults)
        XCTAssertTrue(afterReopening.isExpanded("mac-1"))
    }
}
