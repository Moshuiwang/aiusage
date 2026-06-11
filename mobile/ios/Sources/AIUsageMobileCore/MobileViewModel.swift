import Foundation

public struct LimitWindowGroup: Equatable, Sendable, Identifiable {
    public let id: String
    public let provider: String
    public let sourceID: String
    public let windows: [MobileLimitWindow]

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
            }
        )
    }
    .sorted { lhs, rhs in
        lhs.id.localizedStandardCompare(rhs.id) == .orderedAscending
    }
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

public enum MobilePeriodSelectionDecision: Equatable, Sendable {
    case ignore
    case showCached(MobileSummary)
    case keepVisibleSummary
}

public enum MobilePeriodSelection {
    public static func decision(
        selectedPeriodID: String,
        visibleSummary: MobileSummary,
        cachedSummaries: [String: MobileSummary],
        isLoadingSelectedPeriod: Bool
    ) -> MobilePeriodSelectionDecision {
        if selectedPeriodID == visibleSummary.period.id && !isLoadingSelectedPeriod {
            return .ignore
        }
        if let cached = cachedSummaries[selectedPeriodID] {
            return .showCached(cached)
        }
        return .keepVisibleSummary
    }
}

public enum MobileViewModel {
    public static func build(from summary: MobileSummary) -> MobileViewState {
        let failedSources = summary.sources.filter { $0.status != "ok" && $0.status != "disabled" }
        let okSources = summary.sources.filter { $0.status == "ok" }
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
            healthText = "\(okSources.count)/\(summary.sources.count) sources"
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
                topSources: Array(summary.breakdown.byMachine.prefix(3)),
                refreshGroups: Array(limitGroups(from: summary.limits.windows).prefix(3))
            ),
            sources: summary.sources,
            breakdown: summary.breakdown,
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

struct BreakdownDrilldownSection: Equatable, Sendable, Identifiable {
    var id: String { title }
    let title: String
    let rows: [MobileBreakdownRow]
}

enum BreakdownDrilldown {
    static func sections(
        for row: MobileBreakdownRow,
        dimension: BreakdownDimension,
        breakdown: MobileBreakdown
    ) -> [BreakdownDrilldownSection] {
        let sourceIDs = Set(row.sourceIDs ?? [])
        let candidates: [(String, [MobileBreakdownRow])] = {
            switch dimension {
            case .machine:
                return [
                    ("系统账户", breakdown.byOSUser),
                    ("Agent", breakdown.byAgent),
                    ("Model", breakdown.byModel),
                    ("Date", breakdown.byDate)
                ]
            case .account:
                return [
                    ("Machine", breakdown.byMachine),
                    ("Agent", breakdown.byAgent),
                    ("Model", breakdown.byModel),
                    ("Date", breakdown.byDate)
                ]
            case .agent:
                return [
                    ("Machine", breakdown.byMachine),
                    ("系统账户", breakdown.byOSUser),
                    ("Model", breakdown.byModel),
                    ("Date", breakdown.byDate)
                ]
            case .model:
                return [
                    ("Machine", breakdown.byMachine),
                    ("系统账户", breakdown.byOSUser),
                    ("Agent", breakdown.byAgent),
                    ("Date", breakdown.byDate)
                ]
            case .date:
                return [
                    ("Machine", breakdown.byMachine),
                    ("系统账户", breakdown.byOSUser),
                    ("Agent", breakdown.byAgent),
                    ("Model", breakdown.byModel)
                ]
            }
        }()

        return candidates.compactMap { title, rows in
            let filtered = scopedRows(rows: rows, sourceIDs: sourceIDs, excluding: row)
            guard !filtered.isEmpty else {
                return nil
            }
            return BreakdownDrilldownSection(title: title, rows: filtered)
        }
    }

    private static func scopedRows(
        rows: [MobileBreakdownRow],
        sourceIDs: Set<String>,
        excluding selectedRow: MobileBreakdownRow
    ) -> [MobileBreakdownRow] {
        let scoped = rows.compactMap { row -> MobileBreakdownRow? in
            guard row.id != selectedRow.id else {
                return nil
            }
            guard !sourceIDs.isEmpty else {
                return row
            }

            if let contributions = row.contributions, !contributions.isEmpty {
                let matches = contributions.filter { sourceIDs.contains($0.sourceID) }
                let tokens = matches.reduce(0) { $0 + $1.tokens }
                guard tokens > 0 else {
                    return nil
                }
                return MobileBreakdownRow(
                    id: row.id,
                    label: row.label,
                    tokens: tokens,
                    sourceIDs: matches.map(\.sourceID).sorted(),
                    contributions: matches
                )
            }

            let rowSourceIDs = Set(row.sourceIDs ?? [])
            guard !rowSourceIDs.isDisjoint(with: sourceIDs) else {
                return nil
            }
            return row
        }
        return scoped.sorted {
            if $0.tokens == $1.tokens {
                return $0.label.localizedStandardCompare($1.label) == .orderedAscending
            }
            return $0.tokens > $1.tokens
        }
    }
}
