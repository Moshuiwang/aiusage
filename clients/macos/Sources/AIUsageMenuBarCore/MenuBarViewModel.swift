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
    public let sources: [MenuDisplayRow]
    public let limitRows: [MenuDisplayRow]
    public let breakdownSections: [MenuDisplaySection]
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

        return MenuBarState(
            statusTitle: "AI \(tokenText)",
            periodLabel: periodLabel(selectedPeriodID),
            heroTotalText: tokenText,
            tokenBreakdownText: [
                "输入 \(TokenFormat.compact(summary.period.inputTokens))",
                "输出 \(TokenFormat.compact(summary.period.outputTokens))",
                "Cache \(TokenFormat.compact(summary.period.cacheTokens))",
            ].joined(separator: " · "),
            healthText: healthText(okCount: okCount, total: summary.sources.count, problemCount: problemCount),
            primaryLimitText: primaryLimitText(primaryLimit),
            lastUpdatedText: timeText(summary.generatedAt, timezone: summary.timezone),
            trendBars: trendBars(summary.trend),
            sources: summary.sources.map { sourceRow($0, generatedAt: summary.generatedAt) },
            limitRows: sortedLimits(summary.limits.windows).map { limitRow($0, generatedAt: summary.generatedAt) },
            breakdownSections: breakdownSections(summary.breakdown)
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
        let time: String
        if let generatedAt, generatedAt.count >= 16 {
            let start = generatedAt.index(generatedAt.startIndex, offsetBy: 11)
            let end = generatedAt.index(generatedAt.startIndex, offsetBy: 16)
            time = String(generatedAt[start..<end])
        } else {
            time = "--:--"
        }
        if let timezone, !timezone.isEmpty {
            return "\(time) · \(timezone)"
        }
        return time
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

    private static func sourceRow(_ source: MobileSource, generatedAt: String?) -> MenuDisplayRow {
        let title = source.displayName ?? [source.machine, source.osUser].compactMap { $0 }.joined(separator: " · ")
        return MenuDisplayRow(
            id: source.sourceID,
            title: title.isEmpty ? source.sourceID : title,
            subtitle: sourceSubtitle(source, generatedAt: generatedAt),
            value: source.status == "ok" ? "正常" : "异常",
            status: source.status
        )
    }

    private static func sourceSubtitle(_ source: MobileSource, generatedAt: String?) -> String {
        var parts: [String] = []
        if let lastObserved = compactDateTime(source.lastObservedAt, reference: generatedAt, suffix: "更新") {
            parts.append(lastObserved)
        } else {
            parts.append("未上报")
        }
        if let platform = source.platform, !platform.isEmpty {
            parts.append(platform)
        }
        return parts.joined(separator: " · ")
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
