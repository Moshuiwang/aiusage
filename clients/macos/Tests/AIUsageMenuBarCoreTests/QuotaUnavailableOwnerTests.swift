import Foundation
import XCTest
@testable import AIUsageMenuBarCore

final class QuotaUnavailableOwnerTests: XCTestCase {
    func testRealWorkerFixtureDecodesAndShowsEightRowsWithTruthfulTexts() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "quota-unavailable-owner", withExtension: "json"))
        let summary = try JSONDecoder().decode(MobileSummary.self, from: Data(contentsOf: url))
        let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "week",
            deviceTimeZone: TimeZone(identifier: "Asia/Shanghai")!)
        XCTAssertEqual(state.serverCards.count, 1)
        let rows = state.serverCards[0].models
        XCTAssertEqual(rows.count, 8)
        XCTAssertEqual(rows.reduce(0) { $0 + $1.tokens }, 7200)
        let expected = ["gpt-6-sol": "未达标", "gpt-6-luna": "数据不足",
            "claude-sonnet-5": "已过期", "claude-haiku-5": "未校准", "claude-fable-5": "未校准",
            "unmapped-model": "—", "unknown": "—", "claude-opus-5": "≈<0.1%"]
        XCTAssertEqual(Set(rows.map(\.modelID)), Set(expected.keys))
        for row in rows { XCTAssertEqual(row.quotaText, expected[row.modelID], row.modelID) }
        let failed = try XCTUnwrap(rows.first { $0.modelID == "gpt-6-sol" })
        // #271：Worker v2 不再下发 backtest_max_error，提示退化为不带误差数字的形式。
        XCTAssertEqual(failed.quotaHelpText, "换算回测未通过，92个区间；暂不估算")
        let decoded = try XCTUnwrap(summary.breakdown.byMachine[0].agents?
            .flatMap(\.models).first { $0.id == "gpt-6-sol" })
        XCTAssertEqual(decoded.quotaEstimateUnavailable?.reason, "backtest_failed")
        XCTAssertEqual(decoded.quotaEstimateUnavailable?.sampleIntervals, 92)
        XCTAssertNil(decoded.quotaEstimateUnavailable?.backtestMaxError)
        XCTAssertNil(decoded.quotaEstimate)
    }

    func testUnknownReasonAndMissingModelDoNotClaimKnownCalibrationStatus() throws {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "quota-unavailable-owner", withExtension: "json"))
        let data = try Data(contentsOf: url)
        for (status, reason) in [("available", "future-reason"), ("missing", "backtest_failed")] {
            var root = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
            var breakdown = root["breakdown"] as! [String: Any]
            var machines = breakdown["by_machine"] as! [[String: Any]]
            var agents = machines[0]["agents"] as! [[String: Any]]
            let codex = try XCTUnwrap(agents.firstIndex { $0["id"] as? String == "codex" })
            var models = agents[codex]["models"] as! [[String: Any]]
            let index = try XCTUnwrap(models.firstIndex { $0["id"] as? String == "gpt-6-sol" })
            models[index]["status"] = status
            models[index]["quota_estimate_unavailable"] = ["reason": reason, "sample_intervals": 92, "backtest_max_error": 2.306]
            agents[codex]["models"] = models
            machines[0]["agents"] = agents
            breakdown["by_machine"] = machines
            root["breakdown"] = breakdown
            let summary = try JSONDecoder().decode(MobileSummary.self, from: JSONSerialization.data(withJSONObject: root))
            let state = MenuBarViewModel.build(from: summary, selectedPeriodID: "week",
                deviceTimeZone: TimeZone(identifier: "Asia/Shanghai")!)
            let row = try XCTUnwrap(state.serverCards.first?.models.first { $0.modelID == "gpt-6-sol" })
            XCTAssertEqual(row.quotaText, "—")
            XCTAssertEqual(row.quotaHelpText, "校准中或数据不足，暂不估算")
        }
    }
}
