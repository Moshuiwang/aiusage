import Foundation

/// #178：「更多」菜单顶部只读信息区——版本、本地缓存大小、同步源在线数。
public enum MoreMenuInfo {
    public static func build(sources: [MobileSource], cacheBytes: Int64, versionText: String) -> [String] {
        let total = sources.count
        let online = sources.filter { $0.status == "ok" }.count
        let formatter = ByteCountFormatter()
        formatter.countStyle = .file
        formatter.allowedUnits = [.useAll]
        let cacheText = formatter.string(fromByteCount: max(cacheBytes, 0))
        return [
            versionText,
            "本地缓存 \(cacheText)",
            "同步源 \(total) 个 · \(online) 个在线"
        ]
    }
}
