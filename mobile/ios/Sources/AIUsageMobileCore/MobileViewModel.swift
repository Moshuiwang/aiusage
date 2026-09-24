import Foundation

public struct LimitWindowGroup: Equatable, Sendable, Identifiable {
    public let id: String
    public let provider: String
    public let sourceID: String
    public let windows: [MobileLimitWindow]
    public let accountLabel: String?
    public let accountPlanLabel: String?

    public var providerLabel: String {
        provider.capitalized
    }

    public var weeklyResetText: String {
        windows.first { $0.window.lowercased().contains("week") || $0.window == "周" }?.resetAt ?? "--"
    }

    public var fiveHourResetText: String {
        windows.first { $0.window.lowercased().contains("5") }?.resetAt ?? "--"
    }

    public var statText: String {
        let observed = windows.filter(\.isOfficialObserved).count
        return "\(observed)/\(windows.count) 可信"
    }
}

public func limitGroups(from windows: [MobileLimitWindow]) -> [LimitWindowGroup] {
    let grouped = Dictionary(grouping: windows) { window in
        "\(window.provider)|\(window.sourceID)"
    }
    return grouped.map { key, groupWindows in
        let first = groupWindows[0]
            return LimitWindowGroup(
                id: key,
                provider: first.provider,
                sourceID: first.sourceID,
                windows: groupWindows.sorted { lhs, rhs in
                    if lhs.window == rhs.window {
                        return lhs.id.localizedStandardCompare(rhs.id) == .orderedAscending
                    }
                    if lhs.window.lowercased().contains("week") {
                        return true
                    }
                    if rhs.window.lowercased().contains("week") {
                        return false
                    }
                    return lhs.window.localizedStandardCompare(rhs.window) == .orderedAscending
                },
                accountLabel: groupWindows.compactMap(\.accountLabel).first,
                accountPlanLabel: groupWindows.compactMap(\.accountPlanLabel).first
        )
    }
    .sorted { lhs, rhs in
        lhs.id.localizedStandardCompare(rhs.id) == .orderedAscending
    }
}

public struct QuotaWindowDisplayState: Equatable, Sendable {
    public let rowText: String
    public let percent: Int?
    public let resetText: String
    public let isKnown: Bool

    public static func fiveHour(window: MobileLimitWindow?) -> QuotaWindowDisplayState {
        guard let window else {
            return QuotaWindowDisplayState(rowText: "5h -- --", percent: nil, resetText: "--", isKnown: false)
        }
        let pct = Int(window.usedPercent.rounded())
        let reset = quotaResetText(resetAt: window.resetAt)
        return QuotaWindowDisplayState(rowText: "5h \(pct)% \(reset)", percent: pct, resetText: reset, isKnown: true)
    }
}

public enum SourcesDisplayState {
    public static func rows(in breakdown: MobileBreakdown) -> [MobileBreakdownRow] {
        visibleRows(breakdown.bySource ?? breakdown.byMachine)
    }

    public static func visibleRows(_ rows: [MobileBreakdownRow]) -> [MobileBreakdownRow] {
        rows.filter { $0.tokens > 0 }
    }
}

public enum SourceUpdateDateText {
    public static func format(_ value: String?, now: Date = Date(), timezone: String?) -> String {
        guard let value, !value.isEmpty else { return "--" }
        guard let date = parseDate(value) else { return value }
        var calendar = Calendar(identifier: .gregorian)
        if let timezone, let tz = TimeZone(identifier: timezone) {
            calendar.timeZone = tz
        }
        let timeFormatter = DateFormatter()
        timeFormatter.locale = Locale(identifier: "zh_CN")
        timeFormatter.timeZone = calendar.timeZone
        timeFormatter.dateFormat = "HH:mm"

        if calendar.isDate(date, inSameDayAs: now) {
            return "今天 \(timeFormatter.string(from: date))"
        }
        if let yesterday = calendar.date(byAdding: .day, value: -1, to: calendar.startOfDay(for: now)),
           calendar.isDate(date, inSameDayAs: yesterday) {
            return "昨天 \(timeFormatter.string(from: date))"
        }

        let dateFormatter = DateFormatter()
        dateFormatter.locale = Locale(identifier: "zh_CN")
        dateFormatter.timeZone = calendar.timeZone
        let sameYear = calendar.component(.year, from: date) == calendar.component(.year, from: now)
        dateFormatter.dateFormat = sameYear ? "MM-dd HH:mm" : "yyyy-MM-dd HH:mm"
        return dateFormatter.string(from: date)
    }

    private static func parseDate(_ value: String) -> Date? {
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = iso.date(from: value) { return date }
        iso.formatOptions = [.withInternetDateTime]
        return iso.date(from: value)
    }
}

public enum AccountLabelText {
    public static func compactEmail(_ label: String) -> String {
        guard label.count > 24, let at = label.firstIndex(of: "@") else { return label }
        let local = String(label[..<at])
        let domain = String(label[at...])
        guard local.count > 8 else { return label }
        return "\(local.prefix(4))****\(local.suffix(3))\(domain)"
    }
}

private func quotaResetText(resetAt: String?) -> String {
    guard let resetAt, !resetAt.isEmpty else { return "已重置" }
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    var date = formatter.date(from: resetAt)
    if date == nil {
        formatter.formatOptions = [.withInternetDateTime]
        date = formatter.date(from: resetAt)
    }
    guard let date else { return resetAt.count >= 16 ? String(resetAt.dropFirst(11).prefix(5)) : resetAt }
    return date.timeIntervalSinceNow > 0 ? remainingDurationText(until: date) : "已重置"
}

private func remainingDurationText(until date: Date) -> String {
    let interval = date.timeIntervalSinceNow
    guard interval > 0 else { return "已重置" }
    let totalMinutes = Int(interval / 60)
    let days = totalMinutes / (24 * 60)
    let hours = (totalMinutes % (24 * 60)) / 60
    let minutes = totalMinutes % 60
    if days > 0 { return "\(days)d \(hours)h" }
    if hours > 0 { return "\(hours)h \(minutes)min" }
    return "\(minutes)min"
}

public struct MobileHomeState: Equatable, Sendable {
    public let title: String
    public let periodID: String
    public let periodLabelText: String
    public let totalTokens: Int
    public let totalText: String
    public let inputTokens: Int
    public let inputText: String
    public let outputTokens: Int
    public let outputText: String
    public let cacheTokens: Int
    public let cacheText: String
    public let cacheHitText: String
    public let rangeText: String
    public let lastServerReadText: String
    public let tokenBreakdownText: String
    public let healthText: String
    public let primaryLimitText: String
    public let trendPoints: [MobileTrendPoint]
    public let topSources: [MobileBreakdownRow]
    public let refreshGroups: [LimitWindowGroup]
}

public struct MobileViewState: Equatable, Sendable {
    public let home: MobileHomeState
    public let sources: [MobileSource]
    public let breakdown: MobileBreakdown
    public let limits: MobileLimits
}

public enum MobileViewModel {
    public static func build(from summary: MobileSummary) -> MobileViewState {
        let visibleMachineRows = SourcesDisplayState.visibleRows(summary.breakdown.byMachine)
        let visibleSourceIDs = Set(visibleMachineRows.flatMap { $0.sourceIDs ?? [] })
        let visibleSources = summary.sources.filter { visibleSourceIDs.contains($0.sourceID) }
        let visibleBreakdown = MobileBreakdown(
            byMachine: visibleMachineRows,
            byOSUser: summary.breakdown.byOSUser,
            byAgent: summary.breakdown.byAgent,
            byModel: summary.breakdown.byModel,
            byDate: summary.breakdown.byDate,
            bySource: summary.breakdown.bySource
        )
        let failedSources = summary.sources.filter { $0.status != "ok" && $0.status != "disabled" }
        let okSources = visibleSources.filter { $0.status == "ok" }
        let observedLimit = summary.limits.windows
            .filter(\.isOfficialObserved)
            .sorted {
                if $0.remainingPercent == $1.remainingPercent {
                    return $0.id.localizedStandardCompare($1.id) == .orderedAscending
                }
                return $0.remainingPercent < $1.remainingPercent
            }
            .first

        let healthText: String
        if failedSources.isEmpty {
            healthText = "\(okSources.count)/\(visibleSources.count) sources"
        } else {
            healthText = "\(failedSources.count) source issues"
        }

        return MobileViewState(
            home: MobileHomeState(
                title: "AI Usage",
                periodID: summary.period.id,
                periodLabelText: periodLabelText(summary.period),
                totalTokens: summary.period.totalTokens,
                totalText: TokenFormat.compact(summary.period.totalTokens),
                inputTokens: summary.period.inputTokens,
                inputText: TokenFormat.compact(summary.period.inputTokens),
                outputTokens: summary.period.outputTokens,
                outputText: TokenFormat.compact(summary.period.outputTokens),
                cacheTokens: summary.period.cacheTokens,
                cacheText: TokenFormat.compact(summary.period.cacheTokens),
                cacheHitText: "\(summary.period.cacheRatio)%",
                rangeText: periodRangeText(summary.period),
                lastServerReadText: lastServerReadText(
                    generatedAt: summary.generatedAt,
                    timezone: summary.timezone
                ),
                tokenBreakdownText: "Input \(TokenFormat.compact(summary.period.inputTokens)) · Output \(TokenFormat.compact(summary.period.outputTokens)) · Cache \(TokenFormat.compact(summary.period.cacheTokens))",
                healthText: healthText,
                primaryLimitText: limitText(observedLimit),
                trendPoints: summary.trend.points,
                topSources: Array(visibleMachineRows.prefix(3)),
                refreshGroups: Array(limitGroups(from: summary.limits.windows).prefix(3))
            ),
            sources: visibleSources,
            breakdown: visibleBreakdown,
            limits: summary.limits
        )
    }

    private static func periodRangeText(_ period: MobilePeriod) -> String {
        switch period.id {
        case "today":
            return period.date ?? period.endDate ?? "today"
        case "week":
            return "\(period.startDate ?? "--") - \(period.endDate ?? "--")"
        case "month":
            return "\(period.startDate ?? "--") - \(period.endDate ?? "--")"
        case "all":
            return "all data"
        default:
            return period.endDate ?? period.date ?? period.id
        }
    }

    private static func periodLabelText(_ period: MobilePeriod) -> String {
        switch period.id {
        case "today":
            return "今天"
        case "week":
            return "周"
        case "month":
            return "月"
        case "all":
            return "全部"
        default:
            return period.id
        }
    }

    private static func limitText(_ window: MobileLimitWindow?) -> String {
        guard let window else {
            return "No observed quota"
        }
        return "\(window.provider) \(window.window) · \(Int(window.remainingPercent.rounded()))% left"
    }

    private static func lastServerReadText(generatedAt: String?, timezone: String?) -> String {
        let timeText: String
        if let generatedAt, generatedAt.count >= 16 {
            let start = generatedAt.index(generatedAt.startIndex, offsetBy: 11)
            let end = generatedAt.index(generatedAt.startIndex, offsetBy: 16)
            timeText = String(generatedAt[start..<end])
        } else {
            timeText = "--"
        }

        if let timezone, !timezone.isEmpty {
            return "上次读取 \(timeText) · \(timezone)"
        }
        return "上次读取 \(timeText)"
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

    public static func full(_ value: Int) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        return formatter.string(from: NSNumber(value: value)) ?? String(value)
    }
}

public enum TrendPointSelection {
    public static func defaultPoint(in points: [MobileTrendPoint]) -> MobileTrendPoint? {
        points.last { $0.tokens > 0 } ?? points.last
    }

    public static func nearestPoint(
        in points: [MobileTrendPoint],
        xLocation: Double,
        width: Double
    ) -> MobileTrendPoint? {
        guard !points.isEmpty else {
            return nil
        }
        guard points.count > 1, width > 0 else {
            return points[0]
        }
        let clampedX = min(max(xLocation, 0), width)
        let step = width / Double(points.count - 1)
        let index = Int((clampedX / step).rounded())
        return points[min(max(index, 0), points.count - 1)]
    }
}

public struct TrendTooltipLines: Equatable, Sendable {
    public let label: String
    public let total: String
    public let claude: String
    public let codex: String
    public let gemini: String
    public let unknown: String
}

public enum TrendChartPresentation {
    public static func points(from points: [MobileTrendPoint]) -> [MobileTrendPoint] {
        points
    }

    public static func tooltipLines(for point: MobileTrendPoint) -> TrendTooltipLines {
        TrendTooltipLines(
            label: point.label.isEmpty ? point.bucket : point.label,
            total: "\(TokenFormat.compact(point.tokens)) · \(TokenFormat.full(point.tokens))",
            claude: "Claude \(TokenFormat.full(point.claudeTokens))",
            codex: "Codex \(TokenFormat.full(point.codexTokens))",
            gemini: "Gemini \(TokenFormat.full(point.geminiTokens))",
            unknown: "未知 \(TokenFormat.full(point.unknownTokens))"
        )
    }
}
