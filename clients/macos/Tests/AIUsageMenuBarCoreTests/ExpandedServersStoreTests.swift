import XCTest
@testable import AIUsageMenuBarCore

/// #177 第四轮真机反馈：Server 卡片展开状态持久化——首次默认全部收起，
/// 之后展开的 server id 集合跨次打开面板保持。
///
/// #177 第四轮 Opus 审查：原来这里还有 `testReconciledDropsIDsNoLongerPresent` /
/// `testReconciledWithEmptyExistingSetDropsEverything` 两个测试，覆盖
/// `ExpandedServersStore.reconciled(_:existingServerIDs:)`——按「当前可见 server id 集合」
/// 清理已消失的 id。这两个测试和它们覆盖的函数本身都已删除：`reconciled` 的语义在 Server
/// 卡片场景下天生是错的——existingServerIDs 来自某个所选期间的卡片集合，是期间相关、瞬时的，
/// 不代表「这台机器永远消失了」。上一轮真机反馈的 bug 正是 View 在 cards（随所选期间变化）
/// 变化时调用了它并回写，导致切到没有该机器的期间再切回来，展开状态被冲掉。删除这个函数不留
/// 一个天生会被错误调用的 API；对应的回归测试搬到了 `ServerExpansionStateTests`（App 目标），
/// 在「展开状态与当前可见卡片集合彻底解耦」这个正确的抽象层面表达。
final class ExpandedServersStoreTests: XCTestCase {
    private func makeDefaults() -> UserDefaults {
        let suiteName = "ExpandedServersStoreTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        return defaults
    }

    func testLoadDefaultsToEmptySetWhenNothingStored() {
        let defaults = makeDefaults()
        XCTAssertEqual(ExpandedServersStore.load(from: defaults), [])
    }

    func testSaveThenLoadRoundTrips() {
        let defaults = makeDefaults()
        ExpandedServersStore.save(["mac-1", "linux-2"], to: defaults)
        XCTAssertEqual(ExpandedServersStore.load(from: defaults), ["mac-1", "linux-2"])
    }

    func testSaveOverwritesPreviousValue() {
        let defaults = makeDefaults()
        ExpandedServersStore.save(["a", "b"], to: defaults)
        ExpandedServersStore.save(["c"], to: defaults)
        XCTAssertEqual(ExpandedServersStore.load(from: defaults), ["c"])
    }
}
