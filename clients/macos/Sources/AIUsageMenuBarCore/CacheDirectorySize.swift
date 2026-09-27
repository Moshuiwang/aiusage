import Foundation

/// #178：「更多」菜单信息区第二行——统计菜单栏本地缓存目录大小。
/// 调用方必须只传 `RuntimePaths.periodCacheDirectoryURL`（summaries/），
/// 不含 config.json / menu-bar.log（用户关心的是缓存数据，不是配置/日志）。
public enum CacheDirectorySize {
    public static func compute(at url: URL) -> Int64 {
        let fileManager = FileManager.default
        var isDirectory: ObjCBool = false
        guard fileManager.fileExists(atPath: url.path, isDirectory: &isDirectory), isDirectory.boolValue else {
            return 0
        }
        guard let enumerator = fileManager.enumerator(
            at: url,
            includingPropertiesForKeys: [.isRegularFileKey, .fileSizeKey],
            options: [],
            errorHandler: nil
        ) else {
            return 0
        }

        var total: Int64 = 0
        for item in enumerator {
            guard let fileURL = item as? URL else { continue }
            let values = try? fileURL.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
            guard values?.isRegularFile == true else { continue }
            total += Int64(values?.fileSize ?? 0)
        }
        return total
    }
}
