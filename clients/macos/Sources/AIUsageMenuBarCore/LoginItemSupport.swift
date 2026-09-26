import Foundation

/// #178：SMAppService.mainApp 只在应用以真正的 .app bundle 运行时可用；
/// `swift run` / 单元测试环境下 `Bundle.main.bundleURL` 不是 .app，登录项菜单项必须置灰。
public enum LoginItemSupport {
    public static func isSupported(bundleURL: URL?) -> Bool {
        guard let bundleURL else { return false }
        return bundleURL.pathExtension.lowercased() == "app"
    }
}
