import Foundation

public struct MenuBarState: Equatable, Sendable {
    public let statusTitle: String
    public let periodLabel: String
    public let heroTotalText: String
    public let tokenBreakdownText: String
    public let healthText: String
    public let primaryLimitText: String
    public let lastUpdatedText: String
    public let trendBars: [MenuTrendBar]
    public let trendRefCeilingText: String
    public let trendCeilingFraction: Double
    public let trendMidFraction: Double
    public let trendMidText: String
    public let sources: [MenuDisplayRow]
    public let limitRows: [MenuDisplayRow]
    public let breakdownSections: [MenuDisplaySection]
    public let quotaRings: [QuotaRingData]
    public let providerUsageCoverageText: String?
}

public struct QuotaRingData: Equatable, Sendable, Identifiable {
    public let id: String
    public let displayName: String
    public let outerRed: Double; public let outerGreen: Double; public let outerBlue: Double
    public let innerRed: Double; public let innerGreen: Double; public let innerBlue: Double
    public let outerFraction: Double
    public let innerFraction: Double
    public let outerPctText: String
    public let innerPctText: String
    public let outerTimeText: String
    public let innerTimeText: String
    public let outerLabel: String
    public let innerLabel: String
    public let sourceText: String
    public let updatedText: String
    public let availabilityText: String
    public let usageText: String
}

public struct MenuTrendBar: Equatable, Sendable, Identifiable {
    public let id: String
    public let label: String
    public let tooltipTitle: String
    public let valueText: String
    public let ratio: Double
}

public struct MenuDisplayRow: Equatable, Sendable, Identifiable {
    public let id: String
    public let title: String
    public let subtitle: String
    public let value: String
    public let status: String
}

public struct MenuDisplaySection: Equatable, Sendable, Identifiable {
    public let id: String
    public let title: String
    public let rows: [MenuDisplayRow]
}

public enum MenuBarViewModel {
    public static func build(from summary: MobileSummary, selectedPeriodID: String, now: Date = Date()) -> MenuBarState {
        let tokenText = TokenFormat.compact(summary.period.totalTokens)
        let okCount = summary.sources.filter { $0.status == "ok" }.count
        let problemCount = summary.sources.filter { $0.status != "ok" && $0.status != "disabled" }.count
        let displaySlots = fixedProviderSlots(summary.providerSlots)
        let currentProviderWindows = currentProviderWindows(displaySlots, now: now)
        let primaryLimit = currentProviderWindows
            .sorted { lhs, rhs in
                if lhs.usedPercent == rhs.usedPercent {
                    return lhs.id.localizedStandardCompare(rhs.id) == .orderedAscending
                }
                return lhs.usedPercent > rhs.usedPercent
            }
            .first

        let maxTokens = summary.trend.points.map(\.tokens).max() ?? 0
        let ceiling = maxTokens > 0 ? ceilingValue(maxTokens) : 1
        let midVal = midlineValue(ceiling: ceiling)

        return MenuBarState(
            statusTitle: tokenText,
            periodLabel: periodLabel(selectedPeriodID),
            heroTotalText: tokenText,
            tokenBreakdownText: [
                "输入 \(TokenFormat.compact(summary.period.inputTokens))",
                "输出 \(TokenFormat.compact(summary.period.outputTokens))",
                "Cache \(TokenFormat.compact(summary.period.cacheTokens))",
            ].joined(separator: " · "),
            healthText: healthText(okCount: okCount, total: summary.sources.count, problemCount: problemCount),
            primaryLimitText: primaryLimitText(primaryLimit),
            lastUpdatedText: latestDataText(summary.sources, fallback: summary.generatedAt, timezone: summary.timezone),
            trendBars: trendBars(summary.trend),
            trendRefCeilingText: maxTokens > 0 ? ceilingText(ceiling) : "",
            trendCeilingFraction: maxTokens > 0 ? Double(maxTokens) / Double(ceiling) : 1.0,
            trendMidFraction: maxTokens > 0 && midVal > 0 ? Double(midVal) / Double(ceiling) : 0,
            trendMidText: maxTokens > 0 && midVal > 0 ? ceilingText(midVal) : "",
            sources: sourceRows(summary.sources, byMachine: summary.breakdown.byMachine, generatedAt: summary.generatedAt),
            limitRows: sortedLimits(currentProviderWindows).map { limitRow($0, generatedAt: summary.generatedAt) },
            breakdownSections: breakdownSections(summary.breakdown),
            quotaRings: quotaRings(
                from: displaySlots,
                generatedAt: summary.generatedAt,
                now: now
            ),
            providerUsageCoverageText: providerUsageCoverageText(summary.providerUsageCoverage)
        )
    }

    private static func periodLabel(_ periodID: String) -> String {
        switch periodID {
        case "today":
            return "今天"
        case "week":
            return "本周"
        case "month":
            return "本月"
        case "all":
            return "全部"
        default:
            return periodID
        }
    }

    private static func healthText(okCount: Int, total: Int, problemCount: Int) -> String {
        guard total > 0 else {
            return "暂无来源"
        }
        if problemCount == 0 {
            return "\(okCount)/\(total) 正常"
        }
        return "\(okCount)/\(total) 正常 · \(problemCount) 异常"
    }

    private static func primaryLimitText(_ window: MobileLimitWindow?) -> String {
        guard let window else {
            return "暂无可信额度"
        }
        return "\(providerName(window.provider)) \(window.window) · \(Int(window.usedPercent.rounded()))% 已用"
    }

    private static func providerUsageCoverageText(_ coverage: MobileProviderUsageCoverage) -> String? {
        guard !coverage.isComplete else { return nil }
        if coverage.status == "unknown" {
            return "用量归属未知：服务端未提供归属信息"
        }
        return "用量归属不完整：部分用量未归属到 Claude/Codex"
    }

    private static func timeText(_ generatedAt: String?, timezone: String?) -> String {
        guard let generatedAt else { return "--" }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        var date = formatter.date(from: generatedAt)
        if date == nil {
            formatter.formatOptions = [.withInternetDateTime]
            date = formatter.date(from: generatedAt)
        }
        guard let d = date else { return "--" }
        let elapsed = Int(-d.timeIntervalSinceNow)
        if elapsed < 60 { return "刚刚" }
        if elapsed < 3600 { return "\(elapsed / 60) 分钟前" }
        if elapsed < 86400 { return "\(elapsed / 3600) 小时前" }
        return "\(elapsed / 86400) 天前"
    }

    private static func latestDataText(_ sources: [MobileSource], fallback: String?, timezone: String?) -> String {
        let latest = sources.compactMap { $0.lastObservedAt }.max()
        return timeText(latest ?? fallback, timezone: timezone)
    }

    private static func trendBars(_ trend: MobileTrend) -> [MenuTrendBar] {
        let maxTokens = max(trend.points.map(\.tokens).max() ?? 0, 1)
        return trend.points.enumerated().map { index, point in
            MenuTrendBar(
                id: point.bucket,
                label: axisLabel(
                    for: point,
                    index: index,
                    count: trend.points.count,
                    granularity: trend.granularity
                ),
                tooltipTitle: shortBucket(point.bucket, granularity: trend.granularity),
                valueText: TokenFormat.compact(point.tokens),
                ratio: Double(point.tokens) / Double(maxTokens)
            )
        }
    }

    private static func axisLabel(for point: MobileTrendPoint, index: Int, count: Int, granularity: String?) -> String {
        guard shouldShowAxisLabel(index: index, count: count) else {
            return ""
        }
        return shortBucket(point.bucket, granularity: granularity)
    }

    private static func shouldShowAxisLabel(index: Int, count: Int) -> Bool {
        if count <= 4 {
            return true
        }
        return index == 0 || index == count / 2 || index == count - 1
    }

    private static func shortBucket(_ bucket: String, granularity: String?) -> String {
        if granularity == "hour", bucket.count >= 16, bucket.dropFirst(10).first == "T" {
            let hourStart = bucket.index(bucket.startIndex, offsetBy: 11)
            let minuteEnd = bucket.index(bucket.startIndex, offsetBy: 16)
            return String(bucket[hourStart..<minuteEnd])
        }
        if bucket.count >= 10, bucket.dropFirst(4).first == "-", bucket.dropFirst(7).first == "-" {
            let monthStart = bucket.index(bucket.startIndex, offsetBy: 5)
            let dayEnd = bucket.index(bucket.startIndex, offsetBy: 10)
            return String(bucket[monthStart..<dayEnd])
        }
        if bucket.count >= 5 {
            return String(bucket.suffix(5))
        }
        return bucket
    }

    private static func sourceRows(_ sources: [MobileSource], byMachine: [MobileBreakdownRow], generatedAt: String?) -> [MenuDisplayRow] {
        let sourceTokens = sourceTokensBySourceID(from: byMachine)
        return sources
            .compactMap { source -> (MenuDisplayRow, Int)? in
                let tokens = sourceTokens[source.sourceID] ?? 0
                if tokens == 0 { return nil }
                let title = source.osUser ?? source.machine ?? source.sourceID
                let timeStr = compactDateTime(source.lastObservedAt, reference: generatedAt, suffix: "更新") ?? "未上报"
                let machineStr = source.machine ?? ""
                let platformStr = source.platform ?? ""
                let subtitleParts = [machineStr, platformStr, timeStr].filter { !$0.isEmpty }
                let row = MenuDisplayRow(
                    id: source.sourceID,
                    title: title.isEmpty ? source.sourceID : title,
                    subtitle: subtitleParts.joined(separator: " · "),
                    value: tokens > 0 ? TokenFormat.compact(tokens) : "正常",
                    status: source.status
                )
                return (row, tokens)
            }
            .sorted { $0.1 > $1.1 }
            .map { $0.0 }
    }

    private static func sourceTokensBySourceID(from rows: [MobileBreakdownRow]) -> [String: Int] {
        var tokensBySourceID: [String: Int] = [:]
        for row in rows where row.tokens > 0 {
            if let contributions = row.contributions, !contributions.isEmpty {
                for contribution in contributions where contribution.tokens > 0 {
                    tokensBySourceID[contribution.sourceID, default: 0] += contribution.tokens
                }
            } else if let sourceIDs = row.sourceIDs, sourceIDs.count == 1, let sourceID = sourceIDs.first {
                tokensBySourceID[sourceID, default: 0] += row.tokens
            }
        }
        return tokensBySourceID
    }

    private static func sourceQuality(_ sourceType: String?) -> Int {
        switch sourceType {
        case "oauth_usage_api": return 4
        case "runtime_api", "cli_rpc": return 4
        case "official_cli": return 3
        case "official_cli_limit_message", "official_cli_subscription": return 2
        case "active_limits_cache": return 1
        default: return 0
        }
    }

    private static func fixedProviderSlots(_ slots: [MobileProviderSlot]) -> [MobileProviderSlot] {
        let fixedProviders = ["claude", "codex"]
        var slotsByProvider: [String: MobileProviderSlot] = [:]

        for slot in slots {
            let provider = canonicalProvider(slot.provider)
            guard fixedProviders.contains(provider), slotsByProvider[provider] == nil else { continue }
            slotsByProvider[provider] = MobileProviderSlot(
                provider: provider,
                usage: slot.usage,
                quota: slot.quota
            )
        }

        return fixedProviders.map { provider in
            slotsByProvider[provider] ?? MobileProviderSlot(
                provider: provider,
                usage: .missing,
                quota: .missing()
            )
        }
    }

    private static func currentProviderWindows(_ slots: [MobileProviderSlot], now: Date) -> [MobileLimitWindow] {
        slots.flatMap { trustedProviderWindows(for: $0, now: now) }
    }

    private static func trustedProviderWindows(
        for slot: MobileProviderSlot,
        now: Date
    ) -> [MobileLimitWindow] {
        guard slot.quota.status == "available" else { return [] }

        let candidates = slot.quota.windows.filter { window in
            window.isOfficialObserved &&
                !isLocalEstimate(window.sourceType) &&
                !isExpired(resetAt: window.resetAt, now: now) &&
                !isStale(observedAt: window.observedAt, now: now)
        }
        guard !candidates.isEmpty else { return [] }

        let sourceID = slot.quota.sourceID ?? preferredSourceID(candidates)
        guard let sourceID else { return [] }
        return candidates.filter { $0.sourceID == sourceID }
    }

    private static func preferredSourceID(_ windows: [MobileLimitWindow]) -> String? {
        let grouped = Dictionary(grouping: windows, by: \.sourceID)
        return grouped.keys.sorted { lhs, rhs in
            let lhsWindows = grouped[lhs] ?? []
            let rhsWindows = grouped[rhs] ?? []
            let lhsLatest = lhsWindows.compactMap { parseDate($0.observedAt) }.max() ?? .distantPast
            let rhsLatest = rhsWindows.compactMap { parseDate($0.observedAt) }.max() ?? .distantPast
            if lhsLatest != rhsLatest { return lhsLatest > rhsLatest }

            let lhsQuality = lhsWindows.map { sourceQuality($0.sourceType) }.max() ?? 0
            let rhsQuality = rhsWindows.map { sourceQuality($0.sourceType) }.max() ?? 0
            if lhsQuality != rhsQuality { return lhsQuality > rhsQuality }
            return lhs < rhs
        }.first
    }

    private static func isLocalEstimate(_ sourceType: String?) -> Bool {
        switch sourceType {
        case "active_limits_cache", "local_history_estimate", "ccusage_daily", "ccusage_blocks", "session_log_estimate":
            return true
        default:
            return false
        }
    }

    private static func isExpired(resetAt: String?, now: Date) -> Bool {
        guard let resetDate = parseDate(resetAt) else {
            return false
        }
        return resetDate <= now
    }

    private static func isStale(observedAt: String?, now: Date) -> Bool {
        guard let observedDate = parseDate(observedAt) else { return true }
        return now.timeIntervalSince(observedDate) > 120 * 60
    }

    private static func bestWindowPerType(_ windows: [MobileLimitWindow]) -> [MobileLimitWindow] {
        var best: [String: MobileLimitWindow] = [:]
        for w in windows {
            if let existing = best[w.window] {
                if isBetterLimitWindow(w, than: existing) {
                    best[w.window] = w
                }
            } else {
                best[w.window] = w
            }
        }
        return Array(best.values)
    }

    private static func isBetterLimitWindow(_ candidate: MobileLimitWindow, than existing: MobileLimitWindow) -> Bool {
        let candidateQuality = sourceQuality(candidate.sourceType)
        let existingQuality = sourceQuality(existing.sourceType)
        if candidateQuality != existingQuality {
            return candidateQuality > existingQuality
        }
        return (candidate.observedAt ?? "") > (existing.observedAt ?? "")
    }

    private static func quotaRings(
        from slots: [MobileProviderSlot],
        generatedAt: String?,
        now: Date
    ) -> [QuotaRingData] {
        let providerOrder = ["claude", "codex"]
        return slots.sorted {
            let lhs = providerOrder.firstIndex(of: canonicalProvider($0.provider)) ?? providerOrder.count
            let rhs = providerOrder.firstIndex(of: canonicalProvider($1.provider)) ?? providerOrder.count
            return lhs == rhs ? $0.provider < $1.provider : lhs < rhs
        }.map { slot in
            let provider = canonicalProvider(slot.provider)
            let wins = currentProviderWindows([slot], now: now)
            let bestWindows = bestWindowPerType(wins)
            let sessionWindow = bestWindows.first(where: isSessionLimitWindow)
            let weekWindow = bestWindows.first(where: isWeekLimitWindow)
            let otherWindow = bestWindows
                .filter { !isSessionLimitWindow($0) && !isWeekLimitWindow($0) }
                .sorted { $0.windowDurationMinutes < $1.windowDurationMinutes }
                .first
            let outerWindow = sessionWindow ?? otherWindow
            let selectedSourceID = wins.map(\.sourceID).first
            let sourceID = slot.quota.sourceID ?? selectedSourceID
            let verifiedAt = slot.quota.lastVerifiedAt ?? wins.compactMap(\.observedAt).max()
            let (name, oR, oG, oB, iR, iG, iB): (String, Double, Double, Double, Double, Double, Double)
            switch provider {
            case "claude":
                name = "Claude"; oR = 0.855; oG = 0.467; oB = 0.337; iR = 0.918; iG = 0.659; iB = 0.510
            case "codex":
                name = "Codex"
                oR = 0.039; oG = 0.518; oB = 1.0; iR = 0.353; iG = 0.784; iB = 0.980
            default:
                name = provider.prefix(1).uppercased() + provider.dropFirst()
                oR = 0.200; oG = 0.600; oB = 0.800; iR = 0.400; iG = 0.750; iB = 0.900
            }
            return QuotaRingData(
                id: provider, displayName: name,
                outerRed: oR, outerGreen: oG, outerBlue: oB,
                innerRed: iR, innerGreen: iG, innerBlue: iB,
                outerFraction: (outerWindow?.usedPercent ?? 0) / 100.0,
                innerFraction: (weekWindow?.usedPercent ?? 0) / 100.0,
                outerPctText: outerWindow.map { "\(Int($0.usedPercent.rounded()))%" } ?? "--",
                innerPctText: weekWindow.map { "\(Int($0.usedPercent.rounded()))%" } ?? "--",
                outerTimeText: outerWindow.flatMap { timeRemainingText($0.resetAt, now: now) } ?? "--",
                innerTimeText: weekWindow.flatMap { timeRemainingText($0.resetAt, now: now) } ?? "--",
                outerLabel: outerWindow.map(windowLabel) ?? "额度",
                innerLabel: weekWindow.map(windowLabel) ?? "长期",
                sourceText: sourceText(provider: provider, sourceID: sourceID),
                updatedText: compactDateTime(
                    verifiedAt,
                    reference: generatedAt,
                    suffix: "更新"
                ) ?? "未更新",
                availabilityText: quotaAvailabilityText(
                    slot.quota,
                    hasVisibleWindow: outerWindow != nil || weekWindow != nil
                ),
                usageText: slot.usage.status == "available"
                    ? "用量 \(TokenFormat.compact(slot.usage.totalTokens))"
                    : "用量不可用"
            )
        }
    }

    private static func quotaAvailabilityText(
        _ quota: MobileProviderQuota,
        hasVisibleWindow: Bool
    ) -> String {
        if hasVisibleWindow {
            return "官方额度"
        }
        guard let reason = quota.reason, !reason.isEmpty else {
            return "额度暂不可用"
        }
        let label: String
        switch reason {
        case "no_data": label = "暂无数据"
        case "stale": label = "数据已过期"
        case "unverified": label = "未验证"
        case "unsupported": label = "暂不支持"
        case "unavailable", "failed", "provider_failed": label = "读取失败"
        default: label = reason
        }
        return "额度暂不可用 · \(label)"
    }

    private static func canonicalProvider(_ provider: String) -> String {
        switch provider.lowercased() {
        case "anthropic", "claude": return "claude"
        case "openai", "codex", "gpt": return "codex"
        default: return provider.lowercased()
        }
    }

    private static func windowLabel(_ window: MobileLimitWindow) -> String {
        let minutes = window.windowDurationMinutes
        if minutes > 0 && minutes % (24 * 60) == 0 { return "\(minutes / (24 * 60))d" }
        if minutes > 0 && minutes % 60 == 0 { return "\(minutes / 60)h" }
        if minutes > 0 { return "\(minutes)m" }
        return window.window
    }

    private static func sourceText(provider: String, sourceID: String?) -> String {
        if let sourceID, let range = sourceID.range(of: "biai-", options: .caseInsensitive) {
            let account = String(sourceID[range.upperBound...])
            return account.isEmpty ? "BIAI" : "BIAI · \(account)"
        }
        return provider == "codex" ? "Codex 官方" : "Claude 官方"
    }

    private static func isSessionLimitWindow(_ window: MobileLimitWindow) -> Bool {
        let name = window.window.lowercased()
        if name == "session" || name.contains("5h") || name.contains("5-hour") {
            return true
        }
        return window.windowDurationMinutes > 0 && window.windowDurationMinutes <= 360
    }

    private static func isWeekLimitWindow(_ window: MobileLimitWindow) -> Bool {
        let name = window.window.lowercased()
        if name == "week" || name.contains("7d") || name.contains("7-day") {
            return true
        }
        return window.windowDurationMinutes >= 7 * 24 * 60
    }

    private static func timeRemainingText(_ resetAt: String?, now: Date) -> String? {
        guard let d = parseDate(resetAt) else { return nil }
        let secs = Int(d.timeIntervalSince(now))
        guard secs > 0 else { return "即将重置" }
        let hours = secs / 3600
        let mins = (secs % 3600) / 60
        if hours >= 24 { return "\(hours / 24)d \(hours % 24)h" }
        if hours > 0 { return "\(hours)h \(mins)min" }
        return "\(mins)min"
    }

    private static func parseDate(_ iso: String?) -> Date? {
        guard let iso, iso.count >= 19 else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: iso) {
            return date
        }
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.date(from: iso)
    }

    private static func ceilingValue(_ maxTokens: Int) -> Int {
        let tiers = [1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 100_000, 200_000, 500_000,
                     1_000_000, 2_000_000, 5_000_000, 10_000_000, 20_000_000, 50_000_000,
                     100_000_000, 200_000_000, 500_000_000,
                     1_000_000_000, 2_000_000_000, 5_000_000_000]
        return tiers.first { $0 > maxTokens } ?? (maxTokens * 2)
    }

    private static func midlineValue(ceiling: Int) -> Int {
        let tiers = [1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 100_000, 200_000, 500_000,
                     1_000_000, 2_000_000, 5_000_000, 10_000_000, 20_000_000, 50_000_000,
                     100_000_000, 200_000_000, 500_000_000,
                     1_000_000_000, 2_000_000_000, 5_000_000_000]
        let half = ceiling / 2
        return tiers.last { $0 <= half } ?? 0
    }

    private static func ceilingText(_ ceiling: Int) -> String {
        if ceiling >= 1_000_000_000 { return "\(ceiling / 1_000_000_000)B" }
        if ceiling >= 1_000_000 { return "\(ceiling / 1_000_000)M" }
        if ceiling >= 1_000 { return "\(ceiling / 1_000)K" }
        return "\(ceiling)"
    }

    private static func limitRow(_ window: MobileLimitWindow, generatedAt: String?) -> MenuDisplayRow {
        let availability = window.isOfficialObserved ? "\(Int(window.remainingPercent.rounded()))% 可用" : "未观测"
        let used = "\(Int(window.usedPercent.rounded()))% 已用"
        return MenuDisplayRow(
            id: window.id,
            title: "\(providerName(window.provider)) \(window.window)",
            subtitle: "\(used) · \(availability) · \(window.confidence)",
            value: compactResetTime(window.resetAt, generatedAt: generatedAt) ?? "--",
            status: window.status
        )
    }

    private static func sortedLimits(_ windows: [MobileLimitWindow]) -> [MobileLimitWindow] {
        windows.sorted { lhs, rhs in
            if lhs.isOfficialObserved != rhs.isOfficialObserved {
                return lhs.isOfficialObserved
            }
            if lhs.usedPercent != rhs.usedPercent {
                return lhs.usedPercent > rhs.usedPercent
            }
            return lhs.id.localizedStandardCompare(rhs.id) == .orderedAscending
        }
    }

    private static func breakdownSections(_ breakdown: MobileBreakdown) -> [MenuDisplaySection] {
        [
            MenuDisplaySection(id: "machine", title: "机器", rows: rows(breakdown.byMachine)),
            MenuDisplaySection(id: "os-user", title: "账户", rows: rows(breakdown.byOSUser)),
            MenuDisplaySection(id: "agent", title: "Agent", rows: rows(breakdown.byAgent)),
            MenuDisplaySection(id: "model", title: "模型", rows: rows(breakdown.byModel)),
            MenuDisplaySection(id: "date", title: "日期", rows: rows(breakdown.byDate)),
        ]
    }

    private static func rows(_ rows: [MobileBreakdownRow]) -> [MenuDisplayRow] {
        rows.filter { $0.tokens > 0 }.map { row in
            MenuDisplayRow(
                id: row.id,
                title: row.label,
                subtitle: sourceCountText(row.sourceIDs?.count ?? row.contributions?.count ?? 0),
                value: TokenFormat.compact(row.tokens),
                status: "ok"
            )
        }
    }

    private static func providerName(_ provider: String) -> String {
        guard let first = provider.first else { return provider }
        return first.uppercased() + provider.dropFirst()
    }

    private static func sourceCountText(_ count: Int) -> String {
        guard count > 0 else { return "" }
        return "\(count) 个来源"
    }

    private static func compactDateTime(_ iso: String?, reference: String?, suffix: String) -> String? {
        guard let iso, iso.count >= 16 else { return nil }
        let date = String(iso.prefix(10))
        let timeStart = iso.index(iso.startIndex, offsetBy: 11)
        let timeEnd = iso.index(iso.startIndex, offsetBy: 16)
        let time = String(iso[timeStart..<timeEnd])
        let text: String
        if let reference, reference.hasPrefix(date) {
            text = time
        } else if iso.count >= 10 {
            let monthStart = iso.index(iso.startIndex, offsetBy: 5)
            let dayEnd = iso.index(iso.startIndex, offsetBy: 10)
            text = "\(String(iso[monthStart..<dayEnd])) \(time)"
        } else {
            text = time
        }
        return "\(text) \(suffix)"
    }

    private static func compactResetTime(_ resetAt: String?, generatedAt: String?) -> String? {
        guard let resetAt else { return nil }
        let suffix: String
        if let generatedAt, resetAt.prefix(10) < generatedAt.prefix(10) {
            suffix = "已过"
        } else {
            suffix = "重置"
        }
        return compactDateTime(resetAt, reference: generatedAt, suffix: suffix)
    }
}

public enum MenuTrendSelection {
    public static func nearestBar(in bars: [MenuTrendBar], xLocation: Double, width: Double) -> MenuTrendBar? {
        guard !bars.isEmpty, width > 0 else {
            return nil
        }
        let clampedX = min(max(xLocation, 0), width)
        let slotWidth = width / Double(bars.count)
        let index = min(max(Int(clampedX / slotWidth), 0), bars.count - 1)
        return bars[index]
    }
}

public enum TokenFormat {
    public static func compact(_ value: Int) -> String {
        let number = Double(value)
        if abs(value) >= 1_000_000_000 {
            return String(format: "%.1fB", number / 1_000_000_000)
        }
        if abs(value) >= 1_000_000 {
            return String(format: "%.1fM", number / 1_000_000)
        }
        if abs(value) >= 1_000 {
            return String(format: "%.1fK", number / 1_000)
        }
        return String(value)
    }
}
