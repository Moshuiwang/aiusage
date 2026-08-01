import Foundation
import XCTest
@testable import AIUsageMenuBarCore

// provider-slots-owner-fixture.json is generated from the Python owner read model
// via tests/test_provider_slots_parity._collect_records; keep test cases read-only.
final class ProviderSlotViewModelTests: XCTestCase {
    func testDecodesOwnerProviderSlotsAndCoverage() throws {
        let record = try goldenRecord(named: "01-usage-and-quota:mobile-summary")

        XCTAssertEqual(record.providerSlots.map(\.provider), ["claude", "codex"])
        let claude = try XCTUnwrap(record.providerSlots.first { $0.provider == "claude" })
        XCTAssertEqual(claude.usage.status, "available")
        XCTAssertEqual(claude.usage.totalTokens, 3_100)
        XCTAssertEqual(claude.quota.status, "available")
        XCTAssertEqual(claude.quota.windows.count, 1)
        XCTAssertEqual(claude.quota.windows.first?.usedPercent, 78.25)
        XCTAssertEqual(record.coverage.status, "complete")
        XCTAssertTrue(record.coverage.isComplete)
    }

    func testOldResponseWithoutProviderFieldsDegradesWithoutQuotaClaims() throws {
        let summary = try loadLegacyFixture()

        XCTAssertTrue(summary.providerSlots.isEmpty)
        XCTAssertEqual(summary.providerUsageCoverage.status, "unknown")
        XCTAssertFalse(summary.providerUsageCoverage.isComplete)

        let state = MenuBarViewModel.build(
            from: summary,
            selectedPeriodID: "week",
            now: try date("2026-06-02T11:00:00+08:00")
        )

        XCTAssertTrue(state.quotaRings.isEmpty)
        XCTAssertTrue(state.providerUsageCoverageText?.contains("未知") == true)
    }

    func testClaudeUsageAndQuotaAreDisplayedFromProviderSlot() throws {
        let record = try goldenRecord(named: "01-usage-and-quota:mobile-summary")
        let state = MenuBarViewModel.build(
            from: try summary(for: record),
            selectedPeriodID: "today",
            now: try date("2026-06-03T11:10:00+08:00")
        )

        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.usageText, "用量 3.1K")
        XCTAssertEqual(claude.innerPctText, "78%")
        XCTAssertNotEqual(claude.innerTimeText, "--")
        XCTAssertEqual(claude.availabilityText, "官方额度")

        let codex = try XCTUnwrap(state.quotaRings.first { $0.id == "codex" })
        XCTAssertEqual(codex.usageText, "用量 1.6K")
        XCTAssertEqual(codex.outerPctText, "43%")
        XCTAssertNotEqual(codex.outerTimeText, "--")
        XCTAssertNil(state.providerUsageCoverageText)
    }

    func testClaudeUsageRemainsVisibleWhenQuotaIsMissing() throws {
        let record = try goldenRecord(named: "02-usage-without-quota:mobile-summary")
        let state = MenuBarViewModel.build(
            from: try summary(for: record),
            selectedPeriodID: "today",
            now: try date("2026-06-03T11:10:00+08:00")
        )

        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.usageText, "用量 3.1K")
        XCTAssertEqual(claude.outerPctText, "--")
        XCTAssertEqual(claude.innerPctText, "--")
        XCTAssertEqual(claude.outerTimeText, "--")
        XCTAssertEqual(claude.innerTimeText, "--")
        XCTAssertTrue(claude.availabilityText.contains("暂不可用"))
        XCTAssertFalse(claude.availabilityText.contains("0%"))
        XCTAssertFalse(claude.availabilityText.contains("100%"))
    }

    func testClaudeQuotaRemainsVisibleWhenUsageIsMissing() throws {
        let record = try goldenRecord(named: "03-quota-without-usage:mobile-summary")
        let state = MenuBarViewModel.build(
            from: try summary(for: record),
            selectedPeriodID: "today",
            now: try date("2026-06-03T11:10:00+08:00")
        )

        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.usageText, "用量不可用")
        XCTAssertEqual(claude.innerPctText, "78%")
        XCTAssertNotEqual(claude.innerTimeText, "--")
    }

    func testClaudeUsageAndQuotaBothDegradeWithoutInventedZeroes() throws {
        let record = try goldenRecord(named: "04-neither:mobile-summary")
        let state = MenuBarViewModel.build(
            from: try summary(for: record),
            selectedPeriodID: "today",
            now: try date("2026-06-03T11:10:00+08:00")
        )

        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.usageText, "用量不可用")
        XCTAssertEqual(claude.outerPctText, "--")
        XCTAssertEqual(claude.innerPctText, "--")
        XCTAssertEqual(claude.outerTimeText, "--")
        XCTAssertEqual(claude.innerTimeText, "--")
        XCTAssertFalse(claude.usageText.contains("0"))
        XCTAssertFalse(claude.outerPctText.contains("0%"))
        XCTAssertFalse(claude.innerPctText.contains("100%"))
    }

    func testPartialProviderUsageCoverageShowsExplicitWarning() throws {
        let record = try goldenRecord(named: "13-third-party-provider-without-slot:mobile-summary")
        let state = MenuBarViewModel.build(
            from: try summary(for: record),
            selectedPeriodID: "week",
            now: try date("2026-06-03T11:10:00+08:00")
        )

        XCTAssertEqual(record.coverage.status, "partial")
        XCTAssertTrue(state.providerUsageCoverageText?.contains("归属不完整") == true)
    }

    func testSummaryCacheRoundTripKeepsProviderReadModel() throws {
        let record = try goldenRecord(named: "01-usage-and-quota:mobile-summary")
        let summary = try summary(for: record)
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("ai-usage-provider-cache-\(UUID().uuidString)")
            .appendingPathExtension("json")
        defer { try? FileManager.default.removeItem(at: url) }

        try SummaryCache.save(summary, to: url)
        let loaded = try XCTUnwrap(SummaryCache.load(from: url))

        XCTAssertEqual(loaded.providerSlots, summary.providerSlots)
        XCTAssertEqual(loaded.providerUsageCoverage, summary.providerUsageCoverage)
    }

    func testEveryOfficialQuotaTrustFlagIsRequiredForPercentAndReset() throws {
        let record = try goldenRecord(named: "01-usage-and-quota:mobile-summary")
        let sourceWindow = try XCTUnwrap(record.providerSlots.first { $0.provider == "claude" }?.quota.windows.first)
        let mutations: [(official: Bool, confidence: String, status: String)] = [
            (false, "observed", "ok"),
            (true, "estimated", "ok"),
            (true, "observed", "failed"),
        ]

        for mutation in mutations {
            let mutatedWindow = MobileLimitWindow(
                sourceID: sourceWindow.sourceID,
                provider: sourceWindow.provider,
                window: sourceWindow.window,
                usedPercent: sourceWindow.usedPercent,
                remainingPercent: sourceWindow.remainingPercent,
                resetAt: sourceWindow.resetAt,
                windowDurationMinutes: sourceWindow.windowDurationMinutes,
                observedAt: sourceWindow.observedAt,
                sourceType: sourceWindow.sourceType,
                confidence: mutation.confidence,
                status: mutation.status,
                official: mutation.official
            )
            var slots = record.providerSlots
            let claudeIndex = try XCTUnwrap(slots.firstIndex { $0.provider == "claude" })
            let claude = slots[claudeIndex]
            slots[claudeIndex] = MobileProviderSlot(
                provider: claude.provider,
                usage: claude.usage,
                quota: MobileProviderQuota(
                    status: "available",
                    reason: nil,
                    lastVerifiedAt: claude.quota.lastVerifiedAt,
                    sourceID: claude.quota.sourceID,
                    sourceType: claude.quota.sourceType,
                    windows: [mutatedWindow]
                )
            )

            let state = MenuBarViewModel.build(
                from: try summary(for: record, providerSlots: slots),
                selectedPeriodID: "today",
                now: try date("2026-06-03T11:10:00+08:00")
            )
            let ring = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
            XCTAssertEqual(ring.innerPctText, "--", "mutation: \(mutation)")
            XCTAssertEqual(ring.innerTimeText, "--", "mutation: \(mutation)")
            XCTAssertEqual(ring.outerPctText, "--", "mutation: \(mutation)")
            XCTAssertEqual(ring.outerTimeText, "--", "mutation: \(mutation)")
        }
    }

    private struct GoldenRecord: Decodable {
        let name: String
        let providerSlots: [MobileProviderSlot]
        let coverage: MobileProviderUsageCoverage

        enum CodingKeys: String, CodingKey {
            case name
            case providerSlots = "provider_slots"
            case coverage = "provider_usage_coverage"
        }
    }

    private func goldenRecord(named name: String) throws -> GoldenRecord {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "provider-slots-owner-fixture", withExtension: "json"))
        let records = try JSONDecoder().decode([GoldenRecord].self, from: Data(contentsOf: url))
        return try XCTUnwrap(records.first { $0.name == name })
    }

    private func loadLegacyFixture() throws -> MobileSummary {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "mobile-summary", withExtension: "json"))
        return try JSONDecoder().decode(MobileSummary.self, from: Data(contentsOf: url))
    }

    private func summary(
        for record: GoldenRecord,
        providerSlots: [MobileProviderSlot]? = nil
    ) throws -> MobileSummary {
        let base = try loadLegacyFixture()
        return MobileSummary(
            schemaVersion: base.schemaVersion,
            client: base.client,
            generatedAt: "2026-06-03T12:00:00+08:00",
            timezone: "Asia/Shanghai",
            period: base.period,
            trend: base.trend,
            sources: base.sources,
            breakdown: base.breakdown,
            limits: base.limits,
            providerSlots: providerSlots ?? record.providerSlots,
            providerUsageCoverage: record.coverage
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
}
