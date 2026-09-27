import AppKit

/// #178：Popover 右上角「⋯」弹出的原生 NSMenu。范围明确排除「打开完整面板 / 检查更新 / 设置 /
/// 在 Finder 中显示」——只有信息区（禁用）+ 立即同步 + 登录时启动 + 完全退出。
enum MoreMenuBuilder {
    static func build(
        info: [String],
        isLoginItemChecked: Bool,
        isLoginItemSupported: Bool,
        target: AnyObject,
        syncAction: Selector,
        loginItemAction: Selector,
        quitAction: Selector
    ) -> NSMenu {
        let menu = NSMenu()

        for line in info {
            let item = NSMenuItem(title: line, action: nil, keyEquivalent: "")
            item.isEnabled = false
            menu.addItem(item)
        }

        menu.addItem(.separator())

        let syncItem = NSMenuItem(title: "立即同步", action: syncAction, keyEquivalent: "r")
        syncItem.keyEquivalentModifierMask = [.command]
        syncItem.target = target
        menu.addItem(syncItem)

        let loginItem = NSMenuItem(title: "登录时启动", action: loginItemAction, keyEquivalent: "")
        loginItem.target = target
        loginItem.state = isLoginItemChecked ? .on : .off
        loginItem.isEnabled = isLoginItemSupported
        menu.addItem(loginItem)

        menu.addItem(.separator())

        let quitItem = NSMenuItem(title: "完全退出 AI Usage", action: quitAction, keyEquivalent: "q")
        quitItem.keyEquivalentModifierMask = [.command]
        quitItem.target = target
        menu.addItem(quitItem)

        return menu
    }
}
