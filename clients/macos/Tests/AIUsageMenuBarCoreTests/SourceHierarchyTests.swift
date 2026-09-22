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

    private func load(_ name: String) throws -> MobileSummary {
        let url = try XCTUnwrap(Bundle.module.url(forResource: name, withExtension: "json"))
        return try JSONDecoder().decode(MobileSummary.self, from: Data(contentsOf: url))
    }
}
