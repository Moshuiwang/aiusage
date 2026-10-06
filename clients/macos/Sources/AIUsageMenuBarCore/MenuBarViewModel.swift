import Foundation

public struct MenuBarState: Equatable, Sendable {
    public let statusTitle: String
    public let periodLabel: String
    /// #186：本机时区与 summary.timezone 当前 UTC 偏移不同时的期间标题标注（如
    /// 「（北京时间）」），偏移相同时为空串。`periodLabel` 本身不含这个标注——期间菜单弹层的
    /// 标题按钮显示的是 `PeriodMenuBuilder` 缓存行的 title（不是 periodLabel），调用方需要把
    /// 这个字段拼到实际渲染的标题文本后面，才能让标注在弹层按钮上也可见。
    public let periodTitleSuffix: String
    public let dateRangeText: String
    public let heroTotalText: String
    public let tokenBreakdownText: String
    public let healthText: String
    public let primaryLimitText: String
    /// #177：标题栏副标题用的钟表时间「HH:mm 更新」（跨天为「MM-dd HH:mm 更新」）。
    public let headerUpdatedText: String
    public let trendBars: [MenuTrendBar]
    /// #176：按 Agent 汇总所有（非未来）柱的分段 tokens，顺序 claude → codex → antigravity → unknown，0 的省略。
    public let trendLegendTotals: [MenuTrendSegment]
    public let trendRefCeilingText: String
    public let trendCeilingFraction: Double
    public let limitRows: [MenuDisplayRow]
    public let breakdownSections: [MenuDisplaySection]
    public let quotaRings: [QuotaRingData]
    public let providerUsageCoverageText: String?
    /// #175：Server 按机器分组的卡片，每张卡展开显示该机器上各模型的用量与「占所属 Agent 周额度」估算。
    public let serverCards: [MenuServerCard]
    /// 标题栏「N 台 Server」只数在线（至少一个 source status == "ok"）的机器。
    public let onlineServerCount: Int
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
    /// 形如 "≈4.9%"；<0.05% 时 "≈<0.1%"；无法估算或 status 非 available 时 "—"。
    public let quotaText: String
    /// #184：quotaText 悬停说明——有估算时讲精度等级与折算口径，没有时讲原因（不得省略，
    /// 避免用户把裸「—」误读成「本模型没有额度」而不是「估算不可用」）。
    public let quotaHelpText: String

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
        quotaText: String,
        quotaHelpText: String
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
        self.quotaHelpText = quotaHelpText
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
    /// #177：单环视图用的主窗口填充比例（周窗口优先，否则 session 窗口；不可用时 0）——
    /// 与 primaryPctText 同口径，供新版单环圆环绘制。
    public let primaryFraction: Double
    public let outerPctText: String
    public let innerPctText: String
    public let outerTimeText: String
    public let innerTimeText: String
    public let outerLabel: String
    public let innerLabel: String
    public let updatedText: String
    public let availabilityText: String
    /// 固定品牌色，不随用量高低变化。
    public let brandColor: MenuTrendColor
    /// 周窗口优先，否则 session 窗口；不可用时 "—"。带 % 后缀，仅供文本整体展示。
    public let primaryPctText: String
    /// #177：不带 % 的主窗口占比数字（如 "26"），不可用时 "—"——视图拼一次单独字号的 %，
    /// 避免 primaryPctText 已带 % 时再次拼接出「26%%」。
    public let primaryPctNumberText: String
    /// 所有可见窗口中最近一次重置的倒计时（如 "3d 23h"），不可用时 "--"。
    public let resetCountdownText: String
    /// 仅当官方观测且状态正常的窗口存在时为 true。
    public let isAvailable: Bool
    /// #177：悬停浮层用的行数据。isAvailable=false 时不含任何百分比——只显示降级状态说明与更新时间，
    /// 不能把「最近成功值」窗口残留的旧百分比泄露到浮层里。
    public let hoverRows: [QuotaHoverRow]
}

/// #177：额度条悬停浮层的一行（标签 + 值文本）。
public struct QuotaHoverRow: Equatable, Sendable, Identifiable {
    public var id: String { label }
    public let label: String
    public let valueText: String

    public init(label: String, valueText: String) {
        self.label = label
        self.valueText = valueText
    }
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

public struct MenuDisplayRow: Equatable, Sendable, Identifiable {
    public let id: String
    public let title: String
    public let subtitle: String
    public let value: String
    public let status: String
    public let platform: String?

    public init(
        id: String,
        title: String,
        subtitle: String,
        value: String,
        status: String,
        platform: String? = nil
    ) {
        self.id = id; self.title = title; self.subtitle = subtitle
        self.value = value; self.status = status; self.platform = platform
    }
}

public struct MenuDisplaySection: Equatable, Sendable, Identifiable {
    public let id: String
    public let title: String
    public let rows: [MenuDisplayRow]
}

public enum MenuBarViewModel {
    // 性能：ISO8601DateFormatter / DateFormatter 的构造本身有实测开销（~0.16ms/次），
    // 一次 build 内会被 parseDate 等调用几十次——缓存复用而不是每次 new。
    // 调用全部发生在主线程同步路径内（SwiftUI body / MenuBarAppModel），可安全共享可变实例。
    nonisolated(unsafe) private static let isoFormatterFractional: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    /// 默认 formatOptions（.withInternetDateTime）——与 `ISO8601DateFormatter().string(from:)` 的
    /// 默认行为一致，因此同一个实例可同时用于「生成参照字符串」与「解析回退」两处。
    nonisolated(unsafe) private static let isoFormatterBasic: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    /// "yyyy-MM-dd" 本地日期比较用；timeZone 按调用方传入的 tz 每次赋值（属性赋值远比重新构造
    /// DateFormatter 便宜——真正贵的是 Locale/TimeZone 查找与对象初始化本身）。
    private static let dayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    /// #186：compactDateTime 用——时区不再固定 Asia/Shanghai，而是随每次调用传入的
    /// deviceTimeZone 赋值（这些都是「时刻类」显示：标题栏更新时间、Server 同步时间、
    /// 额度行重置时刻），dateFormat（HH:mm / MM-dd HH:mm）同样随调用变化。
    private static let compactTimeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        return formatter
    }()

    /// #177 第四轮真机反馈：额度悬停浮层的具体重置时刻用「HH:mm」；#186 起时区随 deviceTimeZone（resetMomentText 每次赋值），不再是 summary.timezone。
    private static let resetMomentTimeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm"
        return formatter
    }()

    /// resetMomentText 用：「M月d日」；#186 起时区随 deviceTimeZone，不再是 summary.timezone。
    private static let resetMomentDayFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "M月d日"
        return formatter
    }()

    public static func build(
        from summary: MobileSummary,
        selectedPeriodID: String,
        selectedOffset: Int = 0,
        now: Date = Date(),
        machineAliases: [String: String]? = nil,
        quotaSlots: [MobileProviderSlot]? = nil,
        additionalSources: [MobileSource] = [],
        // #186：本机时区——默认真实设备时区，测试注入固定时区，绝不依赖运行测试的机器时区。
        // 「时刻类」（悬停重置时刻、标题栏/Server 更新时间）按它显示；「日界类」（今天/本周/本月、
        // 未来时段判定、重置已过判断）仍按 summary.timezone，不受它影响。
        deviceTimeZone: TimeZone = .current
    ) -> MenuBarState {
        let tokenText = TokenFormat.compact(summary.period.totalTokens)
        let summaryTimeZone = summary.timezone.flatMap(TimeZone.init(identifier:)) ?? TimeZone(identifier: "Asia/Shanghai")!
        // #186：仅当本机时区与 summary.timezone 的当前 UTC 偏移不同时才标注——国内使用时
        // （本机时区 == 服务时区）界面必须与现状逐字一致，不能无条件加标注。
        let tzDiffers = deviceTimeZone.secondsFromGMT(for: now) != summaryTimeZone.secondsFromGMT(for: now)
        let periodTitleSuffix = tzDiffers ? timezoneAnnotation(summaryTimeZone) : ""
        let hourAxisPrefix = tzDiffers ? timezoneAxisPrefix(summaryTimeZone) : nil
        let okCount = summary.sources.filter { $0.status == "ok" }.count
        let problemCount = summary.sources.filter { $0.status != "ok" && $0.status != "disabled" }.count
        let displaySlots = fixedProviderSlots(summary.providerSlots)
        let quotaDisplaySlots = fixedProviderSlots(quotaSlots ?? summary.providerSlots)
        let limitWindows = currentProviderWindows(displaySlots, now: now)
        let primaryLimit = limitWindows
            .sorted { lhs, rhs in
                if lhs.usedPercent == rhs.usedPercent {
                    return lhs.id.localizedStandardCompare(rhs.id) == .orderedAscending
                }
                return lhs.usedPercent > rhs.usedPercent
            }
            .first
        // 额度环所需的窗口在此一次性算好（每个 slot 一次 trustedProviderWindows），
        // 而不是在 quotaRings 内部按 slot 重算一遍。
        let quotaSlotsWithWindows = quotaDisplaySlots.map { slot in
            (slot, currentProviderWindows([slot], now: now))
        }

        // 每个 trend point 的 isFuture 只判定一次，maxTokens/图例合计/柱状图三处复用，
        // 而不是各自重新扫描一遍 points。
        let futureFlags = summary.trend.points.map {
            isFutureBucket($0.bucket, granularity: summary.trend.granularity, now: now, timezone: summary.timezone)
        }
        let nonFuturePoints = zip(summary.trend.points, futureFlags).filter { !$0.1 }.map(\.0)
        let maxTokens = nonFuturePoints.map(\.tokens).max() ?? 0
        let ceiling = maxTokens > 0 ? ceilingValue(maxTokens) : 1

        let cards = serverCards(
            summary.breakdown,
            sources: summary.sources,
            period: summary.period,
            now: now,
            machineAliases: machineAliases,
            deviceTimeZone: deviceTimeZone
        )

        let bars = trendBars(
            summary.trend, futureFlags: futureFlags, maxTokens: maxTokens, hourAxisPrefix: hourAxisPrefix
        )

        let basePeriodLabel = selectedOffset == 0
            ? periodLabel(selectedPeriodID)
            : (selectedPeriodID == "today" ? "历史日期" : selectedPeriodID == "week" ? "历史周" : "历史月")

        return MenuBarState(
            statusTitle: tokenText,
            periodLabel: basePeriodLabel,
            periodTitleSuffix: periodTitleSuffix,
            dateRangeText: dateRangeText(summary.period),
            heroTotalText: tokenText,
            tokenBreakdownText: tokenBreakdownText(summary.period),
            healthText: healthText(okCount: okCount, total: summary.sources.count, problemCount: problemCount),
            primaryLimitText: primaryLimitText(primaryLimit),
            headerUpdatedText: headerUpdatedText(
                summary.sources + additionalSources, fallback: summary.generatedAt, now: now, deviceTimeZone: deviceTimeZone
            ),
            trendBars: bars,
            trendLegendTotals: aggregatedSegments(nonFuturePoints),
            trendRefCeilingText: maxTokens > 0 ? ceilingText(ceiling) : "",
            trendCeilingFraction: maxTokens > 0 ? Double(maxTokens) / Double(ceiling) : 1.0,
            limitRows: sortedLimits(limitWindows).map {
                limitRow($0, generatedAt: summary.generatedAt, timezone: summary.timezone, deviceTimeZone: deviceTimeZone)
            },
            breakdownSections: breakdownSections(summary.breakdown),
            quotaRings: quotaRings(
                from: quotaSlotsWithWindows,
                now: now,
                deviceTimeZone: deviceTimeZone
            ),
            providerUsageCoverageText: providerUsageCoverageText(summary.providerUsageCoverage),
            serverCards: cards,
            onlineServerCount: cards.filter(\.isOnline).count
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

    /// #177：标题栏副标题用的钟表时间「HH:mm 更新」（同日）或「MM-dd HH:mm 更新」（跨天）。
    /// #186：时刻类——按本机时区显示，不再固定 Asia/Shanghai。
    private static func headerUpdatedText(
        _ sources: [MobileSource], fallback: String?, now: Date, deviceTimeZone: TimeZone
    ) -> String {
        let latest = latestISOString(sources.compactMap { $0.lastObservedAt })
        let nowRef = isoFormatterBasic.string(from: now)
        return compactDateTime(latest ?? fallback, reference: nowRef, suffix: "更新", timezone: deviceTimeZone) ?? "--"
    }

    /// #186：summary.timezone 为 Asia/Shanghai 时用「北京时间」，其余时区没有一个通用的
    /// 中文简称，用「服务时区」——不编一个可能误导的地名。
    private static func timezoneAnnotation(_ summaryTimeZone: TimeZone) -> String {
        summaryTimeZone.identifier == "Asia/Shanghai" ? "（北京时间）" : "（服务时区）"
    }

    /// #186：小时横轴标注前缀，与 timezoneAnnotation 用同一套判断——Asia/Shanghai 用「北京 」，
    /// 其余时区用「服务区 」。
    private static func timezoneAxisPrefix(_ summaryTimeZone: TimeZone) -> String {
        summaryTimeZone.identifier == "Asia/Shanghai" ? "北京 " : "服务区 "
    }

    /// #177：用量区总量下方的分项文案，缓存段用命中率百分比而不是原始 token 数。
    private static func tokenBreakdownText(_ period: MobilePeriod) -> String {
        let total = max(period.totalTokens, 0)
        let cacheTokens = min(max(period.cacheTokens, 0), max(total, 0))
        let cacheRate = total > 0 ? Double(cacheTokens) / Double(total) * 100 : 0
        let cacheText = String(format: "%.1f%%", locale: Locale(identifier: "en_US_POSIX"), cacheRate)
        return [
            "输入 \(TokenFormat.compact(period.inputTokens))",
            "输出 \(TokenFormat.compact(period.outputTokens))",
            "缓存命中 \(cacheText)",
        ].joined(separator: " · ")
    }

    /// - Parameters:
    ///   - futureFlags: 每个 point 对应的 isFuture，须与 trend.points 等长且同序——由调用方
    ///     一次性算好传入，避免这里再重新扫描一遍 points。
    ///   - maxTokens: 非未来 points 的 token 最大值（未做 floor(1)），调用方已经算过一次。
    ///   - hourAxisPrefix: #186 本机时区与 summary.timezone 当前 UTC 偏移不同时，hour 粒度横轴
    ///     标签的前缀（如 "北京 "）；nil 表示不标注（偏移相同，保持现状）。
    static func trendBars(
        _ trend: MobileTrend, futureFlags: [Bool], maxTokens: Int, hourAxisPrefix: String? = nil
    ) -> [MenuTrendBar] {
        let denominator = max(maxTokens, 1)
        return trend.points.enumerated().map { index, point in
            let isFuture = index < futureFlags.count ? futureFlags[index] : false
            return MenuTrendBar(
                id: point.bucket,
                label: axisLabel(
                    for: point,
                    index: index,
                    count: trend.points.count,
                    granularity: trend.granularity,
                    hourAxisPrefix: hourAxisPrefix
                ),
                tooltipTitle: shortBucket(point.bucket, granularity: trend.granularity),
                valueText: isFuture ? "" : TokenFormat.compact(point.tokens),
                ratio: isFuture ? 0 : Double(point.tokens) / Double(denominator),
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
        dayFormatter.timeZone = tz
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

    private static func axisLabel(
        for point: MobileTrendPoint, index: Int, count: Int, granularity: String?, hourAxisPrefix: String? = nil
    ) -> String {
        guard shouldShowAxisLabel(index: index, count: count) else {
            return ""
        }
        // #177 真机反馈：hour 粒度的横轴刻度改用「N点」（如 "0点"/"12点"/"23点"），
        // 与仍用 "HH:mm" 的 tooltip/图例联动展示分开——day 粒度保持现状（MM-dd）。
        if granularity == "hour" {
            return hourAxisLabel(point.bucket, prefix: hourAxisPrefix) ?? shortBucket(point.bucket, granularity: granularity)
        }
        return shortBucket(point.bucket, granularity: granularity)
    }

    /// - Parameter prefix: #186 本机时区与 summary.timezone 当前 UTC 偏移不同时传入的标注
    ///   （如 "北京 "），拼在小时数字前——bucket 本身仍是 summary 时区的小时（isFutureBucket/
    ///   trendSegments 等日界判断不受影响，这里只是给已算好的小时数字加一个说明性前缀）。
    private static func hourAxisLabel(_ bucket: String, prefix: String? = nil) -> String? {
        guard bucket.count >= 13, bucket.dropFirst(10).first == "T" else { return nil }
        let hourStart = bucket.index(bucket.startIndex, offsetBy: 11)
        let hourEnd = bucket.index(bucket.startIndex, offsetBy: 13)
        guard let hour = Int(bucket[hourStart..<hourEnd]) else { return nil }
        return "\(prefix ?? "")\(hour)点"
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

    // MARK: - #175 Server 卡片（按机器分组）

    private static func serverCards(
        _ breakdown: MobileBreakdown,
        sources: [MobileSource],
        period: MobilePeriod,
        now: Date,
        machineAliases: [String: String]?,
        deviceTimeZone: TimeZone
    ) -> [MenuServerCard] {
        let rows = breakdown.byMachine.isEmpty ? breakdown.byOSUser : breakdown.byMachine
        let hasModelDetail = !breakdown.byMachine.isEmpty
        let sourcesByID = Dictionary(sources.map { ($0.sourceID, $0) }, uniquingKeysWith: { first, _ in first })
        let totalTokens = period.totalTokens
        let nowReference = isoFormatterBasic.string(from: now)

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
            let latestTime = latestISOString(matchedSources.compactMap { $0.lastPushedAt ?? $0.lastObservedAt })
            let timeText = compactDateTime(latestTime, reference: nowReference, suffix: "同步", timezone: deviceTimeZone) ?? "未同步"
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
                        // #184：只在 status == "available" 时信任服务端 quota_estimate——非 available
                        // 的模型行（如「模型未知」撤销分摊占位）即便意外带了字段也不能展示估算。
                        let estimate = model.status == "available" ? model.quotaEstimate : nil
                        let (quotaText, quotaHelpText) = Self.quotaEstimateTexts(estimate, unavailable: model.status == "available" ? model.quotaEstimateUnavailable : nil)
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
                            quotaText: quotaText,
                            quotaHelpText: quotaHelpText
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

    /// #184：把服务端 `quota_estimate` 变成展示文本 + 悬停说明。
    /// 数值必须带「≈」——AGENTS.md 关键不变量：不得把估算伪装成官方额度。
    /// 追加：未知 grade（不是 "A"/"B"）视同没有估算——服务端合同只承诺下发 A/B
    /// （见 quota-estimate.ts），客户端不为陌生等级编一句听起来权威的说明。
    private static func quotaEstimateTexts(_ estimate: MobileQuotaEstimate?, unavailable: MobileQuotaEstimateUnavailable?) -> (text: String, helpText: String) {
        guard let estimate, let gradeHelpText = gradePrecisionHelpText(estimate.grade) else {
            return quotaUnavailableTexts(unavailable)
        }
        let text: String
        if estimate.percent < 0.05 {
            text = "≈<0.1%"
        } else {
            text = String(format: "≈%.1f%%", estimate.percent)
        }
        var helpText = gradeHelpText
        if estimate.basis == "weekly_average" {
            helpText += "；月视图为周均"
        }
        return (text, helpText)
    }

    private static func quotaUnavailableTexts(_ unavailable: MobileQuotaEstimateUnavailable?) -> (String, String) {
        switch unavailable?.reason {
        case "backtest_failed":
            var help = "换算回测未通过"
            if let error = unavailable?.backtestMaxError, error.isFinite, error >= 0 {
                help += String(format: "：账户最大误差%.1f%%（要求≤25%%）", error * 100)
            }
            if let samples = unavailable?.sampleIntervals, samples >= 0 {
                help += "，\(samples)个区间"
            }
            return ("未达标", help + "；暂不估算")
        case "insufficient_data": return ("数据不足", "有效校准数据不足，暂不估算")
        case "stale": return ("已过期", "校准已过期，暂不估算")
        case "formula_changed": return ("未校准", "换算口径已更新，等待重新校准")
        case "not_calibrated": return ("未校准", "尚无可用校准，暂不估算")
        case "unsupported_model": return ("—", "当前模型尚不支持额度换算")
        case "unsupported_period": return ("—", "全部历史尚无周额度换算口径")
        default: return ("—", "校准中或数据不足，暂不估算")
        }
    }

    private static func gradePrecisionHelpText(_ grade: String) -> String? {
        switch grade {
        case "A": return "估算精度 A（约 ±10%），基于官方额度校准"
        case "B": return "估算精度 B（约 ±25%），基于官方额度校准"
        default: return nil
        }
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
        // 真机 bug 同类修复：不同来源可能带不同时区 offset，直接比较 ISO 字符串是字典序，
        // 必须先解析成真实时间再比较（同 latestISOString 的思路）。
        return (parseDate(candidate.observedAt) ?? .distantPast) > (parseDate(existing.observedAt) ?? .distantPast)
    }

    /// - Parameter slotsWithWindows: (slot, currentProviderWindows([slot], now:)) 对，由调用方
    ///   （build）一次性算好传入，避免每个 slot 在这里重新触发一遍 trustedProviderWindows。
    private static func quotaRings(
        from slotsWithWindows: [(MobileProviderSlot, [MobileLimitWindow])],
        now: Date,
        deviceTimeZone: TimeZone
    ) -> [QuotaRingData] {
        // 额度与所选时间段无关：更新时间以「现在」为参照，不参照所选 summary 的 generatedAt。
        let reference = isoFormatterBasic.string(from: now)
        let providerOrder = ["claude", "codex", "antigravity"]
        return slotsWithWindows.sorted {
            let lhs = providerOrder.firstIndex(of: canonicalProvider($0.0.provider)) ?? providerOrder.count
            let rhs = providerOrder.firstIndex(of: canonicalProvider($1.0.provider)) ?? providerOrder.count
            return lhs == rhs ? $0.0.provider < $1.0.provider : lhs < rhs
        }.map { slot, wins in
            let provider = canonicalProvider(slot.provider)
            let bestWindows = bestWindowPerType(wins)
            let sessionWindow = bestWindows.first(where: isSessionLimitWindow)
            let weekWindow = bestWindows.first(where: isWeekLimitWindow)
            let otherWindow = bestWindows
                .filter { !isSessionLimitWindow($0) && !isWeekLimitWindow($0) }
                .sorted { $0.windowDurationMinutes < $1.windowDurationMinutes }
                .first
            let outerWindow = sessionWindow ?? otherWindow
            let verifiedAt = slot.quota.lastVerifiedAt ?? latestISOString(wins.compactMap(\.observedAt))
            let name: String
            switch provider {
            case "claude": name = "Claude"
            case "codex": name = "Codex"
            case "antigravity": name = "Antigravity"
            default: name = provider.prefix(1).uppercased() + provider.dropFirst()
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
            let availabilityTextValue = quotaAvailabilityText(slot.quota, hasVisibleWindow: hasVisibleWindow)
            let updatedTextValue = compactDateTime(verifiedAt, reference: reference, suffix: "更新", timezone: deviceTimeZone) ?? "未更新"
            // #177：浮层不得泄露「最近成功值」残留的旧百分比——isAvailable=false 时只给状态说明 + 更新时间，
            // 不能沿用 outerPctText/innerPctText（它们对 isHistorical 的 quota 仍可能带着旧窗口的百分比）。
            // #177 真机反馈：只显示确实有数据的窗口行——某个 Agent 只有 7d/week 窗口时
            // （如 Codex），不能在悬停浮层里造出一条「额度 — · --」的空占位行。
            let hoverRows: [QuotaHoverRow]
            if isAvailable {
                hoverRows = [
                    weekWindow.map { window in
                        QuotaHoverRow(
                            label: windowLabel(window),
                            valueText: [
                                "\(Int(window.usedPercent.rounded()))%",
                                resetMomentText(window.resetAt, timezone: deviceTimeZone, now: now) ?? "--",
                            ].joined(separator: " · ")
                        )
                    },
                    outerWindow.map { window in
                        QuotaHoverRow(
                            label: windowLabel(window),
                            valueText: [
                                "\(Int(window.usedPercent.rounded()))%",
                                resetMomentText(window.resetAt, timezone: deviceTimeZone, now: now) ?? "--",
                            ].joined(separator: " · ")
                        )
                    },
                ].compactMap { $0 }
            } else {
                hoverRows = [
                    QuotaHoverRow(
                        label: "状态",
                        valueText: [
                            availabilityTextValue.isEmpty ? "暂不可用" : availabilityTextValue,
                            updatedTextValue,
                        ].joined(separator: " · ")
                    )
                ]
            }
            return QuotaRingData(
                id: provider, displayName: name,
                primaryFraction: (primaryWindow?.usedPercent ?? 0) / 100.0,
                outerPctText: outerWindow.map { "\(Int($0.usedPercent.rounded()))%" } ?? "--",
                innerPctText: weekWindow.map { "\(Int($0.usedPercent.rounded()))%" } ?? "--",
                outerTimeText: outerWindow.flatMap { timeRemainingText($0.resetAt, now: now) } ?? "--",
                innerTimeText: weekWindow.flatMap { timeRemainingText($0.resetAt, now: now) } ?? "--",
                outerLabel: outerWindow.map(windowLabel) ?? "额度",
                innerLabel: weekWindow.map(windowLabel) ?? "长期",
                updatedText: updatedTextValue,
                availabilityText: availabilityTextValue,
                brandColor: brandColor(for: provider),
                primaryPctText: primaryWindow.map { "\(Int($0.usedPercent.rounded()))%" } ?? "—",
                primaryPctNumberText: primaryWindow.map { "\(Int($0.usedPercent.rounded()))" } ?? "—",
                resetCountdownText: nearestResetWindow.flatMap { timeRemainingText($0.resetAt, now: now) } ?? "--",
                isAvailable: isAvailable,
                hoverRows: hoverRows
            )
        }
    }

    private static func brandColor(for provider: String) -> MenuTrendColor {
        AgentBranding.color(for: provider)
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

    /// #177 第四轮真机反馈：额度悬停浮层的重置时刻改用具体时间点，不再是倒计时——圆环旁的
    /// resetCountdownText 不受影响，仍用 timeRemainingText。#186 起 timezone 参数由调用方传入
    /// deviceTimeZone（时刻类，按本机时区），不再是 summary.timezone。
    /// 同一天简写「今天 HH:mm」，次日「明天 HH:mm」，其余「M月d日 周X HH:mm」。
    /// internal（非 private）：与 trendBars/isFutureBucket 等同款惯例——供单测直接调用，
    /// 不必绕开 build() 里 trustedProviderWindows 的过期过滤才能测到边界分支。
    static func resetMomentText(_ resetAt: String?, timezone: TimeZone, now: Date) -> String? {
        guard let date = parseDate(resetAt) else { return nil }
        // #177 第四轮 Opus 审查：与圆环旁 timeRemainingText 的 secs<=0 分支保持一致——
        // resetAt 已经过去（或恰好等于 now）时必须显示「即将重置」，不能显示一个已经过去的
        // 具体钟点让人误以为它还没重置。
        guard date > now else { return "即将重置" }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timezone
        let dayDiff = calendar.dateComponents(
            [.day],
            from: calendar.startOfDay(for: now),
            to: calendar.startOfDay(for: date)
        ).day ?? 0

        resetMomentTimeFormatter.timeZone = timezone
        let timeText = resetMomentTimeFormatter.string(from: date)
        switch dayDiff {
        case 0:
            return "今天 \(timeText)"
        case 1:
            return "明天 \(timeText)"
        default:
            resetMomentDayFormatter.timeZone = timezone
            let weekday = calendar.component(.weekday, from: date)
            return "\(resetMomentDayFormatter.string(from: date)) \(weekdayShortName(weekday)) \(timeText)"
        }
    }

    /// Calendar.component(.weekday) 返回 1=周日...7=周六。
    private static func weekdayShortName(_ weekday: Int) -> String {
        let names = ["", "周日", "周一", "周二", "周三", "周四", "周五", "周六"]
        guard weekday >= 1, weekday <= 7 else { return "" }
        return names[weekday]
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
        if let date = isoFormatterFractional.date(from: iso) {
            return date
        }
        return isoFormatterBasic.date(from: iso)
    }

    /// 真机 bug：不同来源可能带不同时区 offset（如 +00:00 与 +08:00），直接对 ISO
    /// 字符串做 `.max()` 是字典序比较，会选错「最新」——必须先解析成真实时间再比较。
    /// 解析失败的字符串按 .distantPast 处理，不让它们意外赢过能解析的时间。
    private static func latestISOString(_ values: [String]) -> String? {
        values.max { lhs, rhs in
            (parseDate(lhs) ?? .distantPast) < (parseDate(rhs) ?? .distantPast)
        }
    }

    private static func ceilingValue(_ maxTokens: Int) -> Int {
        let tiers = [1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 100_000, 200_000, 500_000,
                     1_000_000, 2_000_000, 5_000_000, 10_000_000, 20_000_000, 50_000_000,
                     100_000_000, 200_000_000, 500_000_000,
                     1_000_000_000, 2_000_000_000, 5_000_000_000]
        return tiers.first { $0 > maxTokens } ?? (maxTokens * 2)
    }

    private static func ceilingText(_ ceiling: Int) -> String {
        if ceiling >= 1_000_000_000 { return "\(ceiling / 1_000_000_000)B" }
        if ceiling >= 1_000_000 { return "\(ceiling / 1_000_000)M" }
        if ceiling >= 1_000 { return "\(ceiling / 1_000)K" }
        return "\(ceiling)"
    }

    private static func limitRow(
        _ window: MobileLimitWindow, generatedAt: String?, timezone: String?, deviceTimeZone: TimeZone
    ) -> MenuDisplayRow {
        let availability = window.isOfficialObserved ? "\(Int(window.remainingPercent.rounded()))% 可用" : "未观测"
        let used = "\(Int(window.usedPercent.rounded()))% 已用"
        return MenuDisplayRow(
            id: window.id,
            title: "\(providerName(window.provider)) \(window.window)",
            subtitle: "\(used) · \(availability) · \(window.confidence)",
            value: compactResetTime(window.resetAt, generatedAt: generatedAt, timezone: timezone, deviceTimeZone: deviceTimeZone) ?? "--",
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

    /// #186：timezone 参数不再固定 Asia/Shanghai——调用方传入 deviceTimeZone（这些都是「时刻类」
    /// 显示：标题栏/Server 更新时间、额度行重置时刻），同日/跨日判断与实际渲染的钟点统一按它来。
    private static func compactDateTime(_ iso: String?, reference: String?, suffix: String, timezone: TimeZone) -> String? {
        guard let date = parseDate(iso) else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timezone
        let isSameDay = reference.flatMap(parseDate).map {
            calendar.isDate(date, inSameDayAs: $0)
        } ?? false
        compactTimeFormatter.timeZone = timezone
        compactTimeFormatter.dateFormat = isSameDay ? "HH:mm" : "MM-dd HH:mm"
        let text = compactTimeFormatter.string(from: date)
        return "\(text) \(suffix)"
    }

    /// #186：「已过/重置」的日历日判断属于「日界类」——继续按 summary.timezone（timezone 参数），
    /// 不受本机时区影响；实际渲染的钟点属于「时刻类」——改用 deviceTimeZone。
    private static func compactResetTime(
        _ resetAt: String?, generatedAt: String?, timezone: String?, deviceTimeZone: TimeZone
    ) -> String? {
        guard let resetAt else { return nil }
        // 真机 bug 同类修复：resetAt / generatedAt 各自带不同时区 offset 时，日期部分的原始
        // 字符串前缀可能相同或反直觉地大小颠倒（同一 UTC 时刻换算成北京时间可能已经跨天），
        // 必须解析成真实时间、按北京日历日比较，不能比较字符串前缀。
        let suffix: String
        if let resetDate = parseDate(resetAt), let generatedAt, let generatedDate = parseDate(generatedAt) {
            var calendar = Calendar(identifier: .gregorian)
            calendar.timeZone = timezone.flatMap(TimeZone.init(identifier:)) ?? TimeZone(identifier: "Asia/Shanghai")!
            suffix = calendar.startOfDay(for: resetDate) < calendar.startOfDay(for: generatedDate) ? "已过" : "重置"
        } else {
            suffix = "重置"
        }
        return compactDateTime(resetAt, reference: generatedAt, suffix: suffix, timezone: deviceTimeZone)
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
