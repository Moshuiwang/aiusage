import Foundation
import ServiceManagement

/// #178：把 SMAppService 包在协议后面，方便离线测试「登录时启动」菜单项的开关逻辑，
/// 不依赖真机的 Login Items 系统状态。
enum LoginItemStatus: Equatable {
    case enabled
    case disabled
    case requiresApproval
    case notSupported
}

protocol LoginItemManaging {
    var status: LoginItemStatus { get }
    func register() throws
    func unregister() throws
}

/// 真实实现：包一层 `SMAppService.mainApp`。只在 App 以真正的 .app bundle 运行时才有意义——
/// `swift run` / 单元测试环境下调用会抛错或行为未定义，调用方必须先用 `LoginItemSupport.isSupported`
/// 判断 `Bundle.main.bundleURL` 再决定是否启用这个入口。
final class SMAppServiceLoginItemManager: LoginItemManaging {
    var status: LoginItemStatus {
        switch SMAppService.mainApp.status {
        case .enabled:
            return .enabled
        case .requiresApproval:
            return .requiresApproval
        case .notRegistered, .notFound:
            return .disabled
        @unknown default:
            return .disabled
        }
    }

    func register() throws {
        try SMAppService.mainApp.register()
    }

    func unregister() throws {
        try SMAppService.mainApp.unregister()
    }
}

/// 菜单项只关心「勾选态」和「点一下切换」，把 enabled/requiresApproval 都视为「已勾选」——
/// requiresApproval 意味着用户已经注册但需要去系统设置批准，菜单上仍应显示为勾选，
/// 否则用户会以为点了没反应而反复点击、反复触发 register()。
final class LoginItemController {
    private let manager: LoginItemManaging

    init(manager: LoginItemManaging) {
        self.manager = manager
    }

    var isChecked: Bool {
        switch manager.status {
        case .enabled, .requiresApproval:
            return true
        case .disabled, .notSupported:
            return false
        }
    }

    var needsApproval: Bool {
        manager.status == .requiresApproval
    }

    func toggle() throws {
        if isChecked {
            try manager.unregister()
        } else {
            try manager.register()
        }
    }
}
