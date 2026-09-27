import Foundation
import XCTest
@testable import AIUsageMenuBarCore

/// #184：模型行新增可选 `quota_estimate`，缺省（不是 null）表示不可显示，不能影响旧数据解码。
final class MobileSourceModelQuotaEstimateDecodingTests: XCTestCase {

    func testDecodesQuotaEstimateWhenPresent() throws {
        let json = """
        {"id":"claude-opus-5","label":"Claude Opus 5","tokens":1000,"status":"available",
         "quota_estimate":{"percent":2.34,"grade":"A","basis":"week"}}
        """.data(using: .utf8)!

        let model = try JSONDecoder().decode(MobileSourceModel.self, from: json)

        let estimate = try XCTUnwrap(model.quotaEstimate)
        XCTAssertEqual(estimate.percent, 2.34)
        XCTAssertEqual(estimate.grade, "A")
        XCTAssertEqual(estimate.basis, "week")
    }

    func testDecodesToNilWhenFieldIsAbsent() throws {
        // 旧数据/字段缺省场景：没有 quota_estimate 键，不是 null。
        let json = """
        {"id":"claude-opus-5","label":"Claude Opus 5","tokens":1000,"status":"available"}
        """.data(using: .utf8)!

        let model = try JSONDecoder().decode(MobileSourceModel.self, from: json)

        XCTAssertNil(model.quotaEstimate)
    }

    func testMemberwiseInitDefaultsQuotaEstimateToNilForExistingCallSites() {
        // 既有调用点（如 ServerCardTests 里大量 fixture 构造）不传 quotaEstimate 也要能编译通过。
        let model = MobileSourceModel(id: "m", label: "M", tokens: 10, status: "available")

        XCTAssertNil(model.quotaEstimate)
    }
}
