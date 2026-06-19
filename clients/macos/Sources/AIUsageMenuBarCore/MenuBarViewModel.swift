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
    public static func build(from summary: MobileSummary, selectedPeriodID: String) -> MenuBarState {
        let tokenText = TokenFormat.compact(summary.period.totalTokens)
        let okCount = summary.sources.filter { $0.status == "ok" }.count
        let problemCount = summary.sources.filter { $0.status != "ok" && $0.status != "disabled" }.count
        let primaryLimit = summary.limits.windows
            .filter(\.isOfficialObserved)
            .sorted { lhs, rhs in
                if lhs.remainingPercent == rhs.remainingPercent {
                    return lhs.id.localizedStandardCompare(rhs.id) == .orderedAscending
                }
                return lhs.remainingPercent < rhs.remainingPercent
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
            limitRows: sortedLimits(summary.limits.windows).map { limitRow($0, generatedAt: summary.generatedAt) },
            breakdownSections: breakdownSections(summary.breakdown),
            quotaRings: quotaRings(from: summary.limits.windows)
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
        return "\(providerName(window.provider)) \(window.window) · \(Int(window.remainingPercent.rounded()))% 可用"
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
        var machineTokens: [String: Int] = [:]
        for row in byMachine where row.tokens > 0 {
            machineTokens[row.label] = row.tokens
        }
        return sources
            .compactMap { source -> (MenuDisplayRow, Int)? in
                let tokens = source.machine.flatMap { machineTokens[$0] } ?? 0
                if source.status != "ok" && tokens == 0 { return nil }
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

    private static func sourceQuality(_ sourceType: String?) -> Int {
        switch sourceType {
        case "oauth_usage_api": return 4
        case "official_cli": return 3
        case "official_cli_limit_message", "official_cli_subscription": return 2
        case "active_limits_cache": return 1
        default: return 0
        }
    }

    private static func bestWindowPerType(_ windows: [MobileLimitWindow]) -> [MobileLimitWindow] {
        var best: [String: MobileLimitWindow] = [:]
        for w in windows {
            if let existing = best[w.window] {
                if sourceQuality(w.sourceType) > sourceQuality(existing.sourceType) {
                    best[w.window] = w
                }
            } else {
                best[w.window] = w
            }
        }
        return Array(best.values)
    }

    private static func quotaRings(from windows: [MobileLimitWindow]) -> [QuotaRingData] {
        let observed = windows.filter(\.isOfficialObserved)
        guard !observed.isEmpty else { return [] }
        let grouped = Dictionary(grouping: observed, by: \.provider)
        let order = ["anthropic", "claude", "openai", "codex", "gpt"]
        let ordered = order.filter { grouped[$0] != nil } +
                      grouped.keys.filter { !Set(order).contains($0) }.sorted()
        return ordered.prefix(2).compactMap { provider in
            guard let wins = grouped[provider] else { return nil }
            let sorted = bestWindowPerType(wins).sorted { $0.windowDurationMinutes < $1.windowDurationMinutes }
            let outer = sorted[0]
            let inner = sorted.count > 1 ? sorted[1] : nil
            let (name, oR, oG, oB, iR, iG, iB): (String, Double, Double, Double, Double, Double, Double)
            switch provider {
            case "anthropic", "claude":
                name = "Claude"; oR = 0.855; oG = 0.467; oB = 0.337; iR = 0.918; iG = 0.659; iB = 0.510
            case "openai", "codex", "gpt":
                name = provider == "codex" ? "Codex" : "OpenAI"
                oR = 0.039; oG = 0.518; oB = 1.0; iR = 0.353; iG = 0.784; iB = 0.980
            default:
                name = provider.prefix(1).uppercased() + provider.dropFirst()
                oR = 0.200; oG = 0.600; oB = 0.800; iR = 0.400; iG = 0.750; iB = 0.900
            }
            return QuotaRingData(
                id: provider, displayName: name,
                outerRed: oR, outerGreen: oG, outerBlue: oB,
                innerRed: iR, innerGreen: iG, innerBlue: iB,
                outerFraction: outer.usedPercent / 100.0,
                innerFraction: (inner?.usedPercent ?? 0) / 100.0,
                outerPctText: "\(Int(outer.usedPercent.rounded()))%",
                innerPctText: inner.map { "\(Int($0.usedPercent.rounded()))%" } ?? "--",
                outerTimeText: timeRemainingText(outer.resetAt) ?? "--",
                innerTimeText: inner.flatMap { timeRemainingText($0.resetAt) } ?? "--"
            )
        }
    }

    private static func timeRemainingText(_ resetAt: String?) -> String? {
        guard let resetAt, resetAt.count >= 19 else { return nil }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        var date = formatter.date(from: resetAt)
        if date == nil {
            formatter.formatOptions = [.withInternetDateTime]
            date = formatter.date(from: resetAt)
        }
        guard let d = date else { return nil }
        let secs = Int(d.timeIntervalSinceNow)
        guard secs > 0 else { return "即将重置" }
        let hours = secs / 3600
        let mins = (secs % 3600) / 60
        if hours >= 24 { return "\(hours / 24)d \(hours % 24)h" }
        if hours > 0 { return "\(hours)h \(mins)min" }
        return "\(mins)min"
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
            subtitle: "\(availability) · \(used) · \(window.confidence)",
            value: compactResetTime(window.resetAt, generatedAt: generatedAt) ?? "--",
            status: window.status
        )
    }

    private static func sortedLimits(_ windows: [MobileLimitWindow]) -> [MobileLimitWindow] {
        windows.sorted { lhs, rhs in
            if lhs.isOfficialObserved != rhs.isOfficialObserved {
                return lhs.isOfficialObserved
            }
            if lhs.remainingPercent != rhs.remainingPercent {
                return lhs.remainingPercent < rhs.remainingPercent
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
