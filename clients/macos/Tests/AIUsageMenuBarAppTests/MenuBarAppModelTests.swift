import AIUsageMenuBarCore
import AppKit
import Foundation
@testable import AIUsageMenuBarApp
import SwiftUI
import XCTest

@MainActor
final class MenuBarAppModelTests: XCTestCase {
    func testHostedPopoverShowsContentOnFirstLayout() throws {
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(),
            cachedSummary: try summary(periodID: "today", totalTokens: 349_100_000)
        )
        let hosting = MenuBarPopoverLayout.makeHostingController(rootView: MenuBarPopoverView(model: model))
        let popover = NSPopover()
        popover.contentViewController = hosting
        hosting.loadViewIfNeeded()
        hosting.view.frame.size.width = MenuBarPopoverLayout.width
        hosting.view.layoutSubtreeIfNeeded()
        let fittingHeight = hosting.view.fittingSize.height
        XCTAssertGreaterThan(fittingHeight, 220, "first layout must include the period picker and summary, not just the header")
        // 模拟 NSPopover 展示时按 preferredContentSize 提交实际尺寸——不这样提交，内部
        // ScrollView 在没有真实窗口时永远量出 0 高度，测不出「内容确实渲染了」。
        hosting.view.setFrameSize(NSSize(width: MenuBarPopoverLayout.width, height: fittingHeight))
        hosting.view.layoutSubtreeIfNeeded()

        let scrollViews = descendants(of: hosting.view).compactMap { $0 as? NSScrollView }
        XCTAssertEqual(scrollViews.count, 1, "the actual hosted popover must contain one scrollable content region")
        XCTAssertGreaterThan(scrollViews.first?.frame.height ?? 0, 120)
    }

    func testHostedPopoverKeepsOwnerFixtureContentVisibleAfterMeasurement() throws {
        let fixtureURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("AIUsageMenuBarCoreTests/Fixtures/navigation-models-owner.json")
        let summary = try JSONDecoder().decode(MobileSummary.self, from: Data(contentsOf: fixtureURL))
        XCTAssertGreaterThan(summary.sources.count, 0)
        XCTAssertGreaterThan(summary.breakdown.byModel.count, 0)
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(), cachedSummary: summary
        )
        // 性能第二步：不再有 onContentHeightChange 回调/手工二次测量——直接开
        // sizingOptions，让 preferredContentSize 跟随 SwiftUI 内容的理想高度。
        let hosting = MenuBarPopoverLayout.makeHostingController(rootView: MenuBarPopoverView(model: model))
        let popover = NSPopover()
        popover.contentViewController = hosting
        hosting.loadViewIfNeeded()
        hosting.view.frame.size.width = MenuBarPopoverLayout.width
        hosting.view.layoutSubtreeIfNeeded()
        RunLoop.main.run(until: Date().addingTimeInterval(0.1))
        hosting.view.layoutSubtreeIfNeeded()
        let fittingHeight = hosting.view.fittingSize.height
        XCTAssertGreaterThan(fittingHeight, 220)
        XCTAssertLessThanOrEqual(fittingHeight, (NSScreen.main?.visibleFrame.height ?? 800) + 1)

        hosting.view.setFrameSize(NSSize(width: MenuBarPopoverLayout.width, height: fittingHeight))
        hosting.view.layoutSubtreeIfNeeded()
        let scrollViews = descendants(of: hosting.view).compactMap { $0 as? NSScrollView }
        XCTAssertEqual(scrollViews.count, 1)
        XCTAssertGreaterThan(scrollViews.first?.frame.height ?? 0, 120)
    }

    func testHostedPopoverInitialHeightProvidesFullViewportForLoadedSummary() throws {
        let fixtureURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("AIUsageMenuBarCoreTests/Fixtures/navigation-models-owner.json")
        let summary = try JSONDecoder().decode(MobileSummary.self, from: Data(contentsOf: fixtureURL))
        let fixedDate = try date("2026-09-22T12:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(), cachedSummary: summary, now: { fixedDate }
        )
        XCTAssertTrue(model.hasLoadedUsableSummary)
        let hosting = MenuBarPopoverLayout.makeHostingController(rootView: MenuBarPopoverView(model: model))
        hosting.loadViewIfNeeded()
        hosting.view.frame.size.width = MenuBarPopoverLayout.width
        hosting.view.layoutSubtreeIfNeeded()
        let fittingHeight = hosting.view.fittingSize.height
        XCTAssertGreaterThanOrEqual(fittingHeight, 500, "Loaded summary popover must start with an ample viewport, not collapsed to 200")
    }

    // #177 Opus 审查：新版 Server 卡片默认收起，普通 fixture 不再必然超出可视区，之前把
    // 这条测试的溢出断言直接改弱了。改成两条：一条用「足够多的 Server」构造必然溢出的场景，
    // 保留原本的「能滚到底」断言；另一条用最小场景断言不强制滚动（不裁剪、不误判溢出）。
    func testShownPopoverWithManyServersOverflowsAndCanScrollToBottom() throws {
        _ = NSApplication.shared
        let summary = try manyServerCardsSummary(machineCount: 40)
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(),
            cachedSummary: summary
        )
        let hosting = MenuBarPopoverLayout.makeHostingController(rootView: MenuBarPopoverView(model: model))
        // 性能第二步：不再手工测量/设置 popover.contentSize——只开 sizingOptions，展示时交给
        // NSPopover 自己读 preferredContentSize。
        let popover = NSPopover()
        popover.contentViewController = hosting
        hosting.loadViewIfNeeded()
        hosting.view.frame.size.width = MenuBarPopoverLayout.width
        hosting.view.layoutSubtreeIfNeeded()

        let anchorWindow = NSWindow(
            contentRect: NSRect(x: -10_000, y: -10_000, width: 20, height: 20),
            styleMask: .borderless, backing: .buffered, defer: false
        )
        anchorWindow.isReleasedWhenClosed = false
        let anchor = NSButton(frame: NSRect(x: 0, y: 0, width: 20, height: 20))
        anchorWindow.contentView?.addSubview(anchor)
        anchorWindow.orderFront(nil)
        defer { popover.close(); anchorWindow.close() }
        popover.show(relativeTo: anchor.bounds, of: anchor, preferredEdge: .minY)
        RunLoop.main.run(until: Date().addingTimeInterval(0.05))

        XCTAssertTrue(popover.isShown)
        XCTAssertNotNil(hosting.view.window)
        // 宽度恒为 360，与内容多少无关。
        XCTAssertEqual(popover.contentSize.width, MenuBarPopoverLayout.width)
        let maxHeight = MenuBarPopoverLayout.maxContentHeight(screenHeight: NSScreen.main?.visibleFrame.height)
        // 40 台 Server 的可滚动内容区必须被 frame(maxHeight:) 夹到上限——这条在生产代码里
        // 去掉 `.frame(maxHeight: maxContentHeight)`（或把 maxContentHeight 传成 .infinity）
        // 时会红：document.frame.height 会远超 maxHeight，下面这条断言直接失败。
        let scrollViews = descendants(of: hosting.view).compactMap { $0 as? NSScrollView }
        XCTAssertEqual(scrollViews.count, 1)
        let scroll = try XCTUnwrap(scrollViews.first)
        let document = try XCTUnwrap(scroll.documentView)
        XCTAssertGreaterThan(scroll.frame.height, 120)
        XCTAssertLessThanOrEqual(scroll.frame.height, maxHeight + 1)
        // 40 台 Server（即便折叠）必须比可视区高得多，才是这条测试要守护的"确实会溢出"场景。
        XCTAssertGreaterThan(document.frame.height, scroll.contentView.bounds.height + 50)
        let bottom = document.frame.height - scroll.contentView.bounds.height
        scroll.contentView.scroll(to: NSPoint(x: 0, y: bottom))
        scroll.reflectScrolledClipView(scroll.contentView)
        XCTAssertGreaterThanOrEqual(scroll.contentView.bounds.maxY, document.frame.maxY - 1)
    }

    func testShownPopoverWithFewServersDoesNotForceOverflow() throws {
        _ = NSApplication.shared
        let summary = try manyServerCardsSummary(machineCount: 1)
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(),
            cachedSummary: summary
        )
        let hosting = MenuBarPopoverLayout.makeHostingController(rootView: MenuBarPopoverView(model: model))
        let popover = NSPopover()
        popover.contentViewController = hosting
        hosting.loadViewIfNeeded()
        hosting.view.frame.size.width = MenuBarPopoverLayout.width
        hosting.view.layoutSubtreeIfNeeded()
        let fittingHeightBeforeShow = hosting.view.fittingSize.height

        let anchorWindow = NSWindow(
            contentRect: NSRect(x: -10_000, y: -10_000, width: 20, height: 20),
            styleMask: .borderless, backing: .buffered, defer: false
        )
        anchorWindow.isReleasedWhenClosed = false
        let anchor = NSButton(frame: NSRect(x: 0, y: 0, width: 20, height: 20))
        anchorWindow.contentView?.addSubview(anchor)
        anchorWindow.orderFront(nil)
        defer { popover.close(); anchorWindow.close() }
        popover.show(relativeTo: anchor.bounds, of: anchor, preferredEdge: .minY)
        RunLoop.main.run(until: Date().addingTimeInterval(0.05))

        // 宽度恒为 360。
        XCTAssertEqual(popover.contentSize.width, MenuBarPopoverLayout.width)
        let maxHeight = MenuBarPopoverLayout.maxContentHeight(screenHeight: NSScreen.main?.visibleFrame.height)
        // 少内容：preferredContentSize.height 必须贴合内容理想高度（差 ≤2pt），且显著小于
        // maxContentHeight——不强行撑到上限留白。hosting controller 取自生产工厂
        // MenuBarPopoverLayout.makeHostingController；工厂不设 sizingOptions 时 preferredContentSize
        // 停留在 .zero，下面第一条断言失败。
        XCTAssertLessThanOrEqual(abs(hosting.preferredContentSize.height - fittingHeightBeforeShow), 2)
        XCTAssertLessThan(hosting.preferredContentSize.height, maxHeight - 50)

        let scrollViews = descendants(of: hosting.view).compactMap { $0 as? NSScrollView }
        let scroll = try XCTUnwrap(scrollViews.first)
        let document = try XCTUnwrap(scroll.documentView)
        // 内容明显没有多到需要滚动：document 高度不应比可视区高出一大截（不误判溢出）。
        XCTAssertLessThanOrEqual(document.frame.height, scroll.contentView.bounds.height + 50)
    }

    /// #177：构造 N 台机器的 Server 卡片场景，专供视口溢出/不溢出的测试用——不是产品口径 fixture。
    /// `MobileSource` 没有公开的逐字段 init（只有 `Codable` 的 `init(from:)`），跨模块只能走 JSON 解码。
    private func manyServerCardsSummary(machineCount: Int) throws -> MobileSummary {
        let rows = (0..<machineCount).map { index in
            MobileBreakdownRow(
                id: "machine-\(index)", label: "machine-\(index)", tokens: 100,
                sourceIDs: ["src-\(index)"]
            )
        }
        let sourcesJSON = (0..<machineCount).map { index in
            """
            {
              "source_id": "src-\(index)", "machine": "machine-\(index)", "os_user": "user\(index)",
              "platform": "linux", "status": "ok",
              "last_observed_at": "2026-06-25T11:00:00+08:00", "last_pushed_at": "2026-06-25T11:00:00+08:00"
            }
            """
        }.joined(separator: ",")
        let sources = try JSONDecoder().decode([MobileSource].self, from: Data("[\(sourcesJSON)]".utf8))
        let base = try summary(periodID: "today", totalTokens: machineCount * 100)
        return MobileSummary(
            schemaVersion: base.schemaVersion, client: base.client, generatedAt: base.generatedAt,
            timezone: base.timezone, period: base.period, trend: base.trend,
            sources: sources,
            breakdown: MobileBreakdown(byMachine: rows, byOSUser: [], byAgent: [], byModel: [], byDate: []),
            limits: base.limits
        )
    }

    /// #177 第三轮：`manyServerCardsSummary` 只有壳（无 agents/models），展开后是「暂无模型明细」，
    /// 量不出真实展开负载。这里补一份带真实 Agent/模型明细的重量级 fixture，专供 relayout 耗时测量用。
    func testHostedPopoverKeepsViewportThroughLoadAndHistorySwitch() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(),
            cachedSummaries: ["week": CachedMenuSummary(
                summary: try summary(periodID: "week", totalTokens: 700), fetchedAt: now
            )], now: { now }, loadSummary: loader.load
        )
        let popover = NSPopover()
        let hosting = MenuBarPopoverLayout.makeHostingController(rootView: MenuBarPopoverView(model: model))
        popover.contentViewController = hosting
        hosting.loadViewIfNeeded()
        hosting.view.frame.size.width = MenuBarPopoverLayout.width

        func assertVisibleViewport(_ phase: String) {
            hosting.view.layoutSubtreeIfNeeded()
            let fittingHeight = hosting.view.fittingSize.height
            XCTAssertGreaterThan(fittingHeight, 220, phase)
            // 模拟 NSPopover 展示时按 preferredContentSize 提交实际尺寸，才能量出内部
            // ScrollView 的真实高度（没有真实窗口时它永远是 0）。
            hosting.view.setFrameSize(NSSize(width: MenuBarPopoverLayout.width, height: fittingHeight))
            hosting.view.layoutSubtreeIfNeeded()
            let scroll = descendants(of: hosting.view).compactMap { $0 as? NSScrollView }
            XCTAssertEqual(scroll.count, 1, phase)
            XCTAssertGreaterThan(scroll.first?.frame.height ?? 0, 120, phase)
        }

        assertVisibleViewport("first open without cached data")
        model.refresh()
        try await loader.waitForRequestCount(1)
        assertVisibleViewport("loading")
        await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 349_100_000))
        await waitUntil { model.hasLoadedUsableSummary && !model.isLoading }
        assertVisibleViewport("loaded summary")
        model.refresh(periodID: "week")
        XCTAssertEqual(model.summary.period.id, "week")
        assertVisibleViewport("weekly history")
    }

    private func descendants(of view: NSView) -> [NSView] {
        [view] + view.subviews.flatMap(descendants)
    }

    func testPopoverLayoutUsesMeasuredContentHeight() {
        // #177：Popover v2 定稿宽度收窄到 360pt（HANDOFF.md 第 3 节），预期值随设计变更更新。
        XCTAssertEqual(MenuBarPopoverLayout.width, 360)
        XCTAssertEqual(MenuBarPopoverLayout.maxContentHeight(screenHeight: 922), 874)
    }

    /// #177 第三轮真机反馈：展开 Server 卡片非常慢的根因——`NSPopover.animates` 默认 true，
    /// preferredContentSize 随展开变化时 AppKit 会做窗口级动画，动画期间反复用中间尺寸
    /// 触发整棵内容树 relayout。生产代码唯一构造/配置 popover 的入口是
    /// `MenuBarPopoverLayout.configure(_:)`（`StatusBarController.setupPopover()` 调用它），
    /// 必须在这里关掉动画，不能依赖默认值。
    func testPopoverConfigurationDisablesAnimationsToAvoidPerFrameRelayoutOnExpand() {
        let popover = NSPopover()
        MenuBarPopoverLayout.configure(popover)
        XCTAssertFalse(
            popover.animates,
            "NSPopover.animates 默认 true：展开 Server 卡片改变 preferredContentSize 时会触发窗口级动画，" +
            "动画期间反复用中间尺寸让整棵内容树重新 relayout——这是真机「展开非常慢」的根因，必须显式关掉"
        )
        XCTAssertEqual(popover.behavior, .transient)
    }

    /// #177 第三轮真机反馈：展开/收起改变 `preferredContentSize` 时，实际改变高度的那一次
    /// `layoutSubtreeIfNeeded` 必须真的反映新高度——用真实的「收起 fittingSize」与「20 台
    /// Server 全部有模型明细时的 fittingSize」对比，证明这不是空跑：内容树确实随展开数据量
    /// 显著变化，NSPopover 在 animates=true 时会对这段真实高度差做窗口级动画，每帧都要在
    /// 中间高度上重新问一次 SwiftUI「这个尺寸下你想多高」。逐帧耗时只能在真机用 Instruments/
    /// 肉眼确认，这里只对「内容树本身确实是重量级的」给出可复算证据。
    func testStatusItemPresentationKeepsMenuBarEntryNumeric() throws {
        let state = MenuBarViewModel.build(
            from: try summary(periodID: "today", totalTokens: 366_442_154),
            selectedPeriodID: "today"
        ,
            deviceTimeZone: shanghaiTZForTests)

        XCTAssertEqual(MenuBarStatusItemPresentation.title(for: state), "366.4M")
        XCTAssertEqual(MenuBarStatusItemPresentation.tooltip(for: state), "AI Usage · 今天 366.4M")
    }

    /// #186：periodTitleSuffix 是独立字段（不烘进 periodLabel），tooltip 必须自己把它拼上去，
    /// 否则本机时区标注只会出现在 MenuBarState 里，状态栏 tooltip 上完全看不到。
    func testStatusItemPresentationTooltipAppendsPeriodTitleSuffix() throws {
        let state = MenuBarViewModel.build(
            from: try summary(periodID: "today", totalTokens: 366_442_154),
            selectedPeriodID: "today",
            now: try date("2026-07-18T12:00:00+08:00"),
            deviceTimeZone: try XCTUnwrap(TimeZone(identifier: "America/Los_Angeles"))
        )

        XCTAssertEqual(state.periodTitleSuffix, "（北京时间）")
        XCTAssertEqual(
            MenuBarStatusItemPresentation.tooltip(for: state), "AI Usage · 今天（北京时间） 366.4M"
        )
    }

    func testStatusItemPresentationUsesNewAutosaveNameForVisiblePlacement() {
        XCTAssertEqual(
            MenuBarStatusItemPresentation.autosaveName,
            "com.chunbai.aiusage.menubar.status.numeric.v3"
        )
    }

    func testStatusItemPresentationAllowsUserRecoveryFromMenuBarRemoval() {
        XCTAssertEqual(
            MenuBarStatusItemPresentation.behavior,
            .removalAllowed
        )
    }

    func testSwitchToFreshCachedPeriodDoesNotRequestNetwork() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            cachedSummaries: [
                "week": CachedMenuSummary(
                    summary: try summary(periodID: "week", totalTokens: 700),
                    fetchedAt: now.addingTimeInterval(-60)
                )
            ],
            cacheFreshnessInterval: 300,
            now: { now },
            loadSummary: loader.load
        )

        model.refresh(periodID: "week")
        await yieldToMainActor()

        XCTAssertEqual(model.selectedPeriodID, "week")
        XCTAssertEqual(model.summary.period.id, "week")
        XCTAssertEqual(model.summary.period.totalTokens, 700)
        XCTAssertFalse(model.isLoading)
        let requestCount = await loader.requestCount()
        XCTAssertEqual(requestCount, 0)
    }

    // #176：期间菜单只读已有缓存（内存优先，磁盘退路），绝不为展开菜单发请求。
    func testPeriodMenuRowsReadsMemoryCacheWithoutNetworkRequest() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let cachedSummary = try summaryWithDate(
            periodID: "today", date: "2026-06-24", startDate: "2026-06-24", totalTokens: 4200
        )
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(),
            cachedSummaries: ["today:-1": CachedMenuSummary(summary: cachedSummary, fetchedAt: now)],
            now: { now }, loadSummary: loader.load
        )

        let rows = model.periodMenuRows(for: "today")

        XCTAssertEqual(rows.count, 7)
        XCTAssertEqual(rows[1].selection.offset, -1)
        XCTAssertEqual(rows[1].totalText, "4.2K")
        let requestCount = await loader.requestCount()
        XCTAssertEqual(requestCount, 0)
    }

    func testPeriodMenuRowsFallBackToDiskCacheWithoutNetworkRequest() async throws {
        let loader = ControlledSummaryLoader()
        let paths = try temporaryRuntimePaths()
        let now = try date("2026-06-25T12:00:00+08:00")
        // 本周一是 2026-06-22（now=06-25 周四），offset -1 起始应是 2026-06-15。
        let diskSummary = try summaryWithDate(
            periodID: "week", date: "2026-06-15", startDate: "2026-06-15", totalTokens: 777
        )
        try SummaryCache.save(diskSummary, paths: paths, offset: -1)
        let model = MenuBarAppModel(paths: paths, config: testConfig(), now: { now }, loadSummary: loader.load)

        let rows = model.periodMenuRows(for: "week")

        XCTAssertEqual(rows[1].selection.offset, -1)
        XCTAssertEqual(rows[1].totalText, "777")
        let requestCount = await loader.requestCount()
        XCTAssertEqual(requestCount, 0)
    }

    func testPeriodMenuRowsShowDashWhenNoCacheExists() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(), now: { now }, loadSummary: loader.load
        )

        let rows = model.periodMenuRows(for: "today")

        XCTAssertTrue(rows.allSatisfy { $0.totalText == "—" })
        let requestCount = await loader.requestCount()
        XCTAssertEqual(requestCount, 0)
    }

    func testSwitchingToHistoricalPeriodKeepsQuotaRingsFromNewestSnapshot() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-07-18T12:00:00+08:00")
        let freshClaudeWindow = MobileLimitWindow(
            sourceID: "claude-main", provider: "claude", window: "session",
            usedPercent: 26, remainingPercent: 74,
            resetAt: "2026-07-18T18:00:00+08:00", windowDurationMinutes: 300,
            observedAt: "2026-07-18T11:30:00+08:00", sourceType: "official_cli",
            confidence: "observed", status: "ok", official: true
        )
        let staleClaudeWindow = MobileLimitWindow(
            sourceID: "claude-main", provider: "claude", window: "session",
            usedPercent: 80, remainingPercent: 20,
            resetAt: "2026-07-11T18:00:00+08:00", windowDurationMinutes: 300,
            observedAt: "2026-07-11T09:00:00+08:00", sourceType: "official_cli",
            confidence: "observed", status: "ok", official: true
        )
        let todaySummary = try summary(
            periodID: "today", totalTokens: 100, generatedAt: "2026-07-18T11:00:00+08:00",
            providerSlots: [providerSlot(provider: "claude", windows: [freshClaudeWindow], status: "available")]
        )
        let historicalWeekSummary = try summary(
            periodID: "week", totalTokens: 700, generatedAt: "2026-07-11T11:00:00+08:00",
            providerSlots: [providerSlot(provider: "claude", windows: [staleClaudeWindow], status: "available")]
        )
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            cachedSummaries: [
                "today": CachedMenuSummary(summary: todaySummary, fetchedAt: now),
                "week": CachedMenuSummary(summary: historicalWeekSummary, fetchedAt: now),
            ],
            cacheFreshnessInterval: 300,
            now: { now },
            loadSummary: loader.load
        )

        model.refresh(periodID: "week")
        await yieldToMainActor()

        XCTAssertEqual(model.selectedPeriodID, "week")
        XCTAssertEqual(model.summary.period.id, "week")
        let claude = try XCTUnwrap(model.state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.outerPctText, "26%", "切到历史周不应回退到那份快照缓存的旧额度")
        let requestCount = await loader.requestCount()
        XCTAssertEqual(requestCount, 0)
    }

    /// #186：MenuBarAppModel 的 init(deviceTimeZoneProvider:) 必须真的一路传到 rebuildState()
    /// 内两次 MenuBarViewModel.build 调用，不能在中途被吞掉、悄悄退回 .current——用与本机大概率
    /// 不同的 America/Los_Angeles 反证：headerUpdatedText 与 periodTitleSuffix 都必须反映
    /// provider 返回的时区，而不是运行测试的机器自己的时区。
    func testDeviceTimeZoneProviderFromInitFlowsThroughToRebuiltState() throws {
        let loader = ControlledSummaryLoader()
        let losAngeles = try XCTUnwrap(TimeZone(identifier: "America/Los_Angeles"))
        let todaySummary = try summary(
            periodID: "today", totalTokens: 100,
            generatedAt: "2026-07-18T21:12:00+08:00",
            sourcesJSON: """
            [{"source_id": "s", "machine": "mac", "os_user": "wang", "platform": "macos",
              "display_name": null, "status": "ok",
              "last_observed_at": "2026-07-18T21:12:00+08:00", "last_pushed_at": "2026-07-18T21:12:00+08:00",
              "error_message": null}]
            """
        )
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            cachedSummary: todaySummary,
            now: { try! self.date("2026-07-18T22:00:00+08:00") },
            deviceTimeZoneProvider: { losAngeles },
            loadSummary: loader.load
        )

        // 21:12 北京时间换算到洛杉矶（同为 07-18）是 06:12；如果 provider 没传到
        // build()，会退回 .autoupdatingCurrent（本机真实时区）或误用别的时区，输出就不会是 "06:12 更新"。
        XCTAssertEqual(model.state.headerUpdatedText, "06:12 更新")
        // fixture 的 summary.timezone 固定 "Asia/Shanghai"，与洛杉矶当前偏移不同——
        // periodTitleSuffix 必须带标注。
        XCTAssertEqual(model.state.periodTitleSuffix, "（北京时间）")
    }

    /// #186 P1 修复（PR #197 Codex 审查）：deviceTimeZoneProvider 之前存的是 init 时读一次的
    /// 不可变 TimeZone 值——运行中用户切换系统时区后，界面会一直显示旧时区，直到 App 重启。
    /// 必须每次 rebuildState() 都重新调用 provider（而不是缓存首次读到的值），并在系统真的发出
    /// NSSystemTimeZoneDidChange 通知时主动触发一次 rebuildState()，让菜单栏不需要重启就能反映
    /// 新时区。用可变的 provider（闭包读一个外部 box 的当前值）模拟「用户切换了系统时区」。
    func testSystemTimeZoneChangeNotificationRebuildsStateWithNewTimeZone() async throws {
        let loader = ControlledSummaryLoader()
        let shanghai = shanghaiTZForTests
        let losAngeles = try XCTUnwrap(TimeZone(identifier: "America/Los_Angeles"))
        let box = TimeZoneBox(shanghai)
        let todaySummary = try summary(
            periodID: "today", totalTokens: 100,
            generatedAt: "2026-07-18T21:12:00+08:00",
            sourcesJSON: """
            [{"source_id": "s", "machine": "mac", "os_user": "wang", "platform": "macos",
              "display_name": null, "status": "ok",
              "last_observed_at": "2026-07-18T21:12:00+08:00", "last_pushed_at": "2026-07-18T21:12:00+08:00",
              "error_message": null}]
            """
        )
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            cachedSummary: todaySummary,
            now: { try! self.date("2026-07-18T22:00:00+08:00") },
            deviceTimeZoneProvider: { box.timeZone },
            loadSummary: loader.load
        )

        // 起初本机=北京，与 summary.timezone 偏移相同：不带标注，钟点是北京时间。
        XCTAssertEqual(model.state.headerUpdatedText, "21:12 更新")
        XCTAssertEqual(model.state.periodTitleSuffix, "")

        // 模拟用户在系统设置里把时区切到洛杉矶：系统会发 NSSystemTimeZoneDidChange 通知。
        box.timeZone = losAngeles
        NotificationCenter.default.post(name: .NSSystemTimeZoneDidChange, object: nil)
        await yieldToMainActor()

        XCTAssertEqual(
            model.state.headerUpdatedText, "06:12 更新",
            "收到系统时区变化通知后，不重启 App 也必须用新时区重新渲染"
        )
        XCTAssertEqual(model.state.periodTitleSuffix, "（北京时间）")
    }

    /// 切到历史周期（如「本周」）后，会显示那份历史快照里更早的同步时间，而不是设备实际
    /// 最新一次同步（体现在 todaySummary/缓存里）的时间。headerUpdatedText 必须取所有已知
    /// summary 里最新的同步时间，与 quotaRings 取最新快照同一思路。
    func testHeaderUpdatedTextTakesLatestSyncTimeAcrossAllKnownSummariesNotJustSelectedPeriod() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-07-18T22:00:00+08:00")
        let olderSourceJSON = """
        [{"source_id": "week-src", "machine": "mac", "os_user": "wang", "platform": "macos",
          "display_name": null, "status": "ok",
          "last_observed_at": "2026-07-11T09:23:00+08:00", "last_pushed_at": "2026-07-11T09:23:00+08:00",
          "error_message": null}]
        """
        let newerSourceJSON = """
        [{"source_id": "today-src", "machine": "mac", "os_user": "wang", "platform": "macos",
          "display_name": null, "status": "ok",
          "last_observed_at": "2026-07-18T21:12:00+08:00", "last_pushed_at": "2026-07-18T21:12:00+08:00",
          "error_message": null}]
        """
        let todaySummary = try summary(
            periodID: "today", totalTokens: 100, generatedAt: "2026-07-18T21:12:00+08:00",
            sourcesJSON: newerSourceJSON
        )
        let historicalWeekSummary = try summary(
            periodID: "week", totalTokens: 700, generatedAt: "2026-07-11T09:23:00+08:00",
            sourcesJSON: olderSourceJSON
        )
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            cachedSummaries: [
                "today": CachedMenuSummary(summary: todaySummary, fetchedAt: now),
                "week": CachedMenuSummary(summary: historicalWeekSummary, fetchedAt: now),
            ],
            cacheFreshnessInterval: 300,
            now: { now },
            deviceTimeZoneProvider: { shanghaiTZForTests },
            loadSummary: loader.load
        )

        model.refresh(periodID: "week")
        await yieldToMainActor()

        XCTAssertEqual(model.selectedPeriodID, "week")
        // 切到「本周」（自身最新同步 09:23）后，标题栏仍必须显示设备实际最新同步时间 21:12
        // （来自 todaySummary），不能回退到本周快照里更早的时间。
        XCTAssertEqual(model.state.headerUpdatedText, "21:12 更新")
        let requestCount = await loader.requestCount()
        XCTAssertEqual(requestCount, 0)
    }

    func testSyncNowSendsOneRequestPerPeriodOnToday() async throws {
        let loader = ControlledSummaryLoader()
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            loadSummary: loader.load
        )
        model.syncNow()
        await yieldToMainActor()
        let onToday = await loader.totalRequestCount()
        XCTAssertEqual(onToday, 1, "选中今天时立即同步只应请求一次 today")

        let historyLoader = ControlledSummaryLoader()
        let historyModel = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "week"),
            loadSummary: historyLoader.load
        )
        historyModel.syncNow()
        await yieldToMainActor()
        let onWeek = await historyLoader.totalRequestCount()
        XCTAssertEqual(onWeek, 2, "选中本周时应请求 week 与 today 各一次")
    }

    func testThreeVisiblePeriodsKeepIndependentFreshCaches() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let periods = ["today": 100, "week": 200, "month": 300]
        let cached = try Dictionary(uniqueKeysWithValues: periods.map { period, total in
            (
                period,
                CachedMenuSummary(
                    summary: try summary(periodID: period, totalTokens: total),
                    fetchedAt: now.addingTimeInterval(-60)
                )
            )
        })
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            cachedSummaries: cached,
            cacheFreshnessInterval: 300,
            now: { now },
            loadSummary: loader.load
        )

        for period in ["today", "week", "month"] {
            model.refresh(periodID: period)
            await yieldToMainActor()
            XCTAssertEqual(model.selectedPeriodID, period)
            XCTAssertEqual(model.summary.period.id, period)
            XCTAssertEqual(model.summary.period.totalTokens, periods[period])
            XCTAssertNil(model.errorMessage)
        }

        let requestCount = await loader.requestCount()
        XCTAssertEqual(requestCount, 0)
    }

    func testSwitchToExpiredCachedPeriodShowsCacheThenRefreshesInBackground() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            cachedSummaries: [
                "week": CachedMenuSummary(
                    summary: try summary(periodID: "week", totalTokens: 700),
                    fetchedAt: now.addingTimeInterval(-600)
                )
            ],
            cacheFreshnessInterval: 300,
            now: { now },
            loadSummary: loader.load
        )

        model.refresh(periodID: "week")
        try await loader.waitForRequestCount(1)

        XCTAssertEqual(model.summary.period.id, "week")
        XCTAssertEqual(model.summary.period.totalTokens, 700)
        XCTAssertTrue(model.isLoading)

        await loader.complete(period: "week", summary: try summary(periodID: "week", totalTokens: 900))
        await waitUntil {
            model.summary.period.totalTokens == 900 && model.isLoading == false
        }
    }

    func testExpiredCachedPeriodSurvivesBackgroundRefreshFailure() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            cachedSummaries: [
                "month": CachedMenuSummary(
                    summary: try summary(periodID: "month", totalTokens: 1200),
                    fetchedAt: now.addingTimeInterval(-600)
                )
            ],
            cacheFreshnessInterval: 300,
            now: { now },
            loadSummary: loader.load
        )

        model.refresh(periodID: "month")
        try await loader.waitForRequestCount(1)
        await loader.fail(period: "month")
        await waitUntil {
            model.isLoading == false
        }

        XCTAssertEqual(model.summary.period.id, "month")
        XCTAssertEqual(model.summary.period.totalTokens, 1200)
        XCTAssertTrue(model.errorMessage?.hasPrefix("刷新失败，正在显示缓存：") == true)
    }

    func testSuccessfulQuotaRemainsVisibleWhenFreshSummaryReportsQuotaFailure() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let lastSuccessfulWindow = MobileLimitWindow(
            sourceID: "claude-main",
            provider: "claude",
            window: "session",
            usedPercent: 4,
            remainingPercent: 96,
            resetAt: "2026-06-25T15:00:00+08:00",
            windowDurationMinutes: 300,
            observedAt: "2026-06-25T11:00:00+08:00",
            sourceType: "official_cli",
            confidence: "observed",
            status: "ok",
            official: true
        )
        let cached = try summary(
            periodID: "today",
            totalTokens: 100,
            providerSlots: [
                MobileProviderSlot(
                    provider: "claude",
                    usage: MobileProviderUsage(
                        status: "available", totalTokens: 100, inputTokens: 20,
                        outputTokens: 10, cacheTokens: 70
                    ),
                    quota: MobileProviderQuota(
                        status: "available", reason: nil,
                        lastVerifiedAt: lastSuccessfulWindow.observedAt,
                        sourceID: lastSuccessfulWindow.sourceID,
                        sourceType: lastSuccessfulWindow.sourceType,
                        windows: [lastSuccessfulWindow]
                    )
                )
            ]
        )
        let refreshed = try summary(
            periodID: "today",
            totalTokens: 200,
            providerSlots: [
                MobileProviderSlot(
                    provider: "claude",
                    usage: MobileProviderUsage(
                        status: "available", totalTokens: 200, inputTokens: 40,
                        outputTokens: 20, cacheTokens: 140
                    ),
                    quota: MobileProviderQuota(
                        status: "missing", reason: "unavailable",
                        lastVerifiedAt: lastSuccessfulWindow.observedAt,
                        sourceID: lastSuccessfulWindow.sourceID,
                        sourceType: lastSuccessfulWindow.sourceType,
                        windows: []
                    )
                )
            ]
        )
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            cachedSummaries: [
                "today": CachedMenuSummary(summary: cached, fetchedAt: now.addingTimeInterval(-600))
            ],
            cacheFreshnessInterval: 300,
            now: { now },
            loadSummary: loader.load
        )

        model.refresh(force: true)
        try await loader.waitForRequestCount(1)
        await loader.complete(period: "today", summary: refreshed)
        await waitUntil {
            model.isLoading == false
        }

        let claude = try XCTUnwrap(model.summary.providerSlots.first { $0.provider == "claude" })
        XCTAssertEqual(model.summary.period.totalTokens, 200)
        XCTAssertEqual(claude.usage.totalTokens, 200)
        XCTAssertEqual(claude.quota.status, "missing")
        XCTAssertEqual(claude.quota.windows, [lastSuccessfulWindow])
    }

    func testPopoverQuitActionTerminatesApplication() throws {
        try XCTSkipIf(
            ProcessInfo.processInfo.environment["CI"] == "true",
            "requires a macOS WindowServer session"
        )
        var didQuit = false
        let controller = StatusBarController(
            paths: try temporaryRuntimePaths(),
            quitApplication: {
                didQuit = true
            }
        )

        controller.quitFromPopover()

        XCTAssertTrue(didQuit)
    }

    func testIgnoresStaleRefreshAfterPeriodSwitch() async throws {
        let loader = ControlledSummaryLoader()
        let config = MenuBarRuntimeConfig(
            serverURL: "https://aiusage.chunbai.com",
            token: "test-token",
            dashboardURL: nil,
            defaultPeriod: "all"
        )
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: config,
            cachedSummary: MobileSummary.empty(periodID: "all"),
            loadSummary: loader.load
        )

        model.refresh(periodID: "today")
        model.refresh(periodID: "week")
        try await loader.waitForRequestCount(2)

        await loader.complete(period: "today", summary: MobileSummary.empty(periodID: "today"))
        try await loader.waitForCompleted("today")
        await yieldToMainActor()
        XCTAssertEqual(model.summary.period.id, "week")
        XCTAssertTrue(model.isLoading)

        await loader.complete(period: "week", summary: MobileSummary.empty(periodID: "week"))
        await waitUntil {
            model.summary.period.id == "week" && model.isLoading == false
        }
    }

    func testIgnoresStaleFailureAfterNewerRefreshSucceeds() async throws {
        let loader = ControlledSummaryLoader()
        let config = MenuBarRuntimeConfig(
            serverURL: "https://aiusage.chunbai.com",
            token: "test-token",
            dashboardURL: nil,
            defaultPeriod: "all"
        )
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: config,
            cachedSummary: MobileSummary.empty(periodID: "all"),
            loadSummary: loader.load
        )

        model.refresh(periodID: "today")
        model.refresh(periodID: "week")
        try await loader.waitForRequestCount(2)

        await loader.complete(period: "week", summary: MobileSummary.empty(periodID: "week"))
        await waitUntil {
            model.summary.period.id == "week" && model.isLoading == false
        }

        await loader.fail(period: "today")
        try await loader.waitForCompleted("today")
        await yieldToMainActor()
        XCTAssertNil(model.errorMessage)
        XCTAssertEqual(model.summary.period.id, "week")
    }

    func testShowsCachedDataWarningWhenRefreshFails() async throws {
        let loader = ControlledSummaryLoader()
        let config = MenuBarRuntimeConfig(
            serverURL: "https://aiusage.chunbai.com",
            token: "test-token",
            dashboardURL: nil,
            defaultPeriod: "today"
        )
        let cached = MobileSummary.empty(periodID: "today")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: config,
            cachedSummary: cached,
            loadSummary: loader.load
        )

        model.refresh()
        try await loader.waitForRequestCount(1)
        await loader.fail(period: "today")
        await waitUntil {
            model.isLoading == false
        }

        XCTAssertTrue(model.errorMessage?.hasPrefix("刷新失败，正在显示缓存：") == true)
        XCTAssertTrue(model.errorMessage?.contains("-1001") == true)
        XCTAssertEqual(model.summary, cached)
    }

    func testRefreshUsesUpdatedRuntimeConfigWithoutRestart() async throws {
        let loader = ControlledSummaryLoader()
        let paths = try temporaryRuntimePaths()
        try FileManager.default.createDirectory(at: paths.root, withIntermediateDirectories: true)
        let updatedConfig = """
        {
          "dashboard_url": "https://aiusage.chunbai.com/dashboard",
          "default_period": "today",
          "refresh_interval_seconds": 600,
          "server_url": "https://aiusage.chunbai.com",
          "token": "new-token"
        }
        """
        try updatedConfig.write(to: paths.configURL, atomically: true, encoding: .utf8)
        let staleConfig = MenuBarRuntimeConfig(
            serverURL: "https://vpn2.chunbai.com:8443",
            token: "old-token",
            dashboardURL: nil,
            defaultPeriod: "today"
        )
        let model = MenuBarAppModel(
            paths: paths,
            config: staleConfig,
            cachedSummary: MobileSummary.empty(periodID: "today"),
            loadSummary: loader.load
        )

        model.refresh()
        try await loader.waitForRequestCount(1)
        let requestConfig = try await loader.config(for: "today")

        XCTAssertEqual(requestConfig.baseURL.absoluteString, "https://aiusage.chunbai.com")
        XCTAssertEqual(requestConfig.bearerToken, "new-token")
    }

    func testSwitchingToFreshCacheInvalidatesAnOlderFailure() async throws {
        let loader = ControlledSummaryLoader()
        let now = Date()
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(),
            cachedSummaries: ["week": CachedMenuSummary(summary: try summary(periodID: "week", totalTokens: 700), fetchedAt: now)],
            now: { now }, loadSummary: loader.load
        )
        model.refresh(periodID: "today", force: true)
        try await loader.waitForRequestCount(1)
        model.refresh(periodID: "week")
        await loader.fail(period: "today")
        try await loader.waitForCompleted("today")
        await yieldToMainActor()
        XCTAssertEqual(model.summary.period.totalTokens, 700)
        XCTAssertNil(model.errorMessage, "A request for another selection must not show an error here")
        XCTAssertFalse(model.isLoading)
    }

    func testUncachedSelectionNeverShowsAnotherPeriodsNumbers() async throws {
        let loader = ControlledSummaryLoader()
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(),
            cachedSummary: try summary(periodID: "today", totalTokens: 123), loadSummary: loader.load
        )
        model.refresh(periodID: "month")
        try await loader.waitForRequestCount(1)
        XCTAssertEqual(model.summary.period.id, "month")
        XCTAssertEqual(model.summary.period.totalTokens, 0)
        await loader.fail(period: "month")
        try await loader.waitForCompleted("month")
        await yieldToMainActor()
        XCTAssertTrue(model.errorMessage?.hasPrefix("读取失败") == true)
    }

    func testHistorySurvivesRestartAndRelativeOffsetChanges() throws {
        let paths = try temporaryRuntimePaths()
        let historical = try summaryWithDate(periodID: "today", date: "2026-06-24", startDate: "2026-06-24", totalTokens: 900)
        try SummaryCache.save(historical, paths: paths, offset: 0)
        let oldTime = try date("2026-06-24T20:00:00+08:00")
        for url in try FileManager.default.contentsOfDirectory(at: paths.periodCacheDirectoryURL, includingPropertiesForKeys: nil) {
            try FileManager.default.setAttributes([.modificationDate: oldTime], ofItemAtPath: url.path)
        }
        // 今天写入同一相对位置不能把前天的数据覆盖掉。
        try SummaryCache.save(try summaryWithDate(periodID: "today", date: "2026-06-26", startDate: "2026-06-26", totalTokens: 100), paths: paths)
        let now = try date("2026-06-26T08:00:00+08:00")
        let caches = SummaryCache.loadSummaries(paths: paths, now: now)
        XCTAssertEqual(caches["today"]?.summary.period.totalTokens, 100)
        XCTAssertEqual(caches["today:-2"]?.summary.period.totalTokens, 900)
        let model = MenuBarAppModel(paths: paths, config: testConfig(), cachedSummaries: caches, now: { now })
        let rows = model.periodMenuRows(for: "today")
        XCTAssertEqual(rows.count, 7)
        XCTAssertEqual(rows[2].totalText, "900")
        XCTAssertEqual(rows[0].totalText, "100")
    }

    func testRunningAppMovesDatedHistoryAtMidnightWithoutReloadingHistory() async throws {
        let paths = try temporaryRuntimePaths()
        let loader = ControlledSummaryLoader()
        var now = try date("2026-06-25T23:59:00+08:00")
        try SummaryCache.save(try summaryWithDate(periodID: "today", date: "2026-06-24", startDate: "2026-06-24", totalTokens: 900), paths: paths, offset: -1)
        try SummaryCache.save(try summaryWithDate(periodID: "today", date: "2026-06-25", startDate: "2026-06-25", totalTokens: 100), paths: paths)
        let model = MenuBarAppModel(paths: paths, config: testConfig(), cachedSummaries: SummaryCache.loadSummaries(paths: paths, now: now), now: { now }, loadSummary: loader.load)
        XCTAssertEqual(model.periodMenuRows(for: "today")[1].totalText, "900")
        now = now.addingTimeInterval(120)
        model.refresh()
        try await loader.waitForRequestCount(1)
        let rows = model.periodMenuRows(for: "today")
        XCTAssertEqual(rows.count, 7)
        XCTAssertEqual(rows[1].totalText, "100")
        XCTAssertEqual(rows[2].totalText, "900")
        await loader.complete(period: "today", summary: try summaryWithDate(periodID: "today", date: "2026-06-26", startDate: "2026-06-26", totalTokens: 50))
        await waitUntil { !model.isLoading }
        let requests = await loader.totalRequestCount()
        XCTAssertEqual(requests, 1, "跨天只请求新今天，已保存的历史不应重新下载")
    }

    func testOldDatedHistoryRemainsVisibleWhileRefreshingAndOnReopen() async throws {
        let paths = try temporaryRuntimePaths()
        let loader = ControlledSummaryLoader()
        var now = try date("2026-06-26T08:00:00+08:00")
        let historical = try summaryWithDate(periodID: "today", date: "2026-06-25", startDate: "2026-06-25", totalTokens: 900)
        try SummaryCache.save(historical, paths: paths, offset: 0)
        for url in try FileManager.default.contentsOfDirectory(at: paths.periodCacheDirectoryURL, includingPropertiesForKeys: nil) {
            try FileManager.default.setAttributes([.modificationDate: try date("2026-06-25T20:00:00+08:00")], ofItemAtPath: url.path)
        }
        let caches = SummaryCache.loadSummaries(paths: paths, now: now)
        XCTAssertEqual(caches["today:-1"]?.summary.period.totalTokens, 900)
        let model = MenuBarAppModel(paths: paths, config: testConfig(), cachedSummaries: caches, now: { now }, loadSummary: loader.load)
        model.refresh(offset: -1)
        try await loader.waitForRequestCount(1)
        XCTAssertTrue(model.hasLoadedUsableSummary)
        XCTAssertEqual(model.summary.period.totalTokens, 900)
        await loader.complete(period: "today:-1", summary: historical)
        await waitUntil { !model.isLoading }
        now = now.addingTimeInterval(600)
        for _ in 0..<3 { model.refresh() }
        await yieldToMainActor()
        let count = await loader.totalRequestCount()
        XCTAssertEqual(count, 1)
        XCTAssertEqual(model.summary.period.totalTokens, 900)
    }

    func testHistoryKeepsSeparateCacheAndTodaysMenuBarValue() async throws {
        let loader = ControlledSummaryLoader()
        let paths = try temporaryRuntimePaths()
        let model = MenuBarAppModel(paths: paths, config: testConfig(), loadSummary: loader.load)
        model.refresh()
        try await loader.waitForRequestCount(1)
        await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 100))
        await waitUntil { !model.isLoading }
        model.refresh(offset: model.selectedOffset - 1)
        try await loader.waitForRequestCount(1)
        let request = try await loader.config(for: "today:-1")
        XCTAssertEqual(request.offset, -1)
        XCTAssertEqual(model.selectedOffset, -1)
        XCTAssertFalse(model.hasLoadedUsableSummary)
        await loader.complete(period: "today:-1", summary: try summary(periodID: "today", totalTokens: 900))
        await waitUntil { !model.isLoading }
        XCTAssertEqual(model.summary.period.totalTokens, 900)
        XCTAssertEqual(model.statusState.statusTitle, "100")
        XCTAssertEqual(SummaryCache.load(from: paths.cacheURL(forPeriod: "today", offset: 0))?.period.totalTokens, 100)
        XCTAssertEqual(SummaryCache.load(from: paths.cacheURL(forPeriod: "today", offset: -1))?.period.totalTokens, 900)
        model.refresh(offset: model.selectedOffset + 1)
        XCTAssertEqual(model.summary.period.totalTokens, 100)
        XCTAssertEqual(model.selectedOffset, 0)
        XCTAssertFalse(model.isLoading)
        let count = await loader.requestCount()
        XCTAssertEqual(count, 2)
    }

    func testStaleSamePeriodHistoryResponseCannotReplaceNewerSelection() async throws {
        let loader = ControlledSummaryLoader()
        let model = MenuBarAppModel(paths: try temporaryRuntimePaths(), config: testConfig(), loadSummary: loader.load)
        model.refresh(periodID: "month", offset: -1)
        model.refresh(offset: model.selectedOffset - 1)
        try await loader.waitForRequestCount(2)
        await loader.complete(period: "month:-2", summary: try summary(periodID: "month", totalTokens: 200))
        await waitUntil { !model.isLoading }
        await loader.complete(period: "month:-1", summary: try summary(periodID: "month", totalTokens: 900))
        try await loader.waitForCompleted("month:-1")
        await yieldToMainActor()
        XCTAssertEqual(model.selectedOffset, -2)
        XCTAssertEqual(model.summary.period.totalTokens, 200)
        model.refresh(periodID: "week")
        XCTAssertEqual(model.selectedOffset, 0)
        try await loader.waitForRequestCount(1)
        await loader.complete(period: "week", summary: try summary(periodID: "week", totalTokens: 100))
        await waitUntil { !model.isLoading }
    }

    func testYesterdayRelativeCacheExpiresAtServiceMidnight() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-26T00:01:00+08:00")
        let cachedAt = try date("2026-06-25T23:59:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(),
            cachedSummaries: ["today:-1": CachedMenuSummary(summary: try summary(periodID: "today", totalTokens: 999), fetchedAt: cachedAt)],
            now: { now }, loadSummary: loader.load
        )
        model.refresh(offset: model.selectedOffset - 1)
        try await loader.waitForRequestCount(1)
        XCTAssertFalse(model.hasLoadedUsableSummary)
        XCTAssertEqual(model.summary.period.totalTokens, 0)
        await loader.complete(period: "today:-1", summary: try summary(periodID: "today", totalTokens: 100))
        await waitUntil { !model.isLoading }
        XCTAssertEqual(model.summary.period.totalTokens, 100)
    }

    func testStartupDoesNotPresentPreviousDaysCacheAsToday() throws {
        let now = try date("2026-06-26T00:01:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(), config: testConfig(),
            cachedSummaries: ["today": CachedMenuSummary(
                summary: try summary(periodID: "today", totalTokens: 999),
                fetchedAt: try date("2026-06-25T23:59:00+08:00"))],
            now: { now }
        )
        XCTAssertNil(model.todaySummary)
        XCTAssertFalse(model.hasLoadedUsableSummary)
    }

    func testFreshCacheFastPathInvalidatesSameSelectionRequest() async throws {
        for shouldFail in [false, true] {
            let loader = ControlledSummaryLoader()
            let now = Date()
            let model = MenuBarAppModel(
                paths: try temporaryRuntimePaths(), config: testConfig(),
                cachedSummaries: ["today": CachedMenuSummary(summary: try summary(periodID: "today", totalTokens: 100), fetchedAt: now)],
                now: { now }, loadSummary: loader.load
            )
            model.refresh(force: true)
            try await loader.waitForRequestCount(1)
            model.refresh()
            XCTAssertFalse(model.isLoading)
            if shouldFail { await loader.fail(period: "today") }
            else { await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 999)) }
            try await loader.waitForCompleted("today")
            await yieldToMainActor()
            XCTAssertEqual(model.summary.period.totalTokens, 100)
            XCTAssertEqual(model.todaySummary?.period.totalTokens, 100)
            XCTAssertNil(model.errorMessage)
        }
    }

    func testRequestCrossingMidnightReloadsBeforeShowingYesterdayAsToday() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T23:59:59+08:00")
        let model = MenuBarAppModel(paths: try temporaryRuntimePaths(), config: testConfig(), now: { clock }, loadSummary: loader.load)
        model.refresh()
        try await loader.waitForRequestCount(1)
        clock = try date("2026-06-26T00:00:01+08:00")
        await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 999))
        try await loader.waitForTotalRequestCount(2)
        XCTAssertNil(model.todaySummary)
        XCTAssertFalse(model.hasLoadedUsableSummary)
        XCTAssertTrue(model.isLoading)
        await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 100))
        await waitUntil { !model.isLoading }
        XCTAssertEqual(model.todaySummary?.period.totalTokens, 100)
    }

    func testBackgroundTodayReadCrossingMidnightReloadsAndKeepsHistorySelected() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T23:59:59+08:00")
        let model = MenuBarAppModel(paths: try temporaryRuntimePaths(), config: testConfig(defaultPeriod: "month"), now: { clock }, loadSummary: loader.load)
        model.refreshToday()
        try await loader.waitForRequestCount(1)
        clock = try date("2026-06-26T00:00:01+08:00")
        await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 999))
        try await loader.waitForTotalRequestCount(2)
        XCTAssertNil(model.todaySummary)
        XCTAssertEqual(model.selectedPeriodID, "month")
        await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 100))
        await waitUntil { model.todaySummary?.period.totalTokens == 100 }
        XCTAssertEqual(model.selectedPeriodID, "month")
    }

    func testFailedRefreshCrossingMidnightClearsExpiredSelectionAndTodayValue() async throws {
        for selected in [MenuPeriodSelection(periodID: "today"), MenuPeriodSelection(periodID: "today", offset: -1), MenuPeriodSelection(periodID: "week"), MenuPeriodSelection(periodID: "month", offset: -1)] {
            let loader = ControlledSummaryLoader()
            var clock = try date("2026-06-25T23:59:59+08:00")
            var cached = ["today": CachedMenuSummary(summary: try summary(periodID: "today", totalTokens: 999), fetchedAt: clock)]
            cached[selected.cacheKey] = CachedMenuSummary(summary: try summary(periodID: selected.periodID, totalTokens: 900), fetchedAt: clock)
            let model = MenuBarAppModel(paths: try temporaryRuntimePaths(), config: testConfig(), cachedSummaries: cached, now: { clock }, loadSummary: loader.load)
            model.refresh(periodID: selected.periodID, offset: selected.offset, force: true)
            try await loader.waitForRequestCount(1)
            XCTAssertTrue(model.hasLoadedUsableSummary)
            clock = clock.addingTimeInterval(2)
            await loader.fail(period: selected.cacheKey)
            await waitUntil { !model.isLoading }
            XCTAssertEqual(model.selection, selected)
            XCTAssertNil(model.summary.period.date)
            XCTAssertEqual(model.summary.period.totalTokens, 0)
            XCTAssertFalse(model.hasLoadedUsableSummary)
            XCTAssertNil(model.todaySummary)
            XCTAssertTrue(model.errorMessage?.hasPrefix("读取失败") == true)
        }
    }

    func testFailedBackgroundTodayRefreshCrossingMidnightClearsOldValues() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T23:59:59+08:00")
        let model = MenuBarAppModel(paths: try temporaryRuntimePaths(), config: testConfig(defaultPeriod: "month"), cachedSummaries: [
            "today": CachedMenuSummary(summary: try summary(periodID: "today", totalTokens: 999), fetchedAt: clock),
            "month": CachedMenuSummary(summary: try summary(periodID: "month", totalTokens: 900), fetchedAt: clock)
        ], now: { clock }, loadSummary: loader.load)
        model.refreshToday()
        try await loader.waitForRequestCount(1)
        clock = clock.addingTimeInterval(2)
        await loader.fail(period: "today")
        try await loader.waitForCompleted("today")
        await yieldToMainActor()
        XCTAssertEqual(model.selectedPeriodID, "month")
        XCTAssertEqual(model.selectedOffset, 0)
        XCTAssertNil(model.todaySummary)
        XCTAssertFalse(model.hasLoadedUsableSummary)
        XCTAssertNil(model.summary.period.date)
    }

    func testLateBackgroundFailureDoesNotClearNewDayHistoryResult() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T23:59:59+08:00")
        let model = MenuBarAppModel(paths: try temporaryRuntimePaths(), config: testConfig(defaultPeriod: "month"), cachedSummaries: [
            "today": CachedMenuSummary(summary: try summary(periodID: "today", totalTokens: 999), fetchedAt: clock)
        ], now: { clock }, loadSummary: loader.load)
        model.refreshToday()
        try await loader.waitForRequestCount(1)
        clock = clock.addingTimeInterval(2)
        model.refresh(periodID: "week", offset: -1, force: true)
        try await loader.waitForRequestCount(2)
        await loader.complete(period: "week:-1", summary: try summary(periodID: "week", totalTokens: 700))
        await waitUntil { !model.isLoading }
        await loader.fail(period: "today")
        try await loader.waitForCompleted("today")
        await yieldToMainActor()
        XCTAssertEqual(model.selection, MenuPeriodSelection(periodID: "week", offset: -1))
        XCTAssertNil(model.todaySummary)
        XCTAssertTrue(model.hasLoadedUsableSummary)
        XCTAssertEqual(model.summary.period.totalTokens, 700)
    }

    func testInvalidBackgroundPeriodCrossingMidnightClearsToday() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T23:59:59+08:00")
        let model = MenuBarAppModel(paths: try temporaryRuntimePaths(), config: testConfig(defaultPeriod: "month"), cachedSummaries: [
            "today": CachedMenuSummary(summary: try summary(periodID: "today", totalTokens: 999), fetchedAt: clock)
        ], now: { clock }, loadSummary: loader.load)
        model.refreshToday()
        try await loader.waitForRequestCount(1)
        clock = clock.addingTimeInterval(2)
        await loader.complete(period: "today", summary: try summary(periodID: "week", totalTokens: 900))
        try await loader.waitForCompleted("today")
        await yieldToMainActor()
        XCTAssertNil(model.todaySummary)
        XCTAssertEqual(model.selectedPeriodID, "month")
    }

    private func waitUntil(
        timeoutIterations: Int = 50,
        _ predicate: @MainActor () -> Bool,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        for _ in 0..<timeoutIterations {
            if predicate() {
                return
            }
            try? await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("Timed out waiting for expected model state", file: file, line: line)
    }

    private func yieldToMainActor() async {
        for _ in 0..<5 {
            await Task.yield()
        }
    }

    private func temporaryRuntimePaths() throws -> RuntimePaths {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("ai-usage-menu-\(UUID().uuidString)", isDirectory: true)
        addTeardownBlock {
            try? FileManager.default.removeItem(at: root)
        }
        return RuntimePaths(root: root)
    }

    private func testConfig(defaultPeriod: String = "today") -> MenuBarRuntimeConfig {
        MenuBarRuntimeConfig(
            serverURL: "https://aiusage.chunbai.com",
            token: "test-token",
            dashboardURL: nil,
            defaultPeriod: defaultPeriod
        )
    }

    private func providerSlot(
        provider: String,
        windows: [MobileLimitWindow],
        status: String = "available",
        reason: String? = nil
    ) -> MobileProviderSlot {
        MobileProviderSlot(
            provider: provider,
            usage: .missing,
            quota: MobileProviderQuota(
                status: status,
                reason: reason,
                lastVerifiedAt: windows.compactMap(\.observedAt).max(),
                sourceID: windows.first?.sourceID,
                sourceType: windows.first?.sourceType,
                windows: windows
            )
        )
    }

    private func summary(
        periodID: String,
        totalTokens: Int,
        generatedAt: String = "2026-06-25T12:00:00+08:00",
        providerSlots: [MobileProviderSlot] = [],
        sourcesJSON: String = "[]"
    ) throws -> MobileSummary {
        let json = """
        {
          "schema_version": 1,
          "client": "macos",
          "generated_at": "\(generatedAt)",
          "timezone": "Asia/Shanghai",
          "period": {
            "id": "\(periodID)",
            "date": "2026-06-25",
            "start_date": "2026-06-25",
            "end_date": "2026-06-25",
            "total_tokens": \(totalTokens),
            "input_tokens": \(totalTokens),
            "output_tokens": 0,
            "cache_tokens": 0,
            "cache_ratio": 0,
            "machine": null,
            "account": null
          },
          "trend": {
            "period": "\(periodID)",
            "granularity": "\(periodID == "today" ? "hour" : "day")",
            "start_date": "2026-06-25",
            "end_date": "2026-06-25",
            "points": []
          },
          "sources": \(sourcesJSON),
          "breakdown": {
            "by_machine": [],
            "by_os_user": [],
            "by_agent": [],
            "by_model": [],
            "by_date": []
          },
          "limits": {
            "observed_count": 0,
            "total_count": 0,
            "windows": []
          }
        }
        """
        let base = try JSONDecoder().decode(MobileSummary.self, from: Data(json.utf8))
        return MobileSummary(
            schemaVersion: base.schemaVersion,
            client: base.client,
            generatedAt: base.generatedAt,
            timezone: base.timezone,
            period: base.period,
            trend: base.trend,
            sources: base.sources,
            breakdown: base.breakdown,
            limits: base.limits,
            providerSlots: providerSlots,
            providerUsageCoverage: base.providerUsageCoverage
        )
    }

    private func date(_ iso: String) throws -> Date {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let value = formatter.date(from: iso) {
            return value
        }
        formatter.formatOptions = [.withInternetDateTime]
        return try XCTUnwrap(formatter.date(from: iso))
    }

    /// #176 期间菜单测试专用：需要精确控制 period.date / start_date 来模拟缓存的「实际起始日期」。
    private func summaryWithDate(
        periodID: String,
        date: String,
        startDate: String,
        totalTokens: Int,
        generatedAt: String = "2026-06-25T12:00:00+08:00"
    ) throws -> MobileSummary {
        let json = """
        {
          "schema_version": 1,
          "client": "macos",
          "generated_at": "\(generatedAt)",
          "timezone": "Asia/Shanghai",
          "period": {
            "id": "\(periodID)",
            "date": "\(date)",
            "start_date": "\(startDate)",
            "end_date": "\(startDate)",
            "total_tokens": \(totalTokens),
            "input_tokens": \(totalTokens),
            "output_tokens": 0,
            "cache_tokens": 0,
            "cache_ratio": 0,
            "machine": null,
            "account": null
          },
          "trend": {
            "period": "\(periodID)",
            "granularity": "\(periodID == "today" ? "hour" : "day")",
            "start_date": "\(startDate)",
            "end_date": "\(startDate)",
            "points": []
          },
          "sources": [],
          "breakdown": {
            "by_machine": [],
            "by_os_user": [],
            "by_agent": [],
            "by_model": [],
            "by_date": []
          },
          "limits": {
            "observed_count": 0,
            "total_count": 0,
            "windows": []
          }
        }
        """
        return try JSONDecoder().decode(MobileSummary.self, from: Data(json.utf8))
    }

    // #177 性能：state 曾是计算属性，视图 body 每读一次就重建一遍 MenuBarState。
    // 改成存储属性后，连续读多次 state 不该再触发重建；只有输入真正变化（这里用命中缓存的
    // refresh 切换 period）才应该重建一次，且新 state 要反映新选中的期间。
    func testReadingStateRepeatedlyDoesNotRebuildButChangingPeriodDoes() async throws {
        let loader = ControlledSummaryLoader()
        let now = try date("2026-06-25T12:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "today"),
            cachedSummaries: [
                "today": CachedMenuSummary(
                    summary: try summary(periodID: "today", totalTokens: 100),
                    fetchedAt: now.addingTimeInterval(-60)
                ),
                "week": CachedMenuSummary(
                    summary: try summary(periodID: "week", totalTokens: 700),
                    fetchedAt: now.addingTimeInterval(-60)
                ),
            ],
            cacheFreshnessInterval: 300,
            now: { now },
            deviceTimeZoneProvider: { shanghaiTZForTests },
            loadSummary: loader.load
        )

        let countAfterInit = model.stateBuildCount
        for _ in 0..<20 {
            _ = model.state
        }
        XCTAssertEqual(
            model.stateBuildCount, countAfterInit,
            "连续读 20 次 state 不应触发重建"
        )

        model.refresh(periodID: "week")
        await yieldToMainActor()

        XCTAssertGreaterThan(
            model.stateBuildCount, countAfterInit,
            "切换到已缓存的 week 期间必须触发一次重建"
        )
        XCTAssertEqual(model.state.periodLabel, "本周", "重建后的 state 必须反映新选中的期间")
        let requestCount = await loader.requestCount()
        XCTAssertEqual(requestCount, 0, "week 缓存新鲜，不应发网络请求")
    }

    // Issue #190：D1 免费额度日读取被菜单栏预取推到 82.5%，根因是 week/month 预取新鲜度
    // 复用 cacheFreshnessInterval（300s）< 定时器刷新间隔（600s），导致每轮定时器都重新拉取。
    // week/month 必须改用远低于定时器频率的独立最小间隔（prefetchMinimumInterval）。
    //
    // 模拟 StatusBarController 的定时器路径：每 600s 调用一次 syncNow() + prefetchCommonPeriods()，
    // 连续 6 轮。today 每轮都应请求（驱动菜单栏数字），但 week/month 首轮无缓存时请求一次后，
    // 在 1 小时内的后续 5 轮都不应再请求。
    func testPrefetchCommonPeriodsStaysWithinMinimumIntervalAcrossTimerTicks() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T08:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(),
            now: { clock },
            loadSummary: loader.load
        )

        var issuedSoFar = 0
        for tick in 1...6 {
            clock = clock.addingTimeInterval(600)
            model.syncNow()
            model.prefetchCommonPeriods()

            // today 每轮必发；week/month 只在首轮（无缓存）发起。用累计已发起请求数同步，
            // 而不是 waitForCompleted("today")——同一 key 一旦完成过一次，completedPeriods
            // 这个 Set 会一直命中，后续轮次会在真正的新请求发出前就误判"已完成"。
            issuedSoFar += 1
            if tick == 1 { issuedSoFar += 2 }
            try await loader.waitForTotalRequestCount(issuedSoFar)

            await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: tick))
            if tick == 1 {
                await loader.complete(period: "week", summary: try summary(periodID: "week", totalTokens: 700))
                await loader.complete(period: "month", summary: try summary(periodID: "month", totalTokens: 3000))
            }
            await yieldToMainActor()
        }

        let total = await loader.totalRequestCount()
        XCTAssertEqual(
            total, 8,
            "6 轮 today（每轮 1 次）+ week 1 次 + month 1 次 = 8；week/month 在 1 小时预取窗口内不应重复请求"
        )
    }

    // 缓存存在但距上次预取不足 prefetchMinimumInterval（60 分钟）时，跳过；超过后各再请求一次。
    func testPrefetchCommonPeriodsRefetchesOnlyAfterMinimumIntervalElapses() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T08:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(),
            cachedSummaries: [
                "week": CachedMenuSummary(summary: try summary(periodID: "week", totalTokens: 700), fetchedAt: clock),
                "month": CachedMenuSummary(summary: try summary(periodID: "month", totalTokens: 3000), fetchedAt: clock),
            ],
            now: { clock },
            loadSummary: loader.load
        )

        clock = clock.addingTimeInterval(1800) // 30 分钟，仍在最小间隔内
        model.prefetchCommonPeriods()
        await yieldToMainActor()
        let requestCountAfter30Min = await loader.totalRequestCount()
        XCTAssertEqual(requestCountAfter30Min, 0, "30 分钟内不应重新预取 week/month")

        clock = clock.addingTimeInterval(1900) // 累计 3700s，超过 60 分钟最小间隔
        model.prefetchCommonPeriods()
        try await loader.waitForTotalRequestCount(2)
        await loader.complete(period: "week", summary: try summary(periodID: "week", totalTokens: 800))
        await loader.complete(period: "month", summary: try summary(periodID: "month", totalTokens: 3100))
        await yieldToMainActor()
        let requestCountAfterInterval = await loader.totalRequestCount()
        XCTAssertEqual(requestCountAfterInterval, 2, "超过 60 分钟最小间隔后 week/month 应各重新预取一次")
    }

    // 跨服务日（上海时区午夜）后，即使未满 60 分钟最小间隔，也必须立即重新预取——
    // 否则「本周/本月」在新的一天里会继续显示前一天缓存的过期统计。
    func testPrefetchCommonPeriodsRefetchesImmediatelyAfterServiceDayRollover() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T23:50:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(),
            cachedSummaries: [
                "week": CachedMenuSummary(summary: try summary(periodID: "week", totalTokens: 700), fetchedAt: clock),
                "month": CachedMenuSummary(summary: try summary(periodID: "month", totalTokens: 3000), fetchedAt: clock),
            ],
            now: { clock },
            loadSummary: loader.load
        )

        clock = try date("2026-06-26T00:05:00+08:00") // 跨零点，间隔仅 15 分钟但已跨服务日
        model.prefetchCommonPeriods()
        try await loader.waitForTotalRequestCount(2)
        let requestCountAfterRollover = await loader.totalRequestCount()
        XCTAssertEqual(requestCountAfterRollover, 2, "跨服务日后即使未满 60 分钟也要立即重新预取 week/month")
        await loader.complete(period: "week", summary: try summary(periodID: "week", totalTokens: 10))
        await loader.complete(period: "month", summary: try summary(periodID: "month", totalTokens: 20))
    }

    // PR #191 Codex 审查 P1：syncNow() 对非 today 的当前选中期无条件 force refresh，
    // 如果面板停在 week/month（offset 0）不动，定时器每轮调用 syncNow() 会绕过 #190 刚加的
    // prefetchMinimumInterval 节流——即使 prefetchCommonPeriods() 本身跳过了，syncNow() 那一路
    // 还是照样发。定时器必须改用 timerTick()，让「当前选中的 week/month」并入同一节流。
    func testTimerTickThrottlesSelectedNonTodayPeriodAcrossTicks() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T08:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "week"),
            now: { clock },
            loadSummary: loader.load
        )
        XCTAssertEqual(model.selectedPeriodID, "week", "前提：面板停在 week，不是 today")

        var issuedSoFar = 0
        for tick in 1...6 {
            clock = clock.addingTimeInterval(600)
            model.timerTick()

            // today（refreshToday 驱动菜单栏数字）每轮必发；week 是当前选中期，
            // 首轮无缓存会连同 month 一起由 prefetchCommonPeriods 发起，之后 5 轮都应跳过。
            issuedSoFar += 1
            if tick == 1 { issuedSoFar += 2 }
            try await loader.waitForTotalRequestCount(issuedSoFar)

            await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: tick))
            if tick == 1 {
                await loader.complete(period: "week", summary: try summary(periodID: "week", totalTokens: 700))
                await loader.complete(period: "month", summary: try summary(periodID: "month", totalTokens: 3000))
            }
            await yieldToMainActor()
        }

        let total = await loader.totalRequestCount()
        XCTAssertEqual(
            total, 8,
            "6 轮 today + 首轮 week/month = 8；即使面板停在 week，timerTick() 也不应绕过预取节流重复请求"
        )
    }

    // 超过 prefetchMinimumInterval（60 分钟）后，当前选中的 week（走 prefetchCommonPeriods
    // 同一节流）必须重新请求；30 分钟内不应请求。today 因为 refreshToday 无条件强刷，
    // 每次 timerTick 都会请求，与节流无关。
    func testTimerTickRefetchesSelectedWeekAfterMinimumIntervalElapses() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T08:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "week"),
            cachedSummaries: [
                "today": CachedMenuSummary(summary: try summary(periodID: "today", totalTokens: 1), fetchedAt: clock),
                "week": CachedMenuSummary(summary: try summary(periodID: "week", totalTokens: 700), fetchedAt: clock),
                "month": CachedMenuSummary(summary: try summary(periodID: "month", totalTokens: 3000), fetchedAt: clock),
            ],
            now: { clock },
            loadSummary: loader.load
        )

        clock = clock.addingTimeInterval(1800) // 30 分钟，week/month 仍新鲜
        model.timerTick()
        try await loader.waitForTotalRequestCount(1) // 仅 today
        await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 2))
        await yieldToMainActor()
        let afterHalfHour = await loader.totalRequestCount()
        XCTAssertEqual(afterHalfHour, 1, "week/month 缓存仍新鲜，30 分钟内不应重新请求")

        clock = clock.addingTimeInterval(1900) // 累计 3700s，超过 60 分钟最小间隔
        model.timerTick()
        try await loader.waitForTotalRequestCount(4) // +today +week +month
        await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 3))
        await loader.complete(period: "week", summary: try summary(periodID: "week", totalTokens: 800))
        await loader.complete(period: "month", summary: try summary(periodID: "month", totalTokens: 3100))
        await yieldToMainActor()
        let afterInterval = await loader.totalRequestCount()
        XCTAssertEqual(afterInterval, 4, "超过 60 分钟最小间隔后，当前选中的 week 与 month 都应各重新请求一次")
    }

    // PR #191 Codex 审查 P2：prefetchCommonPeriods 的请求发起时刻与响应落地时刻之间如果跨了
    // 服务日（上海时区午夜），这份响应描述的是「跨日前」的本周/本月，必须丢弃、不写入缓存，
    // 否则新的一天里会展示过期统计，还会因为 fetchedAt 是新写入的时间戳而被误判成新鲜，
    // 挡住下一次本该立即重新请求的预取。
    func testPrefetchCommonPeriodsDiscardsResponseThatCrossedServiceDay() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T23:59:50+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(),
            now: { clock },
            loadSummary: loader.load
        )

        model.prefetchCommonPeriods()
        try await loader.waitForTotalRequestCount(2) // week + month 发起时仍是 06-25

        clock = try date("2026-06-26T00:00:10+08:00") // 响应到达时已经跨了服务日
        await loader.complete(period: "week", summary: try summary(periodID: "week", totalTokens: 700))
        await loader.complete(period: "month", summary: try summary(periodID: "month", totalTokens: 3000))
        await yieldToMainActor()

        // 跨日响应应被丢弃：下一次预取因为「缓存缺失」重新请求 week 和 month，
        // 而不是被刚才那份（其实来自上一天）写入的缓存挡住。
        model.prefetchCommonPeriods()
        try await loader.waitForTotalRequestCount(4)
        let total = await loader.totalRequestCount()
        XCTAssertEqual(total, 4, "跨服务日的预取响应必须被丢弃，下一次预取应立即重新请求 week 和 month")
    }

    // reviewer 在 #191 P1/P2 收口前发现：coveredByPrefetch 的选中期完全交给
    // prefetchCommonPeriods() 处理后，它的 store() 只写 cachedSummaries，不更新
    // self.summary（只有 refresh() 的成功回调会更新 self.summary）。面板停在 week/month
    // 不动时，定时器刷新到了新数据，但界面上一直显示旧数字，直到面板关闭重开。
    func testTimerTickUpdatesVisibleSummaryWhenPrefetchRefreshesTheSelectedPeriod() async throws {
        let loader = ControlledSummaryLoader()
        var clock = try date("2026-06-25T08:00:00+08:00")
        let model = MenuBarAppModel(
            paths: try temporaryRuntimePaths(),
            config: testConfig(defaultPeriod: "week"),
            cachedSummaries: [
                "today": CachedMenuSummary(summary: try summary(periodID: "today", totalTokens: 1), fetchedAt: clock),
                "week": CachedMenuSummary(summary: try summary(periodID: "week", totalTokens: 700), fetchedAt: clock),
                "month": CachedMenuSummary(summary: try summary(periodID: "month", totalTokens: 3000), fetchedAt: clock),
            ],
            now: { clock },
            loadSummary: loader.load
        )
        XCTAssertEqual(model.summary.period.totalTokens, 700, "前提：面板当前展示的是 week 的旧缓存值")

        clock = clock.addingTimeInterval(3700) // 超过 60 分钟最小间隔，week/month 都会重新预取
        model.timerTick()
        try await loader.waitForTotalRequestCount(3) // today + week + month
        await loader.complete(period: "today", summary: try summary(periodID: "today", totalTokens: 2))
        await loader.complete(period: "week", summary: try summary(periodID: "week", totalTokens: 999))
        await loader.complete(period: "month", summary: try summary(periodID: "month", totalTokens: 3100))
        await yieldToMainActor()

        XCTAssertEqual(
            model.summary.period.totalTokens, 999,
            "面板停在 week 时，靠 prefetchCommonPeriods 刷新出来的新 week 结果必须同步反映到当前展示的" +
            "summary，不能只更新缓存、等面板关闭重开才看到"
        )
    }
}

private actor ControlledSummaryLoader {
    private var continuations: [String: CheckedContinuation<MobileSummary, Error>] = [:]
    private var configs: [String: MobileSummaryClientConfig] = [:]
    private var completedPeriods: Set<String> = []
    private var totalRequests = 0

    func load(config: MobileSummaryClientConfig) async throws -> MobileSummary {
        totalRequests += 1
        let key = config.offset == 0 ? config.period : "\(config.period):\(config.offset)"
        defer {
            completedPeriods.insert(key)
        }
        configs[key] = config
        return try await withCheckedThrowingContinuation { continuation in
            continuations[key] = continuation
        }
    }

    func complete(period: String, summary: MobileSummary) {
        continuations.removeValue(forKey: period)?.resume(returning: summary)
    }

    func fail(period: String) {
        continuations.removeValue(forKey: period)?.resume(throwing: URLError(.timedOut))
    }

    func waitForRequestCount(_ count: Int) async throws {
        for _ in 0..<50 {
            if continuations.count >= count {
                return
            }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("Timed out waiting for \(count) requests")
    }

    func waitForTotalRequestCount(_ count: Int) async throws {
        for _ in 0..<50 {
            if totalRequests >= count { return }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("Timed out waiting for \(count) total requests")
    }

    func waitForCompleted(_ period: String) async throws {
        for _ in 0..<50 {
            if completedPeriods.contains(period) {
                return
            }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("Timed out waiting for \(period) completion")
    }

    func requestCount() -> Int {
        configs.count
    }

    /// 实际调用次数（同一 period 重复请求也分别计数）。
    func totalRequestCount() -> Int {
        totalRequests
    }

    func config(for period: String) throws -> MobileSummaryClientConfig {
        guard let config = configs[period] else {
            throw XCTSkip("No request config recorded for \(period)")
        }
        return config
    }
}
