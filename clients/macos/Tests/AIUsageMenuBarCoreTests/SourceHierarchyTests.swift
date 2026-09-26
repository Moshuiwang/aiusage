import Foundation
import XCTest
@testable import AIUsageMenuBarCore

/// #177 收口：本文件原本还覆盖 `state.sources` / `MenuDisplayRow.flatModels` / `MenuFlatModelRow` /
/// `ModelQuotaEstimator.estimateWeeklyQuotaPercentText`（视图层已改用 `state.serverCards` 展示，
/// 这些字段/旧文本 API 随之删除）。等价覆盖已迁移到 `ServerCardTests.swift`
/// （owner 层级、Agent 归属决策、机器别名、月度换算等）和 `ModelQuotaEstimatorTests.swift`
/// （权重估算，改用结构化 `estimateWeeklyQuota` API）。这里只保留与被删 API 无关的
/// `MobileSummary.breakdown.bySource` Codable 往返测试。
final class SourceHierarchyTests: XCTestCase {
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

    private func load(_ name: String) throws -> MobileSummary {
        let url = try XCTUnwrap(Bundle.module.url(forResource: name, withExtension: "json"))
        return try JSONDecoder().decode(MobileSummary.self, from: Data(contentsOf: url))
    }
}
