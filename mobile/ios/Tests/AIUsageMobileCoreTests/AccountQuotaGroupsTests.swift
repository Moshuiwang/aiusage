import Foundation
import XCTest
@testable import AIUsageMobileCore

/// #287：额度按账户分组。fixture 由 Worker 产出（npm run cf:golden:gen），与 macOS 份逐字节相同，不手改。
final class AccountQuotaGroupsTests: XCTestCase {
    private func summary(scenario: String) throws -> MobileSummary {
        let fixtureURL = try XCTUnwrap(Bundle.module.url(forResource: "provider-slots-owner-fixture", withExtension: "json"))
        let records = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: fixtureURL)) as? [[String: Any]])
        let record = try XCTUnwrap(records.first { $0["name"] as? String == "\(scenario):mobile-summary" })
        let baseURL = try XCTUnwrap(Bundle.module.url(forResource: "mobile-summary", withExtension: "json"))
        var base = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: baseURL)) as? [String: Any])
        base["account_slots"] = record["account_slots"]
        return try JSONDecoder().decode(MobileSummary.self, from: JSONSerialization.data(withJSONObject: base))
    }

    func testEachAccountGetsItsOwnQuotaGroupWithPlan() throws {
        let groups = limitGroups(for: try summary(scenario: "17-multi-account-plan-change"))
        XCTAssertEqual(groups.count, 4) // 结构下限：Claude×2 + OpenAI + Antigravity
        XCTAssertEqual(groups.map(\.provider), ["claude", "claude", "codex", "antigravity"])
        XCTAssertEqual(groups.map(\.accountLabel), ["Tony", "Zhipeng", "Em", nil])
        XCTAssertEqual(groups.map(\.accountPlanLabel), ["Max 20x", "Max 5x", "Pro", nil])
        XCTAssertEqual(groups.map { $0.windows.map(\.usedPercent) }, [[10], [82], [55], [5]])
        XCTAssertEqual(Set(groups.map(\.id)).count, 4)
    }

    func testUnavailableAccountIsNotShownAsQuota() throws {
        // 07：provider_failed 晚于成功 → 当前不可用，不能出现在额度分组里。
        let groups = limitGroups(for: try summary(scenario: "07-provider-failed-after-success"))
        XCTAssertFalse(groups.contains { $0.provider == "claude" })
    }

    func testOldServerWithoutAccountSlotsFallsBackToLimitWindows() throws {
        let baseURL = try XCTUnwrap(Bundle.module.url(forResource: "mobile-summary", withExtension: "json"))
        let legacy = try JSONDecoder().decode(MobileSummary.self, from: Data(contentsOf: baseURL))
        XCTAssertTrue(legacy.accountSlots.isEmpty)
        XCTAssertEqual(limitGroups(for: legacy), limitGroups(from: legacy.limits.windows))
    }
}
