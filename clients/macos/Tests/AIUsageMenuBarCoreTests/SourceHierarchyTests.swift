import Foundation
import XCTest
@testable import AIUsageMenuBarCore

final class SourceHierarchyTests: XCTestCase {
    func testOwnerSourceAgentModelHierarchyPreservesEveryIdentityAndValue() throws {
        let summary = try load("navigation-models-owner")
        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "today")
        let rows = try XCTUnwrap(summary.breakdown.bySource)
        XCTAssertEqual(rows.count, 2)
        XCTAssertEqual(state.sources.map(\.id), ["model-mac", "model-linux"])
        XCTAssertEqual(state.sources.map(\.title), ["alice / mac", "alice / linux"])
        XCTAssertEqual(state.sources.map(\.value), ["650", "350"])
        XCTAssertEqual(state.dateRangeText, "2026-09-22")
        XCTAssertEqual(rows.reduce(0) { $0 + $1.tokens }, summary.period.totalTokens)
        var checkedModels = 0
        for row in rows {
            let presented = try XCTUnwrap(state.sources.first { $0.id == row.id })
            let agents = try XCTUnwrap(presented.agents)
            XCTAssertEqual(agents.count, 2)
            XCTAssertEqual(agents.map(\.id), ["claude", "codex"])
            XCTAssertEqual(agents.reduce(0) { $0 + $1.tokens }, row.tokens)
            for agent in agents {
                XCTAssertEqual(agent.models.reduce(0) { $0 + $1.tokens }, agent.tokens)
                checkedModels += agent.models.count
            }
        }
        XCTAssertEqual(checkedModels, 7)
        let codex = try XCTUnwrap(state.sources.first?.agents?.first { $0.id == "codex" })
        XCTAssertEqual(codex.models.map(\.id), ["gpt-6-luna", "gpt-6-sol", "unknown"])
        XCTAssertEqual(codex.models.map(\.tokens), [200, 100, 50])
        XCTAssertEqual(codex.models.map(\.title), ["gpt-6-luna", "gpt-6-sol", "模型未知"])
        XCTAssertEqual(codex.models.last?.valueText, "50")
        let missing = try XCTUnwrap(state.sources.last?.agents?.first { $0.id == "claude" })
        XCTAssertEqual(missing.status, "missing")
        XCTAssertEqual(missing.valueText, "数据缺失")
        XCTAssertEqual(missing.tokens, 0)
        XCTAssertTrue(missing.models.isEmpty)
    }

    func testOwnerFieldsSurviveDiskCacheRoundTrip() throws {
        let summary = try load("navigation-models-owner")
        let encoded = try JSONEncoder().encode(summary)
        let decoded = try JSONDecoder().decode(MobileSummary.self, from: encoded)
        XCTAssertEqual(decoded.breakdown.bySource?.count, 2)
        XCTAssertEqual(decoded.breakdown.bySource, summary.breakdown.bySource)
        XCTAssertEqual(decoded.breakdown.bySource?.first?.agents?.last?.models.count, 3)
        XCTAssertEqual(decoded.breakdown.bySource?.first?.machine, "mac")
        XCTAssertEqual(decoded.breakdown.bySource?.first?.osUser, "alice")
    }

    func testLegacySummaryKeepsSourceTotalsWithoutInventingAgentDetails() throws {
        let summary = try load("mobile-summary")
        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "week")
        XCTAssertNil(summary.breakdown.bySource)
        XCTAssertEqual(state.sources.count, 2)
        XCTAssertEqual(state.sources.map(\.value), ["3.0K", "2.0K"])
        XCTAssertTrue(state.sources.allSatisfy { $0.agents == nil })
    }

    func testLegacyFallbackUsesMachineThenUserRowsWithoutSummingContributions() throws {
        let original = try load("navigation-models-owner")
        for usesMachine in [true, false] {
            let row = MobileBreakdownRow(id: "server-aggregate", label: "已汇总来源", tokens: 777,
                sourceIDs: ["model-mac", "model-linux"],
                contributions: [MobileBreakdownContribution(sourceID: "model-mac", tokens: 10), MobileBreakdownContribution(sourceID: "model-linux", tokens: 20)])
            let breakdown = MobileBreakdown(byMachine: usesMachine ? [row] : [], byOSUser: usesMachine ? [] : [row], byAgent: [], byModel: [], byDate: [])
            let summary = MobileSummary(schemaVersion: original.schemaVersion, client: original.client, generatedAt: original.generatedAt, timezone: original.timezone, period: original.period, trend: original.trend, sources: original.sources, breakdown: breakdown, limits: original.limits)
            let rows = MenuBarViewModel.build(from: summary, selectedPeriodID: "today").sources
            XCTAssertEqual(rows.count, 1)
            XCTAssertEqual(rows.first?.id, "server-aggregate")
            XCTAssertEqual(rows.first?.title, "已汇总来源")
            XCTAssertEqual(rows.first?.value, "777")
            XCTAssertEqual(rows.first?.subtitle, "来源明细缺失")
            XCTAssertNil(rows.first?.agents)
        }
    }

    func testFlatModelsAreSortedDescendingByTokensAcrossAgents() throws {
        let summary = try load("navigation-models-owner")
        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "today")
        let macSource = try XCTUnwrap(state.sources.first { $0.id == "model-mac" })
        let flatModels = try XCTUnwrap(macSource.flatModels)
        XCTAssertEqual(flatModels.count, 4)
        XCTAssertEqual(flatModels.map(\.tokens), [300, 200, 100, 50])
        XCTAssertEqual(flatModels.first?.label, "claude-opus")
        XCTAssertEqual(flatModels[1].label, "gpt-6-luna")
    }

    /// #175 决策的口径变化会透过薄包装影响到这条旧路径（reviewer 复查发现的回归覆盖缺口）：
    /// Claude Agent 下的非 Claude 系模型不再显示百分比；Codex Agent 下即便模型名像 Claude 也按 Codex 基准计算。
    func testFlatModelsReflectAgentOwnershipDecisionForNonFamilyModelNames() throws {
        let breakdown = MobileBreakdown(
            byMachine: [],
            byOSUser: [],
            byAgent: [],
            byModel: [],
            byDate: [],
            bySource: [
                MobileBreakdownRow(
                    id: "mixed-source",
                    label: "mixed-source",
                    tokens: 5_000_000 + 22_000_000,
                    sourceIDs: ["mixed-source"],
                    agents: [
                        MobileSourceAgent(id: "claude", label: "Claude", tokens: 5_000_000, status: "available", models: [
                            MobileSourceModel(id: "deepseek-v4-pro", label: "DeepSeek V4 Pro", tokens: 5_000_000, status: "available"),
                        ]),
                        MobileSourceAgent(id: "codex", label: "Codex", tokens: 22_000_000, status: "available", models: [
                            MobileSourceModel(id: "claude-mini", label: "claude-mini", tokens: 22_000_000, status: "available"),
                        ]),
                    ]
                ),
            ]
        )
        let original = try load("navigation-models-owner")
        let summary = MobileSummary(
            schemaVersion: original.schemaVersion,
            client: original.client,
            generatedAt: original.generatedAt,
            timezone: original.timezone,
            period: original.period,
            trend: original.trend,
            sources: original.sources,
            breakdown: breakdown,
            limits: original.limits
        )

        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "today")
        let source = try XCTUnwrap(state.sources.first { $0.id == "mixed-source" })
        let flatModels = try XCTUnwrap(source.flatModels)
        XCTAssertEqual(flatModels.count, 2)

        // Claude Agent 下的 deepseek-v4-pro：不是 Claude 系模型名，决策为不计入 Claude 周额度。
        let deepseek = try XCTUnwrap(flatModels.first { $0.modelID == "deepseek-v4-pro" })
        XCTAssertNil(deepseek.quotaWeeklyPercentText)

        // Codex Agent 下的 claude-mini：Agent 归属优先于模型名，按 Codex 基准（22M/22M=1.0）计算，不是「未知」。
        let claudeMiniUnderCodex = try XCTUnwrap(flatModels.first { $0.modelID == "claude-mini" })
        XCTAssertEqual(claudeMiniUnderCodex.quotaWeeklyPercentText, "约占周额度 1.0%")
    }

    func testCustomMachineAliasesReplaceLongHostnames() throws {
        let summary = try load("navigation-models-owner")
        let aliases = ["mac": "MacBook Air", "linux": "GPU Server"]
        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "today", machineAliases: aliases)
        XCTAssertEqual(state.sources.map(\.title), ["alice / MacBook Air", "alice / GPU Server"])
    }

    private func load(_ name: String) throws -> MobileSummary {
        let url = try XCTUnwrap(Bundle.module.url(forResource: name, withExtension: "json"))
        return try JSONDecoder().decode(MobileSummary.self, from: Data(contentsOf: url))
    }
}
