import Foundation
import XCTest
@testable import AIUsageMenuBarCore

// provider-slots-owner-fixture.json is generated from the Cloudflare Worker read model
// (cloudflare/native-worker/test/golden/, regenerate with `npm run cf:golden:gen`).
// It is the mobile half of provider_slots_golden.json and is kept in sync by
// cloudflare/native-worker/test/provider-slots-parity.test.ts. Never hand-edit it;
// keep the test cases here read-only.
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

        XCTAssertEqual(state.quotaRings.map(\.id), ["claude", "codex"])
        XCTAssertTrue(state.quotaRings.allSatisfy { ring in
            ring.outerPctText == "--" && ring.innerPctText == "--" &&
                ring.outerTimeText == "--" && ring.innerTimeText == "--"
        })
        XCTAssertTrue(state.providerUsageCoverageText?.contains("未知") == true)
    }

    func testPartialProviderResponseKeepsBothFixedSlotsAndDegradesMissingProvider() throws {
        let record = try goldenRecord(named: "01-usage-and-quota:mobile-summary")
        let claude = try XCTUnwrap(record.providerSlots.first { $0.provider == "claude" })
        let state = MenuBarViewModel.build(
            from: try summary(for: record, providerSlots: [claude]),
            selectedPeriodID: "today",
            now: try date("2026-06-03T11:10:00+08:00")
        )

        XCTAssertEqual(state.quotaRings.map(\.id), ["claude", "codex"])
        let codex = try XCTUnwrap(state.quotaRings.first { $0.id == "codex" })
        XCTAssertEqual(codex.usageText, "用量不可用")
        XCTAssertEqual(codex.outerPctText, "--")
        XCTAssertEqual(codex.innerPctText, "--")
        XCTAssertEqual(codex.outerTimeText, "--")
        XCTAssertEqual(codex.innerTimeText, "--")
    }

    func testCompleteCoverageWithoutStatisticsIsNotComplete() throws {
        let coverageData = Data(#"{"status":"complete"}"#.utf8)
        let coverage = try JSONDecoder().decode(MobileProviderUsageCoverage.self, from: coverageData)

        XCTAssertEqual(coverage.status, "complete")
        XCTAssertFalse(coverage.isComplete)

        let record = try goldenRecord(named: "01-usage-and-quota:mobile-summary")
        let state = MenuBarViewModel.build(
            from: try summary(for: record, coverage: coverage),
            selectedPeriodID: "today",
            now: try date("2026-06-03T11:10:00+08:00")
        )
        XCTAssertTrue(state.providerUsageCoverageText?.contains("归属") == true)
    }

    func testClaudeUsageAndQuotaAreDisplayedFromProviderSlot() throws {
        let record = try goldenRecord(named: "01-usage-and-quota:mobile-summary")
        let state = MenuBarViewModel.build(
            from: try summary(for: record),
            selectedPeriodID: "today",
            now: try date("2026-06-03T11:10:00+08:00")
        )

        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.usageText, "用量 3.1K · 9.7%")
        XCTAssertEqual(claude.innerPctText, "78%")
        XCTAssertNotEqual(claude.innerTimeText, "--")
        XCTAssertEqual(claude.availabilityText, "官方额度")

        let codex = try XCTUnwrap(state.quotaRings.first { $0.id == "codex" })
        XCTAssertEqual(codex.usageText, "用量 1.6K · 6.2%")
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
        XCTAssertEqual(claude.usageText, "用量 3.1K · 9.7%")
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

    func testDegradedQuotaStatusesKeepLastSuccessfulWindowsVisible() throws {
        let record = try goldenRecord(named: "01-usage-and-quota:mobile-summary")
        let sourceWindow = try XCTUnwrap(record.providerSlots.first { $0.provider == "claude" }?.quota.windows.first)

        for quotaStatus in ["missing", "stale", "unsupported", "failed"] {
            let slot = MobileProviderSlot(
                provider: "claude",
                usage: .missing,
                quota: MobileProviderQuota(
                    status: quotaStatus,
                    reason: quotaStatus,
                    lastVerifiedAt: sourceWindow.observedAt,
                    sourceID: sourceWindow.sourceID,
                    sourceType: sourceWindow.sourceType,
                    windows: [sourceWindow]
                )
            )
            let state = MenuBarViewModel.build(
                from: try summary(for: record, providerSlots: [slot]),
                selectedPeriodID: "today",
                now: try date("2026-06-03T11:10:00+08:00")
            )
            let ring = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
            XCTAssertEqual(ring.outerPctText, "--", "status: \(quotaStatus)")
            XCTAssertEqual(ring.innerPctText, "78%", "status: \(quotaStatus)")
            XCTAssertNotEqual(ring.innerTimeText, "--", "status: \(quotaStatus)")
        }
    }

    func testNilQuotaSourceChoosesOneSourceInsteadOfCombiningWindows() throws {
        let record = try goldenRecord(named: "01-usage-and-quota:mobile-summary")
        let windows = [
            MobileLimitWindow(
                sourceID: "biai-source-a", provider: "claude", window: "session",
                usedPercent: 10, remainingPercent: 90, resetAt: "2026-06-03T16:00:00+08:00",
                windowDurationMinutes: 300, observedAt: "2026-06-03T11:10:00+08:00",
                sourceType: "oauth_usage_api", confidence: "observed", status: "ok", official: true
            ),
            MobileLimitWindow(
                sourceID: "biai-source-b", provider: "claude", window: "week",
                usedPercent: 20, remainingPercent: 80, resetAt: "2026-06-10T00:00:00+08:00",
                windowDurationMinutes: 10080, observedAt: "2026-06-03T11:20:00+08:00",
                sourceType: "oauth_usage_api", confidence: "observed", status: "ok", official: true
            ),
        ]
        let slot = MobileProviderSlot(
            provider: "claude",
            usage: .missing,
            quota: MobileProviderQuota(
                status: "available", reason: nil, lastVerifiedAt: nil, sourceID: nil,
                sourceType: "oauth_usage_api", windows: windows
            )
        )

        let state = MenuBarViewModel.build(
            from: try summary(for: record, providerSlots: [slot]),
            selectedPeriodID: "today",
            now: try date("2026-06-03T11:30:00+08:00")
        )
        let ring = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })

        XCTAssertEqual(ring.outerPctText, "--")
        XCTAssertEqual(ring.innerPctText, "20%")
        XCTAssertEqual(ring.sourceText, "BIAI · source-b")
    }

    func testEveryOwnerScenarioKeepsFixedSlotsAndShowsLastSuccessfulQuota() throws {
        let records = try allGoldenRecords()
        // 场景数变化必须显式改这里。Worker 侧 provider-slots-parity.test.ts 有对称的 toBe(15)。
        XCTAssertEqual(records.count, 15)

        for record in records {
            let state = MenuBarViewModel.build(
                from: try summary(for: record),
                selectedPeriodID: "today",
                now: try date("2026-06-03T12:00:00+08:00")
            )
            XCTAssertEqual(state.quotaRings.map(\.id), ["claude", "codex"], record.name)

            for slot in record.providerSlots {
                let ring = try XCTUnwrap(state.quotaRings.first { $0.id == slot.provider }, record.name)
                let hasTrustedOwnerWindow = slot.quota.windows.contains {
                    $0.official && $0.confidence == "observed" && $0.status == "ok"
                }
                if !hasTrustedOwnerWindow {
                    XCTAssertEqual(ring.outerPctText, "--", record.name)
                    XCTAssertEqual(ring.innerPctText, "--", record.name)
                    XCTAssertEqual(ring.outerTimeText, "--", record.name)
                    XCTAssertEqual(ring.innerTimeText, "--", record.name)
                }
            }
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
        let records = try allGoldenRecords()
        return try XCTUnwrap(records.first { $0.name == name }, "Missing owner fixture record: \(name)")
    }

    private func allGoldenRecords() throws -> [GoldenRecord] {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "provider-slots-owner-fixture", withExtension: "json"))
        return try JSONDecoder().decode([GoldenRecord].self, from: Data(contentsOf: url))
    }

    private func loadLegacyFixture() throws -> MobileSummary {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "mobile-summary", withExtension: "json"))
        return try JSONDecoder().decode(MobileSummary.self, from: Data(contentsOf: url))
    }

    private func summary(
        for record: GoldenRecord,
        providerSlots: [MobileProviderSlot]? = nil,
        coverage: MobileProviderUsageCoverage? = nil
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
            providerUsageCoverage: coverage ?? record.coverage
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
