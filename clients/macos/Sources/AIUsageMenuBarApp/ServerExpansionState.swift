import AIUsageMenuBarCore
import Combine
import Foundation

/// #177 第四轮 Opus 审查：展开状态只能通过用户主动 toggle 改变并落盘——这个类型的 API 面上
/// 故意不提供任何「按当前可见 server id 集合清理/回写」的方法。上一轮的 bug 正是
/// MenuBarServerListView 在 `cards`（随所选期间变化）变化时调用了这样一个 reconcile 并回写：
/// serverCards 是按所选期间算出来的，某台机器这期没有用量就不会出现在 cards 里，不代表它
/// 「永远消失」——切到没有该机器的期间再切回来，它的展开状态就被冲掉了。没有更小粒度能安全
/// 触发这种清理的时机（哪怕只在启动时调用一次也一样错，因为启动时的 summary 同样是某个期间
/// 的快照），所以直接不提供这个能力：展开状态与「当前展示了哪些卡片」彻底解耦。
@MainActor
final class ServerExpansionState: ObservableObject {
    @Published private(set) var expandedIDs: Set<String>
    private let defaults: UserDefaults

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        self.expandedIDs = ExpandedServersStore.load(from: defaults)
    }

    func isExpanded(_ id: String) -> Bool {
        expandedIDs.contains(id)
    }

    func toggle(_ id: String) {
        if expandedIDs.contains(id) {
            expandedIDs.remove(id)
        } else {
            expandedIDs.insert(id)
        }
        ExpandedServersStore.save(expandedIDs, to: defaults)
    }
}
