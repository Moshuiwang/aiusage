import AppKit
import ServiceManagement
import AIUsageMenuBarCore
import Combine
import SwiftUI

enum MenuBarPopoverLayout {
    /// #177：Popover v2 定稿宽度（HANDOFF.md 第 3 节），从旧版 380pt 收窄到设计值 360pt。
    static let width: CGFloat = 360
    static let bottomMargin: CGFloat = 48

    static func maxContentHeight(screenHeight: CGFloat?) -> CGFloat {
        let baseHeight = screenHeight ?? 800
        return max(320, baseHeight - bottomMargin)
    }

    /// Popover 内容的 hosting controller：交给系统按 SwiftUI 理想尺寸维护 preferredContentSize。
    @MainActor
    static func makeHostingController(rootView: MenuBarPopoverView) -> NSHostingController<MenuBarPopoverView> {
        let hostingController = NSHostingController(rootView: rootView)
        hostingController.sizingOptions = [.preferredContentSize]
        return hostingController
    }

    /// #177 第三轮真机反馈：展开 Server 卡片会改变内容高度，进而改变
    /// `NSHostingController.preferredContentSize`。`NSPopover.animates` 默认 true，
    /// AppKit 会对这个尺寸变化做窗口级动画——动画期间会反复用中间尺寸向 SwiftUI 请求
    /// relayout，相当于把整棵内容树（图表、额度环、全部 Server 卡片）在几百毫秒内重算好几遍，
    /// 这就是真机上「展开非常慢」的根因。展开这类交互不需要弹窗级动画，直接关掉。
    @MainActor
    static func configure(_ popover: NSPopover) {
        popover.behavior = .transient
        popover.animates = false
    }
}

@MainActor
enum MenuBarStatusItemPresentation {
    static let autosaveName = "com.chunbai.aiusage.menubar.status.numeric.v3"
    static let behavior: NSStatusItem.Behavior = .removalAllowed

    static func title(for state: MenuBarState) -> String {
        state.statusTitle
    }

    static func tooltip(for state: MenuBarState) -> String {
        "AI Usage · \(state.periodLabel)\(state.periodTitleSuffix) \(state.statusTitle)"
    }
}

@MainActor
final class StatusBarController: NSObject {
    private let statusItem: NSStatusItem
    private let popover = NSPopover()
    private let model: MenuBarAppModel
    private let paths: RuntimePaths
    private let quitApplication: () -> Void
    private var cancellables: Set<AnyCancellable> = []
    private var timer: Timer?
    private let collector: CollectorController
    private var popoverHostingController: NSHostingController<MenuBarPopoverView>?
    private lazy var loginItemController = LoginItemController(manager: SMAppServiceLoginItemManager())

    init(paths: RuntimePaths, quitApplication: @escaping () -> Void = { NSApp.terminate(nil) }) {
        self.paths = paths
        self.collector = CollectorController(root: paths.root)
        self.quitApplication = quitApplication
        let config = MenuBarRuntimeConfigLoader.load(paths: paths)
        let cachedSummaries = SummaryCache.loadSummaries(paths: paths)
        self.model = MenuBarAppModel(paths: paths, config: config, cachedSummaries: cachedSummaries)
        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        super.init()
        setupStatusItem()
        setupPopover()
        bindStatusTitle()
        startRefreshTimer()
        model.refresh()
        if model.selection != MenuPeriodSelection(periodID: "today") { model.refreshToday() }
        model.prefetchCommonPeriods()
        collector.start()
        if config == nil {
            DispatchQueue.main.async { [weak self] in self?.configureConnection() }
        }
    }

    private func setupStatusItem() {
        statusItem.autosaveName = MenuBarStatusItemPresentation.autosaveName
        statusItem.behavior = MenuBarStatusItemPresentation.behavior
        statusItem.isVisible = true
        guard let button = statusItem.button else {
            return
        }
        button.image = nil
        button.title = "AI"
        button.font = NSFont.monospacedDigitSystemFont(ofSize: NSFont.systemFontSize, weight: .semibold)
        button.toolTip = "AI Usage"
        button.setAccessibilityLabel("AI Usage")
        button.target = self
        button.action = #selector(togglePopover(_:))
        button.sendAction(on: [.leftMouseUp, .rightMouseUp])
    }

    private func setupPopover() {
        MenuBarPopoverLayout.configure(popover)
        let hostingController = MenuBarPopoverLayout.makeHostingController(
            rootView: MenuBarPopoverView(model: model, onQuit: { [weak self] in
                self?.quitFromPopover()
            }, onMore: { [weak self] in
                self?.showMoreMenu()
            })
        )
        hostingController.view.wantsLayer = true
        hostingController.view.layer?.backgroundColor = NSColor.clear.cgColor
        popoverHostingController = hostingController
        popover.contentViewController = hostingController
    }

    func quitFromPopover() {
        collector.stop()
        quitApplication()
    }

    func stopCollector() { collector.stop() }

    func enableLoginItem() {
        guard LoginItemSupport.isSupported(bundleURL: Bundle.main.bundleURL) else { return }
        do {
            if !loginItemController.isChecked { try loginItemController.toggle() }
            AppRuntimeLog.append("loginItemRegistered approvalRequired=\(loginItemController.needsApproval)", paths: paths)
            if loginItemController.needsApproval { SMAppService.openSystemSettingsLoginItems() }
        } catch {
            AppRuntimeLog.append("loginItem registration failed", paths: paths)
        }
    }

    private func bindStatusTitle() {
        model.$todaySummary
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                self?.updateStatusItemPresentation()
            }
            .store(in: &cancellables)

        model.$selectedPeriodID
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                self?.updateStatusItemPresentation()
            }
            .store(in: &cancellables)
    }

    private func updateStatusItemPresentation() {
        guard let button = statusItem.button else {
            return
        }
        button.imagePosition = .noImage
        button.title = model.todaySummary == nil ? "—" : MenuBarStatusItemPresentation.title(for: model.statusState)
        button.toolTip = model.todaySummary == nil ? "AI Usage · 今日用量待加载" : MenuBarStatusItemPresentation.tooltip(for: model.statusState)
    }

    private func startRefreshTimer() {
        guard let interval = model.config?.refreshIntervalSeconds else {
            return
        }
        timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                // #191（PR #191 Codex 审查 P1）：syncNow() 对非 today 的当前选中期无条件强刷，
                // 面板停在 week/month 会绕过 #190 的预取节流；定时器改用 timerTick()，手动
                // 「立即同步」按钮/菜单仍用 syncNow()，行为不变。
                self.model.timerTick()
            }
        }
    }

    private func configurePopoverWindow() {
        guard let window = popover.contentViewController?.view.window else {
            return
        }
        window.isOpaque = false
        window.backgroundColor = .clear
    }

    // MARK: – 更多菜单（#178）

    private func showMoreMenu() {
        var info = MoreMenuInfo.build(
            sources: model.summary.sources,
            cacheBytes: CacheDirectorySize.compute(at: paths.periodCacheDirectoryURL),
            versionText: currentVersionText()
        )
        info.append(collector.statusText)
        let bundleURL = Bundle.main.bundleURL
        let isSupported = LoginItemSupport.isSupported(bundleURL: bundleURL)
        let menu = MoreMenuBuilder.build(
            info: info,
            isLoginItemChecked: isSupported && loginItemController.isChecked,
            isLoginItemSupported: isSupported,
            target: self,
            syncAction: #selector(syncFromMoreMenu),
            loginItemAction: #selector(toggleLoginItemFromMoreMenu),
            quitAction: #selector(quitFromMoreMenuAction)
        )
        let updateItem = NSMenuItem(title: "检查 App 更新…", action: #selector(checkUpdates), keyEquivalent: "")
        updateItem.target = self
        menu.addItem(updateItem)
        let devicesItem = NSMenuItem(title: "管理设备申请…", action: #selector(manageEnrollments), keyEquivalent: "")
        devicesItem.target = self
        menu.addItem(devicesItem)
        let pairingItem = NSMenuItem(title: "检查本机授权", action: #selector(checkEnrollment), keyEquivalent: "")
        pairingItem.target = self
        pairingItem.isEnabled = FileManager.default.fileExists(atPath: collector.store.enrollmentURL.path)
        menu.addItem(pairingItem)
        let settingsItem = NSMenuItem(title: "连接设置…", action: #selector(configureConnection), keyEquivalent: "")
        settingsItem.target = self
        menu.insertItem(settingsItem, at: info.count + 2)
        let collectItem = NSMenuItem(title: "立即采集本机", action: #selector(collectNow), keyEquivalent: "")
        collectItem.target = self
        collectItem.isEnabled = collector.store.isEnabled
        menu.insertItem(collectItem, at: info.count + 3)
        let toggleItem = NSMenuItem(title: "采集本机用量与额度", action: #selector(toggleCollection), keyEquivalent: "")
        toggleItem.target = self
        toggleItem.state = collector.store.isEnabled ? .on : .off
        toggleItem.isEnabled = collector.store.sourceID != nil
        menu.insertItem(toggleItem, at: info.count + 4)
        // 从「⋯」按钮所在位置弹出：popUp(in: nil) 把 at 当成屏幕坐标，用当前鼠标位置
        // （用户刚点了按钮）近似按钮位置——真实弹出坐标/视觉效果需回 Mac 侧截图确认。
        menu.popUp(positioning: nil, at: NSEvent.mouseLocation, in: nil)
    }

    private func currentVersionText() -> String {
        let info = Bundle.main.infoDictionary
        return AppVersionText.make(
            shortVersion: info?["CFBundleShortVersionString"] as? String,
            build: info?["CFBundleVersion"] as? String,
            commit: info?["AIUsageGitCommit"] as? String
        )
    }

    @objc private func syncFromMoreMenu() {
        model.syncNow()
    }

    @objc private func checkUpdates() { collector.checkUpdates() }
    @objc private func manageEnrollments() { collector.manageEnrollments() }
    @objc private func checkEnrollment() {
        collector.checkEnrollment { [weak self] in
            self?.enableLoginItem()
            self?.model.syncNow()
        }
    }
    @objc private func collectNow() { collector.collectNow() }
    @objc private func toggleCollection() { collector.toggle() }
    @objc private func configureConnection() {
        if collector.configure() {
            if collector.wantsLoginItem { enableLoginItem() }
            model.syncNow()
            timer?.invalidate()
            startRefreshTimer()
        }
    }

    @objc private func toggleLoginItemFromMoreMenu() {
        do {
            try loginItemController.toggle()
            // 首次注册常处于「需要批准」，直接带用户去系统设置的登录项页面完成批准。
            if loginItemController.needsApproval {
                SMAppService.openSystemSettingsLoginItems()
            }
        } catch {
            AppRuntimeLog.append("loginItem toggle failed: \(error)", paths: paths)
            let alert = NSAlert()
            alert.alertStyle = .warning
            alert.messageText = "登录时启动设置失败"
            alert.informativeText = error.localizedDescription
            NSApp.activate(ignoringOtherApps: true)
            alert.runModal()
        }
    }

    @objc private func quitFromMoreMenuAction() {
        quitFromPopover()
    }

    @objc private func togglePopover(_ sender: Any?) {
        AppRuntimeLog.append("togglePopover isShown=\(popover.isShown)", paths: paths)
        guard let button = statusItem.button else {
            return
        }
        if popover.isShown {
            popover.performClose(sender)
        } else {
            model.refresh()
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            configurePopoverWindow()
            popover.contentViewController?.view.window?.makeKey()
        }
    }
}
