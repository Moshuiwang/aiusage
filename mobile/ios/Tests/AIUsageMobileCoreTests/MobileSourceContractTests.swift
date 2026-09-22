import Foundation
import XCTest
@testable import AIUsageMobileCore

final class MobileSourceContractTests: XCTestCase {
    func testOwnerProducedSourceAgentAndModelContractPreservesEveryLevel() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "navigation-models-owner", withExtension: "json"))
        let data = try Data(contentsOf: url)
        let summary = try JSONDecoder().decode(MobileSummary.self, from: data)
        let state = MobileViewModel.build(from: summary)
        let rows = SourcesDisplayState.rows(in: state.breakdown)
        XCTAssertEqual(rows.map(\.id), ["model-mac", "model-linux"])
        XCTAssertEqual(rows.map(\.tokens), [650, 350])
        XCTAssertEqual(rows.map(\.osUser), ["alice", "alice"])
        XCTAssertEqual(rows.map(\.machine), ["mac", "linux"])
        XCTAssertEqual(rows.map { $0.agents?.count }, [2, 2])
        let agents = rows.flatMap { $0.agents ?? [] }
        XCTAssertEqual(agents.count, 4)
        let models = agents.flatMap(\.models)
        XCTAssertEqual(models.count, 7)
        XCTAssertEqual(Set(models.map(\.id)), Set(["gpt-6-sol", "gpt-6-luna", "claude-opus", "unknown"]))
        let linuxClaude = try XCTUnwrap(rows[1].agents?.first { $0.id == "claude" })
        XCTAssertEqual(linuxClaude.status, "missing")
        XCTAssertEqual(linuxClaude.usageText, "数据缺失")
        let unknown = models.filter { $0.id == "unknown" }
        XCTAssertEqual(unknown.count, 2)
        XCTAssertEqual(unknown.map(\.displayLabel), ["模型未知", "模型未知"])
        XCTAssertEqual(unknown.map(\.usageText), ["50", "50"])

        // Independently recompute each layer from the final owner-produced JSON.
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let breakdown = try XCTUnwrap(object["breakdown"] as? [String: Any])
        let rawRows = try XCTUnwrap(breakdown["by_source"] as? [[String: Any]])
        XCTAssertEqual(rawRows.count, 2)
        XCTAssertEqual(rawRows.reduce(0) { $0 + ($1["tokens"] as? Int ?? -999) }, 1000)
        for (index, row) in rawRows.enumerated() {
            let rawAgents = try XCTUnwrap(row["agents"] as? [[String: Any]])
            XCTAssertEqual(rawAgents.count, 2)
            XCTAssertEqual(rawAgents.reduce(0) { $0 + ($1["tokens"] as? Int ?? -999) }, rows[index].tokens)
            for agent in rawAgents {
                let rawModels = try XCTUnwrap(agent["models"] as? [[String: Any]])
                XCTAssertEqual(rawModels.reduce(0) { $0 + ($1["tokens"] as? Int ?? -999) }, agent["tokens"] as? Int)
            }
        }
        let roundTrip = try JSONDecoder().decode(MobileSummary.self, from: JSONEncoder().encode(summary))
        XCTAssertEqual(roundTrip.breakdown.bySource, rows)
    }

    func testOldDTOShowsOnlyOriginalTotalsWithMissingDetails() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "mobile-summary", withExtension: "json"))
        let summary = try JSONDecoder().decode(MobileSummary.self, from: Data(contentsOf: url))
        let rows = SourcesDisplayState.rows(in: summary.breakdown)
        XCTAssertEqual(rows.count, 2)
        XCTAssertEqual(rows.map(\.tokens), [3000, 2000])
        XCTAssertTrue(rows.allSatisfy { $0.agents == nil })
    }
}
