#if os(watchOS)
import SwiftUI
import WidgetKit

enum QuotaRingSelection {
    case codex
    case claude
}

struct QuotaRingEntry: TimelineEntry {
    let date: Date
    let state: QuotaRingState
}

struct TodayChartEntry: TimelineEntry {
    let date: Date
    let state: TodayChartState
}

struct QuotaRingState {
    let title: String
    let accountShortName: String
    let outerUsedPercent: Int
    let innerUsedPercent: Int
    let remainingPercent: Int
    let resetText: String
    let outerColor: Color
    let innerColor: Color
    let isStale: Bool

    static func build(from summary: WatchMobileSummary?, selection: QuotaRingSelection) -> QuotaRingState {
        guard let summary else {
            return empty(selection: selection, isStale: false)
        }
        let isStale = WatchSummaryFreshness.isStale(summary)

        let windows = summary.limits.windows.filter(\.isOfficialObserved)
        let candidates = windows
            .filter { providerMatches($0.provider, selection: selection) }
            .sorted { lhs, rhs in
                if isShortWindow(lhs) != isShortWindow(rhs) {
                    return isShortWindow(lhs)
                }
                return lhs.remainingPercent < rhs.remainingPercent
            }
        guard let primaryWindow = candidates.first else {
            return empty(selection: selection, isStale: isStale)
        }
        let providerWindows = windows.filter { providerMatches($0.provider, provider: primaryWindow.provider) }

        let shortWindow = providerWindows.first(where: isShortWindow) ?? primaryWindow
        let longWindow = providerWindows.first(where: { !isShortWindow($0) }) ?? shortWindow

        return QuotaRingState(
            title: providerLabel(primaryWindow.provider),
            accountShortName: accountShortName(primaryWindow),
            outerUsedPercent: shortWindow.usedPercent,
            innerUsedPercent: longWindow.usedPercent,
            remainingPercent: max(0, min(100, Int(primaryWindow.remainingPercent.rounded()))),
            resetText: isStale ? "stale" : resetLabel(primaryWindow.resetAt),
            outerColor: providerOuterColor(primaryWindow.provider),
            innerColor: providerInnerColor(primaryWindow.provider),
            isStale: WatchSummaryFreshness.isStale(summary)
        )
    }

    private static func empty(selection: QuotaRingSelection, isStale: Bool) -> QuotaRingState {
        let provider = selection == .claude ? "claude" : "codex"
        return QuotaRingState(
            title: providerLabel(provider),
            accountShortName: selection == .claude ? "CLAU" : "CODE",
            outerUsedPercent: 0,
            innerUsedPercent: 0,
            remainingPercent: 0,
            resetText: isStale ? "stale" : "--",
            outerColor: providerOuterColor(provider),
            innerColor: providerInnerColor(provider),
            isStale: isStale
        )
    }

    private static func isShortWindow(_ window: WatchLimitWindow) -> Bool {
        let value = window.window.lowercased()
        return value == "session"
            || value.contains("5h")
            || ((window.windowDurationMinutes ?? 0) > 0 && (window.windowDurationMinutes ?? 0) <= 360)
    }

    private static func providerMatches(_ provider: String, selection: QuotaRingSelection) -> Bool {
        let value = provider.lowercased()
        switch selection {
        case .codex:
            return value.contains("codex") || value.contains("openai")
        case .claude:
            return value.contains("claude") || value.contains("anthropic")
        }
    }

    private static func providerMatches(_ provider: String, provider target: String) -> Bool {
        providerLabel(provider) == providerLabel(target)
    }

    private static func providerLabel(_ value: String) -> String {
        let lower = value.lowercased()
        if lower.contains("claude") || lower.contains("anthropic") {
            return "Claude"
        }
        if lower.contains("codex") || lower.contains("openai") {
            return "Codex"
        }
        return value.prefix(1).uppercased() + value.dropFirst()
    }

    private static func accountShortName(_ window: WatchLimitWindow) -> String {
        if let account = window.accountLabel, !account.isEmpty {
            let normalized = account.split(separator: "@").first.map(String.init) ?? account
            return String(normalized.prefix(4)).uppercased()
        }
        if let plan = window.accountPlanLabel, !plan.isEmpty {
            return String(plan.prefix(4)).uppercased()
        }
        return String(providerLabel(window.provider).prefix(4)).uppercased()
    }

    private static func resetLabel(_ value: String?) -> String {
        guard let value else {
            return "--"
        }
        return WatchSummaryFreshness.resetText(value).replacingOccurrences(of: "reset ", with: "")
    }

    private static func providerOuterColor(_ provider: String) -> Color {
        let lower = provider.lowercased()
        if lower.contains("claude") || lower.contains("anthropic") {
            return Color(red: 218 / 255, green: 119 / 255, blue: 86 / 255)
        }
        return Color(red: 10 / 255, green: 132 / 255, blue: 1)
    }

    private static func providerInnerColor(_ provider: String) -> Color {
        let lower = provider.lowercased()
        if lower.contains("claude") || lower.contains("anthropic") {
            return Color(red: 234 / 255, green: 168 / 255, blue: 130 / 255)
        }
        return Color(red: 90 / 255, green: 200 / 255, blue: 250 / 255)
    }
}

struct TodayChartState {
    let totalText: String
    let points: [WatchTrendPoint]
    let isStale: Bool

    static func build(from summary: WatchMobileSummary?) -> TodayChartState {
        TodayChartState(
            totalText: TokenFormat.compact(summary?.period.totalTokens ?? 0),
            points: normalizedHourlyPoints(summary?.trend.points ?? []),
            isStale: summary.map { WatchSummaryFreshness.isStale($0) } ?? false
        )
    }

    private static func normalizedHourlyPoints(_ points: [WatchTrendPoint]) -> [WatchTrendPoint] {
        let targetCount = 24
        let source = Array(points.suffix(targetCount))
        if source.count == targetCount {
            return source
        }
        let paddingCount = targetCount - source.count
        let padded = (0..<paddingCount).map { index in
            WatchTrendPoint(
                bucket: "sim-hour-\(index)",
                label: "\(index)",
                tokens: 0
            )
        }
        return padded + source
    }
}

struct FixedQuotaRingProvider: TimelineProvider {
    let selection: QuotaRingSelection

    func placeholder(in context: Context) -> QuotaRingEntry {
        QuotaRingEntry(date: Date(), state: .build(from: WatchSummaryStore.read(), selection: selection))
    }

    func getSnapshot(in context: Context, completion: @escaping (QuotaRingEntry) -> Void) {
        completion(QuotaRingEntry(date: Date(), state: .build(from: WatchSummaryStore.read(), selection: selection)))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<QuotaRingEntry>) -> Void) {
        let entry = QuotaRingEntry(date: Date(), state: .build(from: WatchSummaryStore.read(), selection: selection))
        completion(Timeline(entries: [entry], policy: .after(Date().addingTimeInterval(15 * 60))))
    }
}

struct TodayChartProvider: TimelineProvider {
    func placeholder(in context: Context) -> TodayChartEntry {
        TodayChartEntry(date: Date(), state: .build(from: WatchSummaryStore.read()))
    }

    func getSnapshot(in context: Context, completion: @escaping (TodayChartEntry) -> Void) {
        completion(TodayChartEntry(date: Date(), state: .build(from: WatchSummaryStore.read())))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<TodayChartEntry>) -> Void) {
        let entry = TodayChartEntry(date: Date(), state: .build(from: WatchSummaryStore.read()))
        completion(Timeline(entries: [entry], policy: .after(Date().addingTimeInterval(15 * 60))))
    }
}

struct QuotaRingComplicationView: View {
    @Environment(\.widgetFamily) private var family
    let entry: QuotaRingEntry

    var body: some View {
        switch family {
        case .accessoryCircular:
            circular
        case .accessoryCorner:
            corner
        case .accessoryInline:
            inline
        default:
            inline
        }
    }

    private var circular: some View {
        ZStack {
            AccessoryWidgetBackground()
            Circle()
                .stroke(Color.primary.opacity(0.08), lineWidth: 5.6)
                .padding(2)
            Circle().trim(from: 0, to: CGFloat(entry.state.outerUsedPercent) / 100)
                .stroke(entry.state.outerColor, style: StrokeStyle(lineWidth: 5.6, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .padding(2)
            Circle()
                .stroke(Color.primary.opacity(0.08), lineWidth: 4.2)
                .padding(11)
            Circle().trim(from: 0, to: CGFloat(entry.state.innerUsedPercent) / 100)
                .stroke(entry.state.innerColor, style: StrokeStyle(lineWidth: 4.2, lineCap: .round))
                .rotationEffect(.degrees(-90))
                .padding(11)
            Text(entry.state.accountShortName)
                .font(.system(size: 8, weight: .semibold, design: .rounded))
                .foregroundStyle(.primary.opacity(0.88))
                .lineLimit(1)
                .minimumScaleFactor(0.5)
                .frame(width: 24)
            if entry.state.isStale {
                Text("stale")
                    .font(.system(size: 7, weight: .bold, design: .rounded))
                    .foregroundStyle(.secondary)
                    .offset(y: 17)
                    .lineLimit(1)
            }
        }
        .widgetLabel {
            Text("\(entry.state.title) \(entry.state.remainingPercent)% left · Reset \(entry.state.resetText)")
        }
    }

    private var inline: some View {
        if entry.state.isStale {
            Text("\(entry.state.title) \(entry.state.accountShortName) · stale")
        } else {
            Text("\(entry.state.title) \(entry.state.accountShortName) · Reset \(entry.state.resetText)")
        }
    }

    private var corner: some View {
        Text(entry.state.isStale ? "stale" : "\(entry.state.outerUsedPercent)%")
            .font(.system(size: 13, weight: .semibold, design: .rounded))
            .widgetCurvesContent()
            .widgetLabel {
                Text("\(entry.state.title) · Reset \(entry.state.resetText)")
            }
    }
}

struct TodayChartComplicationView: View {
    let entry: TodayChartEntry

    var body: some View {
        ZStack(alignment: .top) {
            ComplicationBarChart(points: entry.state.points)
                .padding(.top, 12)
            HStack {
                Text("Today Usage")
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Spacer()
                Text(entry.state.totalText)
                    .font(.system(size: 8, weight: .semibold))
                    .foregroundStyle(.primary.opacity(0.86))
                    .lineLimit(1)
            }
            if entry.state.isStale {
                Text("stale")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct ComplicationBarChart: View {
    let points: [WatchTrendPoint]

    private var maxTokens: Int {
        max(points.map(\.tokens).max() ?? 1, 1)
    }

    var body: some View {
        HStack(alignment: .bottom, spacing: 1.5) {
            ForEach(points) { point in
                RoundedRectangle(cornerRadius: 2, style: .continuous)
                    .fill(barGradient)
                    .frame(maxWidth: .infinity)
                    .frame(height: barHeight(point))
                    .opacity(point.tokens == 0 ? 0.28 : 1)
            }
        }
        .frame(maxHeight: .infinity, alignment: .bottom)
    }

    private var barGradient: LinearGradient {
        LinearGradient(
            colors: [
                Color(red: 10 / 255, green: 132 / 255, blue: 1),
                Color(red: 90 / 255, green: 200 / 255, blue: 250 / 255)
            ],
            startPoint: .top,
            endPoint: .bottom
        )
    }

    private func barHeight(_ point: WatchTrendPoint) -> CGFloat {
        max(point.tokens == 0 ? 2 : 4, CGFloat(point.tokens) / CGFloat(maxTokens) * 28)
    }
}

private extension View {
    @ViewBuilder
    func aiUsageComplicationContainerBackground() -> some View {
        self.containerBackground(.background, for: .widget)
    }
}

struct AIUsageCodexQuotaRingComplication: Widget {
    let kind = "AIUsageCodexQuotaRingComplication"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: FixedQuotaRingProvider(selection: .codex)) { entry in
            QuotaRingComplicationView(entry: entry)
                .aiUsageComplicationContainerBackground()
        }
        .configurationDisplayName("AI Usage Codex")
        .description("查看 Codex 额度双环。")
        .supportedFamilies([.accessoryCircular, .accessoryCorner, .accessoryInline])
    }
}

struct AIUsageClaudeQuotaRingComplication: Widget {
    let kind = "AIUsageClaudeQuotaRingComplication"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: FixedQuotaRingProvider(selection: .claude)) { entry in
            QuotaRingComplicationView(entry: entry)
                .aiUsageComplicationContainerBackground()
        }
        .configurationDisplayName("AI Usage Claude")
        .description("查看 Claude Code 额度双环。")
        .supportedFamilies([.accessoryCircular, .accessoryCorner, .accessoryInline])
    }
}

struct AIUsageTodayChartComplication: Widget {
    let kind = "AIUsageTodayChartComplication"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: TodayChartProvider()) { entry in
            TodayChartComplicationView(entry: entry)
                .aiUsageComplicationContainerBackground()
        }
        .configurationDisplayName("AI Usage Today")
        .description("Show today's usage bar chart.")
        .supportedFamilies([.accessoryRectangular])
    }
}

@main
struct AIUsageWatchWidgetBundle: WidgetBundle {
    var body: some Widget {
        AIUsageCodexQuotaRingComplication()
        AIUsageClaudeQuotaRingComplication()
        AIUsageTodayChartComplication()
    }
}
#endif
