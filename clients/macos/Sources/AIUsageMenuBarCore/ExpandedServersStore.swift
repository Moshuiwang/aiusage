import Foundation

/// #177 第四轮真机反馈：Server 卡片展开状态跨次打开面板保持——展开的 server id 集合持久化到
/// UserDefaults；首次（无存量）默认全部收起。允许多张同时展开。
///
/// #177 第四轮 Opus 审查：故意不提供「按当前可见 server id 集合清理」的方法（原来的
/// `reconciled(_:existingServerIDs:)` 已删除）。serverCards 是按所选期间算出来的，某台机器这期
/// 没有用量就不会出现在卡片里，不代表它「永远消失」——上一轮实现在 cards 变化时调用过这个函数
/// 并回写，导致切到没有该机器的期间再切回来，它的展开状态就被冲掉了。也没有更安全的调用时机
/// （哪怕只在启动时调用一次也一样错，启动时的 summary 同样是某个期间的快照），所以直接删除，
/// 不留一个天生会被错误调用的 API；调用方（ServerExpansionState）只暴露 load/toggle+save。
public enum ExpandedServersStore {
    public static let defaultsKey = "serverExpandedIDs.v1"

    public static func load(from defaults: UserDefaults) -> Set<String> {
        guard let stored = defaults.array(forKey: defaultsKey) as? [String] else { return [] }
        return Set(stored)
    }

    public static func save(_ ids: Set<String>, to defaults: UserDefaults) {
        defaults.set(Array(ids), forKey: defaultsKey)
    }
}
