import AppKit
import AIUsageMenuBarCore
import Combine
import SwiftUI

enum MenuBarPopoverLayout {
    static let width: CGFloat = 380
    static let bottomMargin: CGFloat = 48
    static let minContentHeight: CGFloat = 200

    static func maxContentHeight(screenHeight: CGFloat?) -> CGFloat {
        let baseHeight = screenHeight ?? 800
        return max(320, baseHeight - bottomMargin)
    }

    static func size(contentHeight: CGFloat, screenHeight: CGFloat? = nil) -> NSSize {
        let maxHeight = maxContentHeight(screenHeight: screenHeight)
        let clampedHeight = min(max(contentHeight, 1), maxHeight)
        return NSSize(width: width, height: clampedHeight)
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
        "AI Usage · \(state.periodLabel) \(state.statusTitle)"
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
    private var popoverHostingController: NSHostingController<MenuBarPopoverView>?

    init(paths: RuntimePaths, quitApplication: @escaping () -> Void = { NSApp.terminate(nil) }) {
        self.paths = paths
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
        popover.behavior = .transient
        let hostingController = NSHostingController(
            rootView: MenuBarPopoverView(model: model, onQuit: { [weak self] in
                self?.quitFromPopover()
            }, onContentHeightChange: { [weak self] in
                self?.updatePopoverSize()
            })
        )
        hostingController.view.wantsLayer = true
        hostingController.view.layer?.backgroundColor = NSColor.clear.cgColor
        popoverHostingController = hostingController
        popover.contentViewController = hostingController
        updatePopoverSize()
    }

    func quitFromPopover() {
        quitApplication()
    }

    private func bindStatusTitle() {
        model.$todaySummary
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                self?.updateStatusItemPresentation()
            }
            .store(in: &cancellables)

        model.objectWillChange
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in
                DispatchQueue.main.async {
                    self?.updatePopoverSize()
                }
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
                if self.model.selection != MenuPeriodSelection(periodID: "today") { self.model.refresh(force: true) }
                self.model.refreshToday()
                self.model.prefetchCommonPeriods()
            }
        }
    }

    private func updatePopoverSize() {
        guard let hostingController = popoverHostingController else {
            return
        }
        hostingController.loadViewIfNeeded()
        hostingController.view.frame.size.width = MenuBarPopoverLayout.width
        hostingController.view.layoutSubtreeIfNeeded()
        let fittingHeight = hostingController.view.fittingSize.height
        let screenHeight = hostingController.view.window?.screen?.visibleFrame.height ?? NSScreen.main?.visibleFrame.height
        let size = MenuBarPopoverLayout.size(contentHeight: fittingHeight, screenHeight: screenHeight)
        hostingController.view.setFrameSize(size)
        popover.contentSize = size
    }

    private func configurePopoverWindow() {
        guard let window = popover.contentViewController?.view.window else {
            return
        }
        window.isOpaque = false
        window.backgroundColor = .clear
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
            updatePopoverSize()
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            configurePopoverWindow()
            popover.contentViewController?.view.window?.makeKey()
        }
    }
}
