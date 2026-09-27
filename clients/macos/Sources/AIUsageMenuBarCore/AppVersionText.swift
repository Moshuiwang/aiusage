import Foundation

/// #178：「更多」菜单信息区第一行——版本号 + 构建号 + git commit，供 App 层拼装
/// `Bundle.main.infoDictionary` 后调用；纯函数便于离线测试，不依赖 Bundle。
public enum AppVersionText {
    public static func make(shortVersion: String?, build: String?, commit: String?) -> String {
        guard let shortVersion, !shortVersion.isEmpty else {
            return "版本 未知"
        }
        let trimmedBuild = build?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let trimmedCommit = commit?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !trimmedBuild.isEmpty else {
            return "版本 \(shortVersion)"
        }
        if trimmedCommit.isEmpty {
            return "版本 \(shortVersion) (\(trimmedBuild))"
        }
        return "版本 \(shortVersion) (\(trimmedBuild) · \(trimmedCommit))"
    }
}
