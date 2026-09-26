import Foundation

public struct MenuBarState: Equatable, Sendable {
    public let statusTitle: String
    public let periodLabel: String
    public let dateRangeText: String
    public let heroTotalText: String
    public let tokenBreakdownText: String
    public let healthText: String
    public let primaryLimitText: String
    public let lastUpdatedText: String
    public let trendBars: [MenuTrendBar]
    /// #176：按 Agent 汇总所有（非未来）柱的分段 tokens，顺序 claude → codex → antigravity → unknown，0 的省略。
    public let trendLegendTotals: [MenuTrendSegment]
    public let trendRefCeilingText: String
    public let trendCeilingFraction: Double
    public let trendMidFraction: Double
    public let trendMidText: String
    public let sources: [MenuDisplayRow]
    public let limitRows: [MenuDisplayRow]
    public let breakdownSections: [MenuDisplaySection]
    public let quotaRings: [QuotaRingData]
    public let providerUsageCoverageText: String?
    /// #175：Server 按机器分组的卡片，每张卡展开显示该机器上各模型的用量与「占所属 Agent 周额度」估算。
    public let serverCards: [MenuServerCard]
    /// 标题栏「N 台 Server」只数在线（至少一个 source status == "ok"）的机器。
    public let onlineServerCount: Int
    /// Server 模型行的额度列头：日/周为直接估算，月为周均换算。
    public let serverModelQuotaHeader: String
}

/// #175：一台机器一张 Server 卡。
public struct MenuServerCard: Equatable, Sendable, Identifiable {
    public let id: String
    public let title: String
    public let platform: String?
    /// 「用户 · HH:mm 同步」；多用户时用户段为「N 个用户」。
    public let subtitle: String
    public let valueText: String
    /// 该机器 tokens 占当期总量的百分比文本，如 "38%"；总量为 0 时 "—"。
    public let sharePercentText: String
    public let isOnline: Bool
    public let models: [MenuServerModelRow]

    public init(
        id: String,
        title: String,
        platform: String?,
        subtitle: String,
        valueText: String,
        sharePercentText: String,
        isOnline: Bool,
        models: [MenuServerModelRow]
    ) {
        self.id = id
        self.title = title
        self.platform = platform
        self.subtitle = subtitle
        self.valueText = valueText
        self.sharePercentText = sharePercentText
        self.isOnline = isOnline
        self.models = models
    }
}

/// #175：Server 卡内的一行模型用量。
public struct MenuServerModelRow: Equatable, Sendable, Identifiable {
    public let id: String
    public let modelID: String
    public let agentID: String
    public let agentDisplayName: String
    public let agentBrandColor: MenuTrendColor
    public let modelLabel: String
    public let tokens: Int
    public let valueText: String
    /// 模型明细状态（如 "available" / "missing"）；非 "available" 时 quotaText 一律 "—"。
    public let status: String
    /// 形如 "Claude 4.9%"；<0.05% 时 "Claude < 0.1%"；无法估算或 status 非 available 时 "—"。
    public let quotaText: String

    public init(
        id: String,
        modelID: String,
        agentID: String,
        agentDisplayName: String,
        agentBrandColor: MenuTrendColor,
        modelLabel: String,
        tokens: Int,
        valueText: String,
        status: String,
        quotaText: String
    ) {
        self.id = id
        self.modelID = modelID
        self.agentID = agentID
        self.agentDisplayName = agentDisplayName
        self.agentBrandColor = agentBrandColor
        self.modelLabel = modelLabel
        self.tokens = tokens
        self.valueText = valueText
        self.status = status
        self.quotaText = quotaText
    }
}

/// Agent 品牌展示（名称 + 固定品牌色），供额度环与 Server 模型行复用。
public enum AgentBranding {
    public static func displayName(for agentID: String) -> String {
        switch agentID.lowercased() {
        case "claude": return "Claude"
        case "codex": return "Codex"
        case "antigravity": return "Antigravity"
        default:
            guard let first = agentID.first else { return "未知" }
            return String(first).uppercased() + agentID.dropFirst()
        }
    }

    public static func color(for agentID: String) -> MenuTrendColor {
        switch agentID.lowercased() {
        case "claude":
            return MenuTrendColor(red: 0.851, green: 0.467, blue: 0.341, opacity: 1)
        case "codex":
            return MenuTrendColor(red: 0.184, green: 0.486, blue: 0.965, opacity: 1)
        case "antigravity":
            return MenuTrendColor(red: 0.608, green: 0.447, blue: 0.796, opacity: 1)
        default:
            return MenuTrendColor(red: 0.557, green: 0.557, blue: 0.576, opacity: 1)
        }
    }
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
    /// 固定品牌色，不随用量高低变化。
    public let brandColor: MenuTrendColor
    /// 周窗口优先，否则 session 窗口；不可用时 "—"。
    public let primaryPctText: String
    /// 所有可见窗口中最近一次重置的倒计时（如 "3d 23h"），不可用时 "--"。
    public let resetCountdownText: String
    /// 仅当官方观测且状态正常的窗口存在时为 true。
    public let isAvailable: Bool
}

public struct MenuTrendBar: Equatable, Sendable, Identifiable {
    public let id: String
    public let label: String
    public let tooltipTitle: String
    public let valueText: String
    public let ratio: Double
    public let totalTokens: Int
    public let segments: [MenuTrendSegment]
    /// #176：bucket 晚于「现在」（按 summary 时区）时为 true——无段、不参与柱高最大值。
    public let isFuture: Bool
}

public struct MenuTrendSegment: Equatable, Sendable, Identifiable {
    public var id: String { provider.rawValue }

    public let provider: MenuTrendProvider
    public let tokens: Int
    public let fraction: Double
}

public struct MenuTrendColor: Equatable, Sendable {
    public let red: Double
    public let green: Double
    public let blue: Double
    public let opacity: Double

    public init(red: Double, green: Double, blue: Double, opacity: Double) {
        self.red = red
        self.green = green
        self.blue = blue
        self.opacity = opacity
    }
}

public enum MenuTrendProvider: String, CaseIterable, Equatable, Sendable {
    case claude
    case codex
    case antigravity
    case unknown

    public var displayName: String {
        switch self {
        case .claude: return "Claude"
        case .codex: return "Codex"
        case .antigravity: return "Antigravity"
        case .unknown: return "未知"
        }
    }

    /// #176：不再有第二套色值，堆叠色与 #175 的 AgentBranding（额度环、Server 模型行）完全一致。
    public var color: MenuTrendColor {
        AgentBranding.color(for: rawValue)
    }
}

public struct MenuFlatModelRow: Equatable, Sendable, Identifiable {
    public let id: String
    public let modelID: String
    public let label: String
    public let agentID: String
    public let tokens: Int
    public let status: String
    public let quotaWeeklyPercentText: String?

    public init(
        id: String,
        modelID: String,
        label: String,
        agentID: String,
        tokens: Int,
        status: String,
        quotaWeeklyPercentText: String? = nil
    ) {
        self.id = id
        self.modelID = modelID
        self.label = label
        self.agentID = agentID
        self.tokens = tokens
        self.status = status
        self.quotaWeeklyPercentText = quotaWeeklyPercentText
    }

    public var title: String { status == "missing" ? "模型未知" : label }
    public var valueText: String { TokenFormat.compact(tokens) }
}

public struct MenuDisplayRow: Equatable, Sendable, Identifiable {
    public let id: String
    public let title: String
    public let subtitle: String
    public let value: String
    public let status: String
    public let platform: String?
    public let agents: [MobileSourceAgent]?
    public let flatModels: [MenuFlatModelRow]?

    public init(
        id: String,
        title: String,
        subtitle: String,
        value: String,
        status: String,
        platform: String? = nil,
        agents: [MobileSourceAgent]? = nil,
        flatModels: [MenuFlatModelRow]? = nil
    ) {
        self.id = id; self.title = title; self.subtitle = subtitle
        self.value = value; self.status = status; self.platform = platform
        self.agents = agents
        self.flatModels = flatModels
    }
}

public struct MenuDisplaySection: Equatable, Sendable, Identifiable {
    public let id: String
    public let title: String
    public let rows: [MenuDisplayRow]
}

public enum MenuBarViewModel {
    public static func build(
        from summary: MobileSummary,
        selectedPeriodID: String,
        selectedOffset: Int = 0,
        now: Date = Date(),
        machineAliases: [String: String]? = nil,
        quotaSlots: [MobileProviderSlot]? = nil
    ) -> MenuBarState {
        let tokenText = TokenFormat.compact(summary.period.totalTokens)
        let okCount = summary.sources.filter { $0.status == "ok" }.count
        let problemCount = summary.sources.filter { $0.status != "ok" && $0.status != "disabled" }.count
        let displaySlots = fixedProviderSlots(summary.providerSlots)
        let quotaDisplaySlots = fixedProviderSlots(quotaSlots ?? summary.providerSlots)
        let currentProviderWindows = currentProviderWindows(displaySlots, now: now)
        let primaryLimit = currentProviderWindows
            .sorted { lhs, rhs in
                if lhs.usedPercent == rhs.usedPercent {
                    return lhs.id.localizedStandardCompare(rhs.id) == .orderedAscending
                }
                return lhs.usedPercent > rhs.usedPercent
            }
            .first

        // 未来时段不参与最大值，与 trendBars 的 ratio 口径一致。
        let maxTokens = summary.trend.points
            .filter { !isFutureBucket($0.bucket, granularity: summary.trend.granularity, now: now, timezone: summary.timezone) }
            .map(\.tokens).max() ?? 0
        let ceiling = maxTokens > 0 ? ceilingValue(maxTokens) : 1
        let midVal = midlineValue(ceiling: ceiling)

        let cards = serverCards(
            summary.breakdown,
            sources: summary.sources,
            period: summary.period,
            now: now,
            timezone: summary.timezone,
            machineAliases: machineAliases
        )

        let bars = trendBars(summary.trend, now: now, timezone: summary.timezone)

        return MenuBarState(
            statusTitle: tokenText,
            periodLabel: selectedOffset == 0 ? periodLabel(selectedPeriodID) : (selectedPeriodID == "today" ? "历史日期" : selectedPeriodID == "week" ? "历史周" : "历史月"),
            dateRangeText: dateRangeText(summary.period),
            heroTotalText: tokenText,
            tokenBreakdownText: [
                "输入 \(TokenFormat.compact(summary.period.inputTokens))",
                "输出 \(TokenFormat.compact(summary.period.outputTokens))",
                "Cache \(TokenFormat.compact(summary.period.cacheTokens))",
            ].joined(separator: " · "),
            healthText: healthText(okCount: okCount, total: summary.sources.count, problemCount: problemCount),
            primaryLimitText: primaryLimitText(primaryLimit),
            lastUpdatedText: latestDataText(summary.sources, fallback: summary.generatedAt, timezone: summary.timezone),
            trendBars: bars,
            trendLegendTotals: aggregatedSegments(
                summary.trend.points.filter { point in
                    !isFutureBucket(point.bucket, granularity: summary.trend.granularity, now: now, timezone: summary.timezone)
                }
            ),
            trendRefCeilingText: maxTokens > 0 ? ceilingText(ceiling) : "",
            trendCeilingFraction: maxTokens > 0 ? Double(maxTokens) / Double(ceiling) : 1.0,
            trendMidFraction: maxTokens > 0 && midVal > 0 ? Double(midVal) / Double(ceiling) : 0,
            trendMidText: maxTokens > 0 && midVal > 0 ? ceilingText(midVal) : "",
            sources: sourceRows(summary.sources, breakdown: summary.breakdown, generatedAt: summary.generatedAt, machineAliases: machineAliases),
            limitRows: sortedLimits(currentProviderWindows).map { limitRow($0, generatedAt: summary.generatedAt) },
            breakdownSections: breakdownSections(summary.breakdown),
            quotaRings: quotaRings(from: quotaDisplaySlots, now: now),
            providerUsageCoverageText: providerUsageCoverageText(summary.providerUsageCoverage),
            serverCards: cards,
            onlineServerCount: cards.filter(\.isOnline).count,
            serverModelQuotaHeader: serverModelQuotaHeader(periodID: summary.period.id)
        )
    }

    private static func dateRangeText(_ period: MobilePeriod) -> String {
        if period.id == "today" { return period.date ?? "日期待加载" }
        guard let start = period.startDate, let end = period.endDate else { return "日期待加载" }
        return start == end ? start : "\(start) ～ \(end)"
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

    static func trendBars(_ trend: MobileTrend, now: Date, timezone: String?) -> [MenuTrendBar] {
        let maxTokens = max(
            trend.points
                .filter { !isFutureBucket($0.bucket, granularity: trend.granularity, now: now, timezone: timezone) }
                .map(\.tokens).max() ?? 0,
            1
        )
        return trend.points.enumerated().map { index, point in
            let isFuture = isFutureBucket(point.bucket, granularity: trend.granularity, now: now, timezone: timezone)
            return MenuTrendBar(
                id: point.bucket,
                label: axisLabel(
                    for: point,
                    index: index,
                    count: trend.points.count,
                    granularity: trend.granularity
                ),
                tooltipTitle: shortBucket(point.bucket, granularity: trend.granularity),
                valueText: isFuture ? "" : TokenFormat.compact(point.tokens),
                ratio: isFuture ? 0 : Double(point.tokens) / Double(maxTokens),
                totalTokens: isFuture ? 0 : max(point.tokens, 0),
                segments: isFuture ? [] : trendSegments(point),
                isFuture: isFuture
            )
        }
    }

    /// bucket 是否晚于「现在」：hour 粒度按完整 ISO 时刻比较；day 粒度（week/month）按 yyyy-MM-dd 本地日期比较。
    static func isFutureBucket(_ bucket: String, granularity: String?, now: Date, timezone: String?) -> Bool {
        let tz = timezone.flatMap(TimeZone.init(identifier:)) ?? TimeZone(identifier: "Asia/Shanghai")!
        if granularity == "hour" {
            guard let bucketDate = parseDate(bucket) else { return false }
            return bucketDate > now
        }
        guard bucket.count >= 10 else { return false }
        let dayFormatter = DateFormatter()
        dayFormatter.locale = Locale(identifier: "en_US_POSIX")
        dayFormatter.timeZone = tz
        dayFormatter.dateFormat = "yyyy-MM-dd"
        let todayStr = dayFormatter.string(from: now)
        let bucketDay = String(bucket.prefix(10))
        return bucketDay > todayStr
    }

    /// #176：段顺序自底向上 claude → codex → antigravity → unknown（Claude 在底）；段和 == tokens（守恒）。
    static func trendSegments(_ point: MobileTrendPoint) -> [MenuTrendSegment] {
        let total = max(point.tokens, 0)
        guard total > 0 else { return [] }

        let rawClaude = max(point.claudeTokens, 0)
        let rawCodex = max(point.codexTokens, 0)
        let rawAntigravity = max(point.geminiTokens, 0)
        let rawKnown = rawClaude + rawCodex + rawAntigravity
        let claude: Int
        let codex: Int
        let antigravity: Int
        if rawKnown <= total {
            claude = rawClaude
            codex = rawCodex
            antigravity = rawAntigravity
        } else if rawKnown == 0 {
            claude = 0
            codex = 0
            antigravity = 0
        } else {
            claude = total * rawClaude / rawKnown
            codex = total * rawCodex / rawKnown
            antigravity = total - claude - codex
        }
        let unknown = total - claude - codex - antigravity

        return [
            (MenuTrendProvider.claude, claude),
            (.codex, codex),
            (.antigravity, antigravity),
            (.unknown, unknown),
        ].compactMap { provider, tokens in
            guard tokens > 0 else { return nil }
            return MenuTrendSegment(
                provider: provider,
                tokens: tokens,
                fraction: Double(tokens) / Double(total)
            )
        }
    }

    /// #176：跨若干 trend point 按 Agent 汇总，顺序 claude → codex → antigravity → unknown，0 的省略。
    /// 供柱图图例合计（trendLegendTotals）与期间菜单行的 segments 共用。
    static func aggregatedSegments(_ points: [MobileTrendPoint]) -> [MenuTrendSegment] {
        var totals: [MenuTrendProvider: Int] = [:]
        var grandTotal = 0
        for point in points {
            for segment in trendSegments(point) {
                totals[segment.provider, default: 0] += segment.tokens
                grandTotal += segment.tokens
            }
        }
        guard grandTotal > 0 else { return [] }
        return [MenuTrendProvider.claude, .codex, .antigravity, .unknown].compactMap { provider in
            guard let tokens = totals[provider], tokens > 0 else { return nil }
            return MenuTrendSegment(provider: provider, tokens: tokens, fraction: Double(tokens) / Double(grandTotal))
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

    public static func formatMachineName(_ raw: String, aliases: [String: String]? = nil) -> String {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "未知设备" }

        if let alias = aliases?[trimmed], !alias.isEmpty {
            return alias
        }

        var cleaned = trimmed
        if cleaned.hasSuffix(".local") {
            cleaned = String(cleaned.dropLast(6))
        }
        if let alias = aliases?[cleaned], !alias.isEmpty {
            return alias
        }

        return cleaned
    }

    public static func formatSourceTitle(label: String, machine: String?, aliases: [String: String]? = nil) -> String {
        if let rawMachine = machine, !rawMachine.isEmpty {
            let prettyMachine = formatMachineName(rawMachine, aliases: aliases)
            if prettyMachine != rawMachine && label.contains(rawMachine) {
                return label.replacingOccurrences(of: rawMachine, with: prettyMachine)
            }
        }
        if let alias = aliases?[label], !alias.isEmpty {
            return alias
        }
        if label.contains(" / ") {
            let parts = label.components(separatedBy: " / ")
            if parts.count == 2 {
                let user = parts[0]
                let mac = formatMachineName(parts[1], aliases: aliases)
                return "\(user) / \(mac)"
            }
        }
        if let alias = aliases?[label], !alias.isEmpty {
            return alias
        }
        return label
    }

    private static func sourceRows(
        _ sources: [MobileSource],
        breakdown: MobileBreakdown,
        generatedAt: String?,
        machineAliases: [String: String]? = nil
    ) -> [MenuDisplayRow] {
        if let rows = breakdown.bySource {
            let metadata = Dictionary(sources.map { ($0.sourceID, $0) }, uniquingKeysWith: { first, _ in first })
            return rows.map { row in
                let source = metadata[row.id]
                let time = compactDateTime(source?.lastObservedAt ?? source?.lastPushedAt, reference: generatedAt, suffix: "更新") ?? "未上报"
                let rawMachine = row.machine ?? source?.machine ?? ""
                let prettyMachine = formatMachineName(rawMachine, aliases: machineAliases)
                let subtitle = [prettyMachine, source?.platform ?? "", time].filter { !$0.isEmpty }.joined(separator: " · ")
                let title = formatSourceTitle(label: row.label, machine: row.machine ?? source?.machine, aliases: machineAliases)

                var flatModels: [MenuFlatModelRow] = []
                if let agents = row.agents {
                    for agent in agents {
                        for model in agent.models {
                            let quotaWeekly = ModelQuotaEstimator.estimateWeeklyQuotaPercentText(
                                modelID: model.id,
                                label: model.label,
                                agentID: agent.id,
                                tokens: model.tokens
                            )
                            flatModels.append(MenuFlatModelRow(
                                id: "\(row.id)/\(agent.id)/\(model.id)",
                                modelID: model.id,
                                label: model.label,
                                agentID: agent.id,
                                tokens: model.tokens,
                                status: model.status,
                                quotaWeeklyPercentText: quotaWeekly
                            ))
                        }
                    }
                }
                flatModels.sort { $0.tokens > $1.tokens }

                return MenuDisplayRow(
                    id: row.id,
                    title: title,
                    subtitle: subtitle,
                    value: TokenFormat.compact(row.tokens),
                    status: source?.status ?? "unknown",
                    platform: source?.platform,
                    agents: row.agents,
                    flatModels: flatModels
                )
            }
        }
        let rows = breakdown.byMachine.isEmpty ? breakdown.byOSUser : breakdown.byMachine
        return rows.map { row in
            let title = formatSourceTitle(label: row.label, machine: nil, aliases: machineAliases)
            return MenuDisplayRow(
                id: row.id,
                title: title,
                subtitle: "来源明细缺失",
                value: TokenFormat.compact(row.tokens),
                status: "missing",
                agents: nil,
                flatModels: nil
            )
        }
    }

    // MARK: - #175 Server 卡片（按机器分组）

    private static func serverCards(
        _ breakdown: MobileBreakdown,
        sources: [MobileSource],
        period: MobilePeriod,
        now: Date,
        timezone: String?,
        machineAliases: [String: String]?
    ) -> [MenuServerCard] {
        let rows = breakdown.byMachine.isEmpty ? breakdown.byOSUser : breakdown.byMachine
        let hasModelDetail = !breakdown.byMachine.isEmpty
        let sourcesByID = Dictionary(sources.map { ($0.sourceID, $0) }, uniquingKeysWith: { first, _ in first })
        let totalTokens = period.totalTokens
        let isMonth = period.id == "month"
        // nil 表示「已计天数」不可靠（缺 start_date，或本地时钟早于 start_date）：
        // 此时不能猜一个换算基准，月视图模型行必须显示「—」而不是被拉伸/压缩的误导数字。
        let weeklyDivisor: Double? = isMonth
            ? countedDaysForMonth(period: period, timezone: timezone, now: now).map { Double($0) / 7.0 }
            : 1.0
        let nowReference = ISO8601DateFormatter().string(from: now)

        return rows.map { row in
            let matchedSources = (row.sourceIDs ?? []).compactMap { sourcesByID[$0] }
            let isOnline = matchedSources.contains { $0.status == "ok" }
            let distinctUsers = Array(Set(matchedSources.compactMap(\.osUser))).sorted()
            let userText: String
            if distinctUsers.count > 1 {
                userText = "\(distinctUsers.count) 个用户"
            } else if let user = distinctUsers.first {
                userText = user
            } else {
                userText = "未知用户"
            }
            let latestTime = matchedSources.compactMap { $0.lastPushedAt ?? $0.lastObservedAt }.max()
            let timeText = compactDateTime(latestTime, reference: nowReference, suffix: "同步") ?? "未同步"
            let platform = matchedSources.compactMap(\.platform).first

            // aliases 的 key 是机器原名（row.id，如上报用的 hostname），不是 breakdown 已经美化过的 label；
            // 先按原名精确查，查不到再走 formatMachineName(row.label, aliases:) 的既有猜测逻辑。
            let title = machineAliases?[row.id].flatMap { $0.isEmpty ? nil : $0 }
                ?? formatMachineName(row.label, aliases: machineAliases)
            let sharePercentText: String
            if totalTokens > 0 {
                sharePercentText = "\(Int((Double(row.tokens) / Double(totalTokens) * 100).rounded()))%"
            } else {
                sharePercentText = "—"
            }

            var models: [MenuServerModelRow] = []
            if hasModelDetail, let agents = row.agents {
                for agent in agents {
                    let agentDisplayName = AgentBranding.displayName(for: agent.id)
                    let brandColor = AgentBranding.color(for: agent.id)
                    for model in agent.models where model.tokens > 0 {
                        let estimate = ModelQuotaEstimator.estimateWeeklyQuota(
                            modelID: model.id,
                            label: model.label,
                            agentID: agent.id,
                            tokens: model.tokens
                        )
                        // weeklyDivisor 为 nil：月视图「已计天数」不可靠，不展示误导数字。
                        // status != "available"：模型明细本身不可信（缺失/未知），不论算出来多少都不展示占比。
                        let adjustedEstimate: ModelQuotaEstimate? = model.status == "available"
                            ? weeklyDivisor.flatMap { divisor in estimate.map { weeklyAveraged($0, divisor: divisor) } }
                            : nil
                        models.append(MenuServerModelRow(
                            id: "\(row.id)/\(agent.id)/\(model.id)",
                            modelID: model.id,
                            agentID: agent.id,
                            agentDisplayName: agentDisplayName,
                            agentBrandColor: brandColor,
                            modelLabel: model.label,
                            tokens: model.tokens,
                            valueText: TokenFormat.compact(model.tokens),
                            status: model.status,
                            quotaText: serverQuotaText(adjustedEstimate, agentDisplayName: agentDisplayName)
                        ))
                    }
                }
            }
            models.sort { lhs, rhs in
                if lhs.tokens != rhs.tokens { return lhs.tokens > rhs.tokens }
                return lhs.modelID < rhs.modelID
            }

            return MenuServerCard(
                id: row.id,
                title: title,
                platform: platform,
                subtitle: "\(userText) · \(timeText)",
                valueText: TokenFormat.compact(row.tokens),
                sharePercentText: sharePercentText,
                isOnline: isOnline,
                models: models
            )
        }
    }

    private static func weeklyAveraged(_ estimate: ModelQuotaEstimate, divisor: Double) -> ModelQuotaEstimate {
        guard divisor > 0 else { return estimate }
        return ModelQuotaEstimate(
            agentID: estimate.agentID,
            percent: estimate.percent / divisor,
            dedicatedPercent: estimate.dedicatedPercent.map { $0 / divisor }
        )
    }

    private static func serverQuotaText(_ estimate: ModelQuotaEstimate?, agentDisplayName: String) -> String {
        guard let estimate else { return "—" }
        if estimate.percent < 0.05 {
            return "\(agentDisplayName) < 0.1%"
        }
        return "\(agentDisplayName) " + String(format: "%.1f%%", estimate.percent)
    }

    /// 月视图「已计天数」：period.start_date 到 min(period.end_date, now 所在日期) 的天数（含首尾）。
    /// 缺 start_date，或本地时钟早于 start_date（now 所在日期 < start_date，视为不可靠时钟/数据），
    /// 返回 nil——调用方必须不做换算并展示「—」，不能猜一个基准去拉伸/压缩累计值。
    private static func countedDaysForMonth(period: MobilePeriod, timezone: String?, now: Date) -> Int? {
        guard let startDateStr = period.startDate, !startDateStr.isEmpty else { return nil }
        let tz = timezone.flatMap(TimeZone.init(identifier:)) ?? TimeZone(identifier: "Asia/Shanghai")!
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = tz

        let dayFormatter = DateFormatter()
        dayFormatter.locale = Locale(identifier: "en_US_POSIX")
        dayFormatter.timeZone = tz
        dayFormatter.dateFormat = "yyyy-MM-dd"

        let todayStr = dayFormatter.string(from: now)
        let endDateStr = period.endDate ?? todayStr
        let cappedEndStr = min(endDateStr, todayStr)

        guard let start = dayFormatter.date(from: startDateStr), let end = dayFormatter.date(from: cappedEndStr) else {
            return nil
        }
        let days = calendar.dateComponents([.day], from: start, to: end).day ?? 0
        // now 所在日期早于 start_date：时钟偏差或数据异常，天数会是负的——不可靠，返回 nil。
        guard days >= 0 else { return nil }
        return days + 1
    }

    private static func serverModelQuotaHeader(periodID: String) -> String {
        periodID == "month" ? "周均占各自周额度" : "约占各自周额度"
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
        let fixedProviders = ["claude", "codex", "antigravity"]
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
        let isHistorical = slot.quota.status != "available"

        let candidates = slot.quota.windows.filter { window in
            guard window.isOfficialObserved && !isLocalEstimate(window.sourceType) else {
                return false
            }
            if isHistorical {
                return true
            }
            return !isExpired(resetAt: window.resetAt, now: now) &&
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
        now: Date
    ) -> [QuotaRingData] {
        // 额度与所选时间段无关：更新时间以「现在」为参照，不参照所选 summary 的 generatedAt。
        let reference = ISO8601DateFormatter().string(from: now)
        let providerOrder = ["claude", "codex", "antigravity"]
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
            case "antigravity":
                name = "Antigravity"
                oR = 0.259; oG = 0.522; oB = 0.957; iR = 0.400; iG = 0.650; iB = 1.0
            default:
                name = provider.prefix(1).uppercased() + provider.dropFirst()
                oR = 0.200; oG = 0.600; oB = 0.800; iR = 0.400; iG = 0.750; iB = 0.900
            }
            let hasVisibleWindow = outerWindow != nil || weekWindow != nil
            // 「最近成功值」（quota 非 available 但保留了旧窗口）也必须降级，不当可信额度展示。
            let isAvailable = slot.quota.status == "available" && hasVisibleWindow
            let primaryWindow = isAvailable ? (weekWindow ?? outerWindow) : nil
            let nearestResetWindow = [outerWindow, weekWindow]
                .filter { _ in isAvailable }
                .compactMap { $0 }
                .compactMap { window -> (MobileLimitWindow, Date)? in
                    guard let reset = parseDate(window.resetAt) else { return nil }
                    return (window, reset)
                }
                .min { $0.1 < $1.1 }?.0
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
                    reference: reference,
                    suffix: "更新"
                ) ?? "未更新",
                availabilityText: quotaAvailabilityText(
                    slot.quota,
                    hasVisibleWindow: hasVisibleWindow
                ),
                usageText: usageText(slot.usage),
                brandColor: brandColor(for: provider),
                primaryPctText: primaryWindow.map { "\(Int($0.usedPercent.rounded()))%" } ?? "—",
                resetCountdownText: nearestResetWindow.flatMap { timeRemainingText($0.resetAt, now: now) } ?? "--",
                isAvailable: isAvailable
            )
        }
    }

    private static func brandColor(for provider: String) -> MenuTrendColor {
        AgentBranding.color(for: provider)
    }

    private static func usageText(_ usage: MobileProviderUsage) -> String {
        guard usage.status == "available" else {
            return "用量不可用"
        }
        let totalTokens = max(usage.totalTokens, 0)
        guard totalTokens > 0 else {
            return "用量 0"
        }
        let cacheTokens = min(max(usage.cacheTokens, 0), totalTokens)
        let cacheRate = Double(cacheTokens) / Double(totalTokens) * 100
        let cacheText = String(
            format: "%.1f%%",
            locale: Locale(identifier: "en_US_POSIX"),
            cacheRate
        )
        return "用量 \(TokenFormat.compact(totalTokens)) · \(cacheText)"
    }

    private static func quotaAvailabilityText(
        _ quota: MobileProviderQuota,
        hasVisibleWindow: Bool
    ) -> String {
        if hasVisibleWindow, quota.status == "available" {
            return ""
        }
        let label: String? = quota.reason.flatMap { reason in
            guard !reason.isEmpty else { return nil }
            switch reason {
            case "no_data": return "暂无数据"
            case "stale": return "数据已过期"
            case "unverified": return "未验证"
            case "unsupported": return "暂不支持"
            case "unavailable", "failed", "provider_failed": return "读取失败"
            default: return reason
            }
        }
        if hasVisibleWindow {
            return "最近成功值 · \(label ?? "当前不可用")"
        }
        guard let label else { return "额度暂不可用" }
        return "额度暂不可用 · \(label)"
    }

    private static func canonicalProvider(_ provider: String) -> String {
        switch provider.lowercased() {
        case "anthropic", "claude": return "claude"
        case "openai", "codex", "gpt": return "codex"
        case "google", "gemini", "antigravity": return "antigravity"
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
        if provider == "antigravity" { return "Antigravity 官方" }
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
        guard let date = parseDate(iso) else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        let isSameDay = reference.flatMap(parseDate).map {
            calendar.isDate(date, inSameDayAs: $0)
        } ?? false
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = isSameDay ? "HH:mm" : "MM-dd HH:mm"
        let text = formatter.string(from: date)
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
