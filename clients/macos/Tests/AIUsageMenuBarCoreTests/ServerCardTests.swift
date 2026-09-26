import Foundation
import XCTest
@testable import AIUsageMenuBarCore

/// #175：Server 展开后按模型显示「占所属提供方周额度」。
final class ServerCardTests: XCTestCase {

    // MARK: - 一台机器混用 Claude / Codex，各自按自己的 Agent 基准计算

    func testServerCardModelRowsUseAgentOwnershipForQuotaAndExcludeZeroTokenModelsSortedDescending() throws {
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

        // 独立复算：claude-opus-5 属于 Claude Agent，opus 权重 5x。
        let claudeRow = card.models[0]
        XCTAssertEqual(claudeRow.modelLabel, "Claude Opus 5")
        XCTAssertEqual(claudeRow.agentID, "claude")
        let claudePercent = Double(23_000_000) * 5.0 / 115_000_000.0 // = 1.0
        XCTAssertEqual(claudeRow.quotaText, String(format: "%.1f%%", claudePercent))

        // 独立复算：gpt-5.6-sol 属于 Codex Agent，Sol 权重 1x。
        let codexRow = card.models[1]
        XCTAssertEqual(codexRow.modelLabel, "GPT-5.6 Sol")
        XCTAssertEqual(codexRow.agentID, "codex")
        let codexPercent = Double(11_000_000) * 1.0 / 22_000_000.0 // = 0.5
        XCTAssertEqual(codexRow.quotaText, String(format: "%.1f%%", codexPercent))

        // deepseek-v4-pro 挂在 claude agent 下但不是 Claude 系模型，决策为不计入 Claude 周额度。
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
        // 独立复算：claude-opus 在 antigravity 通道内按 5x 权重、Gemini Flash 等价基准折算。
        let percent = Double(10_000_000) * 5.0 / 10_000_000.0 // = 5.0
        // #177 真机反馈：quotaText 不再带 Agent 名（色点已表明归属），只留百分比数字。
        XCTAssertEqual(row.quotaText, String(format: "%.1f%%", percent))
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

    // MARK: - 月视图：列头文案 + 周均换算

    func testDayAndWeekHeaderTextIsWeeklyDirectPhrase() throws {
        let row = MobileBreakdownRow(id: "m-a", label: "m-a", tokens: 100, sourceIDs: [], agents: [])
        let summary = makeSummary(periodID: "week", byMachine: [row], sources: [])
        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "week")
        XCTAssertEqual(state.serverModelQuotaHeader, "周额度")
    }

    func testMonthHeaderTextAndWeeklyAveragedQuotaForFullMonth() throws {
        // claude-opus-5, 30 亿 tokens：直接估算 = 3,000,000,000*5/115,000,000 = 130.434...%，超过 100%。
        let claudeTokens = 3_000_000_000
        let machineRow = MobileBreakdownRow(
            id: "mac-1",
            label: "mac-1",
            tokens: claudeTokens,
            sourceIDs: ["src-1"],
            agents: [
                MobileSourceAgent(id: "claude", label: "Claude", tokens: claudeTokens, status: "available", models: [
                    MobileSourceModel(id: "claude-opus-5", label: "Claude Opus 5", tokens: claudeTokens, status: "available"),
                ]),
            ]
        )
        let summary = makeSummary(
            periodID: "month",
            startDate: "2026-09-01",
            endDate: "2026-09-30",
            byMachine: [machineRow],
            sources: [source(id: "src-1", machine: "mac-1", osUser: "alice", status: "ok")]
        )
        let now = try isoDate("2026-09-30T23:00:00+08:00")

        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "month", now: now)

        XCTAssertEqual(state.serverModelQuotaHeader, "周均额度")

        let card = try XCTUnwrap(state.serverCards.first { $0.id == "mac-1" })
        let row = try XCTUnwrap(card.models.first)

        let directPercent = Double(claudeTokens) * 5.0 / 115_000_000.0
        XCTAssertGreaterThan(directPercent, 100, "直接估算必须先超过 100% 才能验证换算生效")

        // 已计天数：9 月整月 = 30 天（含首尾），周均除数 = 30/7。
        let countedDays = 30.0
        let expectedWeeklyPercent = directPercent / (countedDays / 7.0)
        XCTAssertEqual(row.quotaText, String(format: "%.1f%%", expectedWeeklyPercent))
        XCTAssertFalse(row.quotaText.contains(String(format: "%.1f", directPercent)))
    }

    func testMonthInProgressCountsOnlyElapsedDaysUpToNow() throws {
        // claude-sonnet-5, 1.15 亿 tokens：直接估算 = 115,000,000/115,000,000 = 1.0（显示为 "1.0%"）。
        let claudeTokens = 115_000_000
        let machineRow = MobileBreakdownRow(
            id: "mac-1",
            label: "mac-1",
            tokens: claudeTokens,
            sourceIDs: ["src-1"],
            agents: [
                MobileSourceAgent(id: "claude", label: "Claude", tokens: claudeTokens, status: "available", models: [
                    MobileSourceModel(id: "claude-sonnet-5", label: "Claude Sonnet 5", tokens: claudeTokens, status: "available"),
                ]),
            ]
        )
        let summary = makeSummary(
            periodID: "month",
            startDate: "2026-09-01",
            endDate: "2026-09-30",
            byMachine: [machineRow],
            sources: [source(id: "src-1", machine: "mac-1", osUser: "alice", status: "ok")]
        )
        // 现在是月中第 10 天（含首尾从 09-01 到 09-10 共 10 天）。
        let now = try isoDate("2026-09-10T08:00:00+08:00")

        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "month", now: now)
        let card = try XCTUnwrap(state.serverCards.first { $0.id == "mac-1" })
        let row = try XCTUnwrap(card.models.first)

        let directPercent = Double(claudeTokens) * 1.0 / 115_000_000.0 // = 1.0
        let countedDays = 10.0
        let expectedWeeklyPercent = directPercent / (countedDays / 7.0) // = 0.7
        XCTAssertEqual(row.quotaText, String(format: "%.1f%%", expectedWeeklyPercent))
    }

    // MARK: - 月视图：已计天数不可靠时不产出误导性数字（reviewer 复查发现的回退路径缺口）

    func testMonthWithoutStartDateShowsDashInsteadOfUnadjustedCumulativeNumber() throws {
        let claudeTokens = 23_000_000
        let machineRow = MobileBreakdownRow(
            id: "mac-1",
            label: "mac-1",
            tokens: claudeTokens,
            sourceIDs: ["src-1"],
            agents: [
                MobileSourceAgent(id: "claude", label: "Claude", tokens: claudeTokens, status: "available", models: [
                    MobileSourceModel(id: "claude-opus-5", label: "Claude Opus 5", tokens: claudeTokens, status: "available"),
                ]),
            ]
        )
        // 故意不给 startDate：不能算出可靠的「已计天数」。
        let summary = makeSummary(
            periodID: "month",
            startDate: nil,
            endDate: nil,
            byMachine: [machineRow],
            sources: [source(id: "src-1", machine: "mac-1", osUser: "alice", status: "ok")]
        )

        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "month")
        let card = try XCTUnwrap(state.serverCards.first { $0.id == "mac-1" })
        let row = try XCTUnwrap(card.models.first)

        // 缺 startDate 时不能猜一个换算基准，必须显示「—」，而不是把月累计当周额度直接展示。
        XCTAssertEqual(row.quotaText, "—")
    }

    func testMonthWithClockSkewBeforeStartDateShowsDashInsteadOfInflatedNumber() throws {
        let claudeTokens = 11_500_000 // 直接估算 = 0.1
        let machineRow = MobileBreakdownRow(
            id: "mac-1",
            label: "mac-1",
            tokens: claudeTokens,
            sourceIDs: ["src-1"],
            agents: [
                MobileSourceAgent(id: "claude", label: "Claude", tokens: claudeTokens, status: "available", models: [
                    MobileSourceModel(id: "claude-sonnet-5", label: "Claude Sonnet 5", tokens: claudeTokens, status: "available"),
                ]),
            ]
        )
        let summary = makeSummary(
            periodID: "month",
            startDate: "2026-09-01",
            endDate: "2026-09-30",
            byMachine: [machineRow],
            sources: [source(id: "src-1", machine: "mac-1", osUser: "alice", status: "ok")]
        )
        // 时钟偏差：now 早于 period.start_date。旧实现会被 max(days+1, 1) 夹成 1 天，
        // 除数变成 1/7，把占比放大 7 倍——必须显示「—」而不是一个被放大的误导数字。
        let now = try isoDate("2026-08-25T08:00:00+08:00")

        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "month", now: now)
        let card = try XCTUnwrap(state.serverCards.first { $0.id == "mac-1" })
        let row = try XCTUnwrap(card.models.first)

        XCTAssertEqual(row.quotaText, "—")
    }

    // MARK: - 独立 Opus 审查追加 #1：历史整月天数上限（period.end_date 封顶，不是 now 所在日期）

    func testHistoricalFullMonthCountedDaysCapAtPeriodEndDateNotTodaysDate() throws {
        let claudeTokens = 3_000_000_000
        let machineRow = MobileBreakdownRow(
            id: "mac-1",
            label: "mac-1",
            tokens: claudeTokens,
            sourceIDs: ["src-1"],
            agents: [
                MobileSourceAgent(id: "claude", label: "Claude", tokens: claudeTokens, status: "available", models: [
                    MobileSourceModel(id: "claude-opus-5", label: "Claude Opus 5", tokens: claudeTokens, status: "available"),
                ]),
            ]
        )
        let summary = makeSummary(
            periodID: "month",
            startDate: "2026-09-01",
            endDate: "2026-09-30",
            byMachine: [machineRow],
            sources: [source(id: "src-1", machine: "mac-1", osUser: "alice", status: "ok")]
        )
        // 查看的是已经结束的历史月份：now 已经是下个月中旬。已计天数必须封顶在 period.end_date（30 天），
        // 不能用 now 所在日期（10-15）算出 9/1～10/15 共 45 天。
        let now = try isoDate("2026-10-15T08:00:00+08:00")

        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "month", now: now)
        let card = try XCTUnwrap(state.serverCards.first { $0.id == "mac-1" })
        let row = try XCTUnwrap(card.models.first)

        let directPercent = Double(claudeTokens) * 5.0 / 115_000_000.0
        let countedDays = 30.0 // 9 月整月（含首尾），不是到 10-15 的 45 天
        let expectedWeeklyPercent = directPercent / (countedDays / 7.0)
        XCTAssertEqual(row.quotaText, String(format: "%.1f%%", expectedWeeklyPercent))
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
        // 当前实现会算出一个非零百分比（"Codex < 0.1%"）；status != "available" 时必须一律「—」。
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

        // 独立复算（用 Issue 背景里记录的换算常数字面值，不调用 ModelQuotaEstimator）：
        // claude-opus 挂 claude agent，opus 权重 5x，Claude 基准 1.15 亿：300*5/115,000,000 ≈ 0.0000130%，< 0.05 门限 → "< 0.1%"。
        XCTAssertEqual(mac.models[0].quotaText, "< 0.1%")
        // gpt-6-luna / gpt-6-sol 模型名含 "gpt-6"，挂 codex agent，权重 3x，Codex 基准 2200 万：都 < 0.05 门限。
        XCTAssertEqual(mac.models[1].quotaText, "< 0.1%")
        XCTAssertEqual(mac.models[2].quotaText, "< 0.1%")
        // unknown 行 status="missing"（非 available），不论算出来多少都必须是「—」。
        XCTAssertEqual(mac.models[3].status, "missing")
        XCTAssertEqual(mac.models[3].quotaText, "—")

        XCTAssertEqual(linux.models.map(\.modelLabel), ["gpt-6-luna", "gpt-6-sol", "模型未知"])
        XCTAssertEqual(linux.models.map(\.tokens), [200, 100, 50])
        XCTAssertEqual(linux.models[0].quotaText, "< 0.1%")
        XCTAssertEqual(linux.models[1].quotaText, "< 0.1%")
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
