import AppKit
import SwiftUI
import XCTest
import AIUsageMenuBarCore
@testable import AIUsageMenuBarApp

@MainActor
final class ServerCardLayoutTests: XCTestCase {
    func testLongModelNameWrapsInsteadOfDroppingVisibleContent() {
        _ = NSApplication.shared
        let suite = "aiusage.layout-test.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        ExpandedServersStore.save(["preview"], to: defaults)
        func height(_ label: String) -> CGFloat {
            let model = MenuServerModelRow(id: "model", modelID: "model", agentID: "claude", agentDisplayName: "Claude",
                agentBrandColor: AgentBranding.color(for: "claude"), modelLabel: label, tokens: 1,
                valueText: "675.7M", status: "available", quotaText: "≈<0.1%", quotaHelpText: "参考")
            let card = MenuServerCard(id: "preview", title: "Mac mini", platform: "darwin", subtitle: "wangzhipeng · 同步",
                valueText: "756.3M", sharePercentText: "100%", isOnline: true, models: [model])
            let view = NSHostingView(rootView: MenuBarServerListView(cards: [card], defaults: defaults).frame(width: 340))
            view.frame = NSRect(x: 0, y: 0, width: 340, height: 400)
            view.layoutSubtreeIfNeeded()
            return view.fittingSize.height
        }
        let compact = height("opus")
        let full = height("claude-opus-5-5-long-version-and-very-long-model-name")
        XCTAssertGreaterThan(compact, 0)
        XCTAssertGreaterThan(full, compact + 10, "Long names must wrap, not be truncated into the compact row height")
    }
}
