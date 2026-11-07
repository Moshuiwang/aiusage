import XCTest
@testable import AIUsageMenuBarApp
@testable import AIUsageMenuBarCore

/// #287 审查阻断项：格子 id 从 provider 换成账户键后，「缓存里有、新响应里没有」的格子必然出现
/// （2.x 缓存升级、账户超保留期）。它们不能被追加成带旧百分比的幽灵圆环，也不能被写回缓存。
@MainActor
final class AccountSlotFallbackTests: XCTestCase {
    private func window(_ source: String, _ provider: String, _ used: Double) -> MobileLimitWindow {
        MobileLimitWindow(sourceID: source, provider: provider, window: "week", usedPercent: used,
            remainingPercent: 100 - used, resetAt: "2026-06-10T00:00:00+08:00", windowDurationMinutes: 10080,
            observedAt: "2026-06-03T11:00:00+08:00", sourceType: "official_cli", confidence: "observed",
            status: "ok", official: true)
    }

    private func available(_ provider: String, _ windows: [MobileLimitWindow], account: MobileSlotAccount? = nil) -> MobileProviderSlot {
        MobileProviderSlot(provider: provider, usage: .missing,
            quota: MobileProviderQuota(status: "available", reason: nil, lastVerifiedAt: "2026-06-03T11:00:00+08:00",
                sourceID: windows.first?.sourceID, sourceType: "official_cli", windows: windows),
            account: account)
    }

    private func summary(_ slots: [MobileProviderSlot]) -> MobileSummary {
        let base = MobileSummary.empty()
        return MobileSummary(schemaVersion: 1, client: "macos", generatedAt: "2026-06-03T12:00:00+08:00",
            timezone: "Asia/Shanghai", period: base.period, trend: base.trend, sources: [], breakdown: base.breakdown,
            limits: base.limits, providerSlots: slots)
    }

    func testLegacyProviderCacheDoesNotAddGhostRingsNextToAccountSlots() {
        let legacyCache = summary([available("claude", [window("tz-wangzp", "claude", 77)]),
                                   available("codex", [window("codex-main", "codex", 90)])])
        let zhipeng = MobileSlotAccount(key: "claude:fp:claude:aaaaaaaaaaaaaaaaaaaaaaaa", label: "Zhipeng", plan: "max_5x")
        let tony = MobileSlotAccount(key: "claude:fp:claude:bbbbbbbbbbbbbbbbbbbbbbbb", label: "Tony", plan: "max_20x")
        let em = MobileSlotAccount(key: "codex:fp:codex:cccccccccccccccccccccccc", label: "Em", plan: "pro")
        let loaded = summary([available("claude", [window("tz-wangzhipeng", "claude", 10)], account: tony),
                              available("claude", [window("tz-wangzp", "claude", 82)], account: zhipeng),
                              available("codex", [window("codex-main", "codex", 55)], account: em)])
        let merged = MenuBarAppModel.summaryKeepingLastSuccessfulQuota(loaded, fallback: legacyCache)
        XCTAssertEqual(merged.providerSlots.map(\.id), loaded.providerSlots.map(\.id))
        XCTAssertFalse(merged.providerSlots.contains { $0.account == nil && ["claude", "codex"].contains($0.provider) })
    }

    func testProviderMissingFromResponseStillKeepsItsLastKnownSlot() {
        // 原有语义：新响应完全没有某个 provider 时，保留缓存里那一格（状态不变，不升格为可用）。
        let cache = summary([available("antigravity", [window("antigravity-mac", "antigravity", 5)])])
        let merged = MenuBarAppModel.summaryKeepingLastSuccessfulQuota(summary([]), fallback: cache)
        XCTAssertEqual(merged.providerSlots.map(\.id), ["antigravity"])
    }
}
