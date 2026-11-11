import AppKit
import SwiftUI
import XCTest
@testable import AIUsageMenuBarCore
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

    func testThreeQuotaRingsWithAccountLabelsDoNotOverflowPopoverWidth() {
        _ = NSApplication.shared
        func makeRing(id: String, name: String, account: String?, pct: String, countdown: String) -> QuotaRingData {
            QuotaRingData(
                id: id,
                displayName: name,
                accountText: account,
                primaryFraction: 0.5,
                outerPctText: "--",
                innerPctText: pct,
                outerTimeText: "--",
                innerTimeText: countdown,
                outerLabel: "5h",
                innerLabel: "7d",
                updatedText: "11:16 更新",
                availabilityText: "",
                brandColor: AgentBranding.color(for: id),
                primaryPctText: pct,
                primaryPctNumberText: String(pct.dropLast()),
                resetCountdownText: countdown,
                isAvailable: true,
                hoverRows: []
            )
        }
        let twoRings = [
            makeRing(id: "claude", name: "Claude", account: "Zhipeng · Max 5x", pct: "48%", countdown: "3d 7h"),
            makeRing(id: "codex", name: "Codex", account: "Moshu · Prolite", pct: "83%", countdown: "3d 8h"),
        ]
        let threeRings = twoRings + [
            makeRing(id: "antigravity", name: "Antigravity", account: nil, pct: "51%", countdown: "6d 21h"),
        ]
        let twoView = NSHostingView(
            rootView: MenuBarQuotaSectionView(rings: twoRings)
                .padding(.horizontal, 10)
        )
        twoView.frame = NSRect(x: 0, y: 0, width: MenuBarPopoverLayout.width, height: 200)
        twoView.layoutSubtreeIfNeeded()

        let threeView = NSHostingView(
            rootView: MenuBarQuotaSectionView(rings: threeRings)
                .padding(.horizontal, 10)
        )
        threeView.frame = NSRect(x: 0, y: 0, width: MenuBarPopoverLayout.width, height: 200)
        threeView.layoutSubtreeIfNeeded()

        XCTAssertLessThanOrEqual(
            threeView.fittingSize.width,
            MenuBarPopoverLayout.width,
            "Three quota rings with account labels must not overflow the 360pt popover width"
        )
        XCTAssertGreaterThan(
            threeView.fittingSize.height,
            twoView.fittingSize.height + 24,
            "Three quota rings must wrap to a second row in the 2-column grid"
        )
    }
}
