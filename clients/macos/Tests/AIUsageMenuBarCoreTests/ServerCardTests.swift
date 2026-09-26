import Foundation
import XCTest
@testable import AIUsageMenuBarCore

/// #175：Server 展开后按模型显示「占所属提供方周额度」。
final class ServerCardTests: XCTestCase {

    // MARK: - 一台机器混用 Claude / Codex：#180 决定暂停客户端估算（改走服务端校准，另行规划），
    // Server 展开模型行的「周额度」列本 PR 内一律显示「—」；这里只保留与 quotaText 无关的
    // 结构断言（零用量模型剔除、按 tokens 降序排列）。

    func testServerCardModelRowsExcludeZeroTokenModelsSortedDescendingAndQuotaTextIsAlwaysDash() throws {
        let machineRow = MobileBreakdownRow(
            id: "mac-1",
            label: "mac-1",
            tokens: 23_000_000 + 11_000_000 + 5_000_000,
            sourceIDs: ["src-1"],
            agents: [
                MobileSourceAgent(id: "claude", label: "Claude", tokens: 23_000_000 + 5_000_000, status: "available", models: [
                    MobileSourceModel(id: "claude-opus-5", label: "Claude Opus 5", tokens: 23_000_000, status: "available"),
                    MobileSourceModel(id: "deepseek-v4-pro", label: "DeepSeek V4 Pro", tokens: 5_000_000, status: "available"),
                ]),
                MobileSourceAgent(id: "codex", label: "Codex", tokens: 11_000_000, status: "available", models: [
                    MobileSourceModel(id: "gpt-5.6-sol", label: "GPT-5.6 Sol", tokens: 11_000_000, status: "available"),
                    MobileSourceModel(id: "gpt-5-review", label: "GPT-5 Review", tokens: 0, status: "available"),
                ]),
            ]
        )
        let summary = makeSummary(periodID: "week", byMachine: [machineRow], sources: [
            source(id: "src-1", machine: "mac-1", osUser: "alice", status: "ok")
        ])

        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "week")
        let card = try XCTUnwrap(state.serverCards.first { $0.id == "mac-1" })

        // 结构下限：零用量模型必须被剔除，行数精确为 3。
        XCTAssertEqual(card.models.count, 3)
        XCTAssertEqual(card.models.map(\.tokens), [23_000_000, 11_000_000, 5_000_000])

        let claudeRow = card.models[0]
        XCTAssertEqual(claudeRow.modelLabel, "Claude Opus 5")
        XCTAssertEqual(claudeRow.agentID, "claude")
        XCTAssertEqual(claudeRow.quotaText, "—")

        let codexRow = card.models[1]
        XCTAssertEqual(codexRow.modelLabel, "GPT-5.6 Sol")
        XCTAssertEqual(codexRow.agentID, "codex")
        XCTAssertEqual(codexRow.quotaText, "—")

        let deepseekRow = card.models[2]
        XCTAssertEqual(deepseekRow.modelLabel, "DeepSeek V4 Pro")
        XCTAssertEqual(deepseekRow.quotaText, "—")
    }

    // MARK: - Antigravity 里调用的 claude-opus 记为 Antigravity，不记 Claude

    func testAntigravityChannelClaudeModelCountsTowardAntigravityNotClaude() throws {
        let machineRow = MobileBreakdownRow(
            id: "gpu-1",
            label: "gpu-1",
            tokens: 10_000_000,
            sourceIDs: ["src-1"],
            agents: [
                MobileSourceAgent(id: "antigravity", label: "Antigravity", tokens: 10_000_000, status: "available", models: [
                    MobileSourceModel(id: "claude-opus-4-6-thinking", label: "claude-opus-4-6-thinking", tokens: 10_000_000, status: "available"),
                ]),
            ]
        )
        let summary = makeSummary(periodID: "week", byMachine: [machineRow], sources: [
            source(id: "src-1", machine: "gpu-1", osUser: "bob", status: "ok")
        ])

        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "week")
        let card = try XCTUnwrap(state.serverCards.first { $0.id == "gpu-1" })
        let row = try XCTUnwrap(card.models.first)

        XCTAssertEqual(row.agentID, "antigravity")
        XCTAssertEqual(row.agentDisplayName, "Antigravity")
        // #180：客户端估算已暂停（等待服务端校准），quotaText 一律「—」；Agent 归属本身仍要正确。
        XCTAssertEqual(row.quotaText, "—")
    }

    // MARK: - 副标题：多用户 vs 单用户

    func testSubtitleShowsUserCountWhenMultipleUsersAndUsernameWhenSingle() throws {
        let multiUserMachine = MobileBreakdownRow(
            id: "shared-linux",
            label: "shared-linux",
            tokens: 500,
            sourceIDs: ["u1", "u2", "u3", "u4", "u5"],
            agents: []
        )
        let singleUserMachine = MobileBreakdownRow(
            id: "solo-mac",
            label: "solo-mac",
            tokens: 200,
            sourceIDs: ["u6"],
            agents: []
        )
        let sources = (1...5).map { source(id: "u\($0)", machine: "shared-linux", osUser: "user\($0)", status: "ok") }
            + [source(id: "u6", machine: "solo-mac", osUser: "carol", status: "ok")]
        let summary = makeSummary(periodID: "today", byMachine: [multiUserMachine, singleUserMachine], sources: sources)

        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "today")

        let multi = try XCTUnwrap(state.serverCards.first { $0.id == "shared-linux" })
        XCTAssertTrue(multi.subtitle.hasPrefix("5 个用户"), "got: \(multi.subtitle)")

        let solo = try XCTUnwrap(state.serverCards.first { $0.id == "solo-mac" })
        XCTAssertTrue(solo.subtitle.hasPrefix("carol"), "got: \(solo.subtitle)")
    }

    // MARK: - sharePercentText 精确 + onlineServerCount 只数在线机器

    func testSharePercentTextAndOnlineServerCountExcludeFullyStaleMachines() throws {
        let machineA = MobileBreakdownRow(id: "m-a", label: "m-a", tokens: 300, sourceIDs: ["a1"], agents: [])
        let machineB = MobileBreakdownRow(id: "m-b", label: "m-b", tokens: 700, sourceIDs: ["b1"], agents: [])
        let machineC = MobileBreakdownRow(id: "m-c", label: "m-c", tokens: 0, sourceIDs: ["c1"], agents: [])
        let sources = [
            source(id: "a1", machine: "m-a", osUser: "alice", status: "ok"),
            source(id: "b1", machine: "m-b", osUser: "bob", status: "ok"),
            source(id: "c1", machine: "m-c", osUser: "carol", status: "stale"),
        ]
        let summary = makeSummary(periodID: "today", totalTokens: 1000, byMachine: [machineA, machineB, machineC], sources: sources)

        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "today")

        let cardA = try XCTUnwrap(state.serverCards.first { $0.id == "m-a" })
        let cardB = try XCTUnwrap(state.serverCards.first { $0.id == "m-b" })
        let cardC = try XCTUnwrap(state.serverCards.first { $0.id == "m-c" })
        XCTAssertEqual(cardA.sharePercentText, "30%")
        XCTAssertEqual(cardB.sharePercentText, "70%")
        XCTAssertEqual(cardC.sharePercentText, "0%")
        XCTAssertTrue(cardA.isOnline)
        XCTAssertTrue(cardB.isOnline)
        XCTAssertFalse(cardC.isOnline)

        // 3 台机器，1 台（m-c）全部 source 都 stale → 在线数 2。
        XCTAssertEqual(state.onlineServerCount, 2)
    }

    // MARK: - 月视图：列头文案（#180：周均换算连同 ModelQuotaEstimator 一起删除，等待服务端校准；
    // 原先覆盖 weeklyAveraged/countedDaysForMonth 边界情况的 5 个测试——
    // testMonthHeaderTextAndWeeklyAveragedQuotaForFullMonth / testMonthInProgressCountsOnlyElapsedDaysUpToNow /
    // testMonthWithoutStartDateShowsDashInsteadOfUnadjustedCumulativeNumber /
    // testMonthWithClockSkewBeforeStartDateShowsDashInsteadOfInflatedNumber /
    // testHistoricalFullMonthCountedDaysCapAtPeriodEndDateNotTodaysDate ——随实现一起删除：
    // 它们验证的换算逻辑已不存在，继续保留就是在测试死代码。列头文案本身还在，用下面这一个测试覆盖三种周期。）

    func testHeaderTextIsWeeklyDirectPhraseForDayAndWeekAndWeeklyAveragedPhraseForMonth() throws {
        let row = MobileBreakdownRow(id: "m-a", label: "m-a", tokens: 100, sourceIDs: [], agents: [])
        let weekSummary = makeSummary(periodID: "week", byMachine: [row], sources: [])
        XCTAssertEqual(
            MenuBarViewModel.build(from: weekSummary, selectedPeriodID: "week").serverModelQuotaHeader,
            "周额度"
        )
        let todaySummary = makeSummary(periodID: "today", byMachine: [row], sources: [])
        XCTAssertEqual(
            MenuBarViewModel.build(from: todaySummary, selectedPeriodID: "today").serverModelQuotaHeader,
            "周额度"
        )
        let monthSummary = makeSummary(periodID: "month", byMachine: [row], sources: [])
        XCTAssertEqual(
            MenuBarViewModel.build(from: monthSummary, selectedPeriodID: "month").serverModelQuotaHeader,
            "周均额度"
        )
    }

    // MARK: - 独立 Opus 审查追加 #2：非 available 状态的模型一律「—」，不论挂哪个 Agent

    func testNonAvailableModelStatusAlwaysShowsDashRegardlessOfAgentAndCarriesStatusField() throws {
        let machineRow = MobileBreakdownRow(
            id: "mac-1",
            label: "mac-1",
            tokens: 1_000,
            sourceIDs: ["src-1"],
            agents: [
                MobileSourceAgent(id: "codex", label: "Codex", tokens: 1_000, status: "available", models: [
                    MobileSourceModel(id: "unknown", label: "模型未知", tokens: 1_000, status: "missing"),
                ]),
            ]
        )
        let summary = makeSummary(periodID: "today", byMachine: [machineRow], sources: [
            source(id: "src-1", machine: "mac-1", osUser: "alice", status: "ok")
        ])

        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "today")
        let card = try XCTUnwrap(state.serverCards.first { $0.id == "mac-1" })
        let row = try XCTUnwrap(card.models.first)

        XCTAssertEqual(row.status, "missing")
        // #180：quotaText 现在恒为「—」；这里额外确认 status != "available" 时依然如此（不因 Agent 不同而变化）。
        XCTAssertEqual(row.quotaText, "—")
    }

    // MARK: - 独立 Opus 审查追加 #3：owner fixture 集成断言（数值从原始 JSON 独立复算，不调被测 helper）

    func testOwnerFixtureServerCardsMatchValuesIndependentlyReadFromRawJSON() throws {
        // fixture 实际内容（已直接读取 Tests/AIUsageMenuBarCoreTests/Fixtures/navigation-models-owner.json 核对）：
        // period.total_tokens = 1000；by_machine: "mac"(650, source_ids=[model-mac]), "linux"(350, source_ids=[model-linux])。
        // mac: claude agent { claude-opus: 300, status available }；codex agent { gpt-6-luna: 200, gpt-6-sol: 100, unknown: 50(status missing) }。
        // linux: claude agent { tokens 0, status missing, models: [] }；codex agent 同 mac 的 codex 明细。
        // sources: model-mac(machine mac, os_user alice, status ok)、model-linux(machine linux, os_user alice, status ok)。
        let url = try XCTUnwrap(Bundle.module.url(forResource: "navigation-models-owner", withExtension: "json"))
        let summary = try JSONDecoder().decode(MobileSummary.self, from: Data(contentsOf: url))

        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "today")

        // 结构下限：卡片数、每张卡的行数精确断言。
        XCTAssertEqual(state.serverCards.count, 2)
        let mac = try XCTUnwrap(state.serverCards.first { $0.id == "mac" })
        let linux = try XCTUnwrap(state.serverCards.first { $0.id == "linux" })
        XCTAssertEqual(mac.models.count, 4)
        XCTAssertEqual(linux.models.count, 3)

        // mac 卡按 tokens 降序：claude-opus(300) > gpt-6-luna(200) > gpt-6-sol(100) > unknown(50)。
        XCTAssertEqual(mac.models.map(\.modelLabel), ["claude-opus", "gpt-6-luna", "gpt-6-sol", "模型未知"])
        XCTAssertEqual(mac.models.map(\.tokens), [300, 200, 100, 50])

        // #180：客户端估算已暂停（等待服务端校准），quotaText 一律「—」——不论 Agent、不论 status。
        XCTAssertEqual(mac.models[0].quotaText, "—")
        XCTAssertEqual(mac.models[1].quotaText, "—")
        XCTAssertEqual(mac.models[2].quotaText, "—")
        XCTAssertEqual(mac.models[3].status, "missing")
        XCTAssertEqual(mac.models[3].quotaText, "—")

        XCTAssertEqual(linux.models.map(\.modelLabel), ["gpt-6-luna", "gpt-6-sol", "模型未知"])
        XCTAssertEqual(linux.models.map(\.tokens), [200, 100, 50])
        XCTAssertEqual(linux.models[0].quotaText, "—")
        XCTAssertEqual(linux.models[1].quotaText, "—")
        XCTAssertEqual(linux.models[2].status, "missing")
        XCTAssertEqual(linux.models[2].quotaText, "—")

        // sharePercentText：period.total_tokens = 1000；mac 650 → 65%，linux 350 → 35%。
        XCTAssertEqual(mac.sharePercentText, "65%")
        XCTAssertEqual(linux.sharePercentText, "35%")

        // 两台机器对应的 source 都是 status="ok" → 在线数 2。
        XCTAssertEqual(state.onlineServerCount, 2)
    }

    // MARK: - 独立 Opus 审查追加 #4：机器别名优先按 row.id（机器原名）查找

    func testMachineAliasLooksUpRawMachineIDBeforeFormattingPrettyLabel() throws {
        let machineRow = MobileBreakdownRow(
            id: "host-a",
            label: "Pretty A",
            tokens: 100,
            sourceIDs: ["src-1"],
            agents: []
        )
        let summary = makeSummary(periodID: "today", byMachine: [machineRow], sources: [
            source(id: "src-1", machine: "host-a", osUser: "alice", status: "ok")
        ])
        let aliases = ["host-a": "工作机"]

        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "today", machineAliases: aliases)
        let card = try XCTUnwrap(state.serverCards.first { $0.id == "host-a" })

        // aliases 的 key 是机器原名 "host-a"，不是 breakdown 里已经美化过的 label "Pretty A"；
        // 现有 formatMachineName(row.label, aliases:) 查的是 label，查不到会原样返回 "Pretty A"。
        XCTAssertEqual(card.title, "工作机")
    }

    // MARK: - 迁移自已删除的 SourceHierarchyTests：byMachine 优先于 byOSUser 回退，且不对 contributions 求和

    func testFallbackPrefersByMachineOverByOSUserAndDoesNotSumContributions() throws {
        for usesMachine in [true, false] {
            let row = MobileBreakdownRow(
                id: "server-aggregate",
                label: "已汇总来源",
                tokens: 777,
                sourceIDs: ["s1", "s2"],
                contributions: [
                    MobileBreakdownContribution(sourceID: "s1", tokens: 10),
                    MobileBreakdownContribution(sourceID: "s2", tokens: 20),
                ]
            )
            let summary = makeSummary(
                periodID: "today",
                byMachine: usesMachine ? [row] : [],
                byOSUser: usesMachine ? [] : [row],
                sources: [
                    source(id: "s1", machine: "server-aggregate", osUser: "alice", status: "ok"),
                    source(id: "s2", machine: "server-aggregate", osUser: "bob", status: "ok"),
                ]
            )

            let cards = MenuBarViewModel.build(from: summary, selectedPeriodID: "today").serverCards
            XCTAssertEqual(cards.count, 1, "usesMachine=\(usesMachine)")
            XCTAssertEqual(cards.first?.id, "server-aggregate", "usesMachine=\(usesMachine)")
            // 值必须取 row.tokens 本身（777），不是把 contributions 加总（10+20=30）。
            XCTAssertEqual(cards.first?.valueText, "777", "usesMachine=\(usesMachine)")
            // byOSUser 回退路径（hasModelDetail 只看 byMachine 是否非空）没有模型明细，不能凭空造出模型行。
            XCTAssertTrue(cards.first?.models.isEmpty == true, "usesMachine=\(usesMachine)")
        }
    }

    // MARK: - 迁移自已删除的 SourceHierarchyTests：机器别名回退到 formatMachineName(label) 并剥离 .local 后缀

    func testMachineAliasFallsBackToFormattedLabelWhenRawIDMissesAlias() throws {
        let machineRow = MobileBreakdownRow(
            id: "host-raw-id",
            label: "mymachine.local",
            tokens: 100,
            sourceIDs: ["src-1"],
            agents: []
        )
        let summary = makeSummary(periodID: "today", byMachine: [machineRow], sources: [
            source(id: "src-1", machine: "host-raw-id", osUser: "alice", status: "ok")
        ])
        // aliases 里没有 "host-raw-id"（row.id 原名），只有剥离 ".local" 后缀后的 "mymachine"。
        let aliases = ["mymachine": "工作站"]

        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "today", machineAliases: aliases)
        let card = try XCTUnwrap(state.serverCards.first { $0.id == "host-raw-id" })

        XCTAssertEqual(card.title, "工作站")
    }

    // MARK: - Fixtures

    private func makeSummary(
        periodID: String,
        startDate: String? = nil,
        endDate: String? = nil,
        totalTokens: Int? = nil,
        byMachine: [MobileBreakdownRow],
        byOSUser: [MobileBreakdownRow] = [],
        sources: [MobileSource]
    ) -> MobileSummary {
        let resolvedTotal = totalTokens ?? (byMachine + byOSUser).reduce(0) { $0 + $1.tokens }
        return MobileSummary(
            schemaVersion: 1,
            client: "macos",
            generatedAt: "2026-09-26T12:00:00+08:00",
            timezone: "Asia/Shanghai",
            period: MobilePeriod(
                id: periodID,
                date: periodID == "today" ? "2026-09-26" : nil,
                startDate: startDate,
                endDate: endDate,
                totalTokens: resolvedTotal,
                inputTokens: resolvedTotal,
                outputTokens: 0,
                cacheTokens: 0,
                cacheRatio: 0,
                machine: nil,
                account: nil
            ),
            trend: MobileTrend(period: periodID, granularity: "day", startDate: startDate, endDate: endDate, points: []),
            sources: sources,
            breakdown: MobileBreakdown(byMachine: byMachine, byOSUser: byOSUser, byAgent: [], byModel: [], byDate: []),
            limits: MobileLimits(observedCount: 0, totalCount: 0, windows: [])
        )
    }

    private func source(id: String, machine: String, osUser: String, status: String) -> MobileSource {
        MobileSource(
            sourceID: id,
            machine: machine,
            osUser: osUser,
            platform: "linux",
            displayName: nil,
            status: status,
            lastObservedAt: "2026-09-26T11:00:00+08:00",
            lastPushedAt: "2026-09-26T11:00:00+08:00",
            errorMessage: nil
        )
    }

    private func isoDate(_ iso: String) throws -> Date {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let value = formatter.date(from: iso) {
            return value
        }
        formatter.formatOptions = [.withInternetDateTime]
        return try XCTUnwrap(formatter.date(from: iso))
    }
}
