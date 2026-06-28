import AppKit
import AIUsageMenuBarCore
import Combine
import SwiftUI

@MainActor
enum MenuBarStatusItemPresentation {
    static let autosaveName = "com.chunbai.aiusage.menubar.status.numeric.v3"

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

    init(paths: RuntimePaths, quitApplication: @escaping () -> Void = { NSApp.terminate(nil) }) {
        self.paths = paths
        self.quitApplication = quitApplication
        let config = MenuBarRuntimeConfigLoader.load(paths: paths)
        let cached = SummaryCache.load(from: paths.cacheURL)
        let cachedSummaries = SummaryCache.loadSummaries(paths: paths)
        self.model = MenuBarAppModel(paths: paths, config: config, cachedSummary: cached, cachedSummaries: cachedSummaries)
        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        super.init()
        setupStatusItem()
        setupPopover()
        bindStatusTitle()
        startRefreshTimer()
        model.refresh()
    }

    private func setupStatusItem() {
        statusItem.autosaveName = MenuBarStatusItemPresentation.autosaveName
        guard let button = statusItem.button else {
            return
        }
        button.image = nil
        button.imagePosition = .noImage
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
        popover.contentSize = NSSize(width: 320, height: 520)
        popover.contentViewController = NSHostingController(
            rootView: MenuBarPopoverView(model: model, onQuit: { [weak self] in
                self?.quitFromPopover()
            })
            .frame(width: 320, height: 520)
        )
    }

    func quitFromPopover() {
        quitApplication()
    }

    private func bindStatusTitle() {
        model.$summary
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
        button.title = MenuBarStatusItemPresentation.title(for: model.state)
        button.toolTip = MenuBarStatusItemPresentation.tooltip(for: model.state)
    }

    private func startRefreshTimer() {
        guard let interval = model.config?.refreshIntervalSeconds else {
            return
        }
        timer = Timer.scheduledTimer(withTimeInterval: interval, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.model.refresh()
            }
        }
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
            popover.contentViewController?.view.window?.makeKey()
        }
    }
}
