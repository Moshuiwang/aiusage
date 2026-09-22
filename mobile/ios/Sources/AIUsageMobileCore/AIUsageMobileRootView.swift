import SwiftUI
#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

// MARK: - Public Root View

public struct AIUsageMobileRootView: View {
    private let summary: MobileSummary
    private let state: MobileViewState
    private let onPeriodSelected: (String) -> Void
    private let onRefresh: (String) -> Void
    private let onRefreshAsync: (String) async -> Void
    private let onSettingsTapped: () -> Void
    private let refreshingPeriodID: String?
    private let selectedOffset: Int
    private let onOffsetSelected: (Int) -> Void
    @State private var selectedPeriod: PeriodTab

    public init(
        summary: MobileSummary,
        initialTabID: String = "today",
        refreshingPeriodID: String? = nil,
        selectedOffset: Int = 0,
        onOffsetSelected: @escaping (Int) -> Void = { _ in },
        onPeriodSelected: @escaping (String) -> Void = { _ in },
        onRefresh: @escaping (String) -> Void = { _ in },
        onRefreshAsync: @escaping (String) async -> Void = { _ in },
        onSettingsTapped: @escaping () -> Void = {}
    ) {
        self.summary = summary
        self.state = MobileViewModel.build(from: summary)
        self.onPeriodSelected = onPeriodSelected
        self.onRefresh = onRefresh
        self.onRefreshAsync = onRefreshAsync
        self.onSettingsTapped = onSettingsTapped
        self.selectedOffset = selectedOffset
        self.onOffsetSelected = onOffsetSelected
        self.refreshingPeriodID = refreshingPeriodID
        let pid = (initialTabID == "home" || initialTabID.isEmpty) ? summary.period.id : initialTabID
        self._selectedPeriod = State(initialValue: PeriodTab(id: pid.isEmpty ? "today" : pid))
    }

    public var body: some View {
        NativeLiquidGlassPeriodTabs(selection: periodSelection) { period in
            PeriodScrollView(
                summary: summary,
                state: state,
                selectedPeriod: period,
                refreshingPeriodID: refreshingPeriodID,
                selection: MobileHistorySelection(period: period.id, offset: selectedOffset),
                onOffsetSelected: onOffsetSelected,
                onRefreshAsync: { await onRefreshAsync(period.periodID) },
                onSettingsTapped: onSettingsTapped
            )
        }
        .background(Color.appGroupedBackground.ignoresSafeArea())
        .dynamicTypeSize(.xSmall ... .large)
        .onChange(of: state.home.periodID) { _, newID in
            if let tab = PeriodTab(rawValue: newID) {
                selectedPeriod = tab
            }
        }
    }

    private var periodSelection: Binding<PeriodTab> {
        Binding(
            get: { selectedPeriod },
            set: { period in
                guard selectedPeriod != period else { return }
                selectedPeriod = period
                onPeriodSelected(period.id)
            }
        )
    }
}

// MARK: - Period Tab

enum PeriodTab: String, Hashable {
    case today = "today"
    case week  = "week"
    case month = "month"

    static let allCases: [PeriodTab] = [.today, .week, .month]

    init(id: String) { self = PeriodTab(rawValue: id) ?? .today }

    var id: String { rawValue }
    var periodID: String { rawValue }

    var title: String {
        switch self {
        case .today: return "今天"
        case .week:  return "周"
        case .month: return "月"
        }
    }

    var systemImage: String {
        switch self {
        case .today: return "sun.max"
        case .week:  return "gauge.with.dots.needle.33percent"
        case .month: return "calendar.circle"
        }
    }
}

// MARK: - Native Liquid Glass Period Tabs

enum NativeLiquidGlassPeriodTabsCapability {
    static let usesNativeTabView = true
    static let nativeLiquidGlassBehavior = "iOS 26+ system TabView Liquid Glass with tabBarMinimizeBehavior(.onScrollDown)"
    static let fallbackBehavior = "iOS 17-25 uses native TabView without the iOS 26 Liquid Glass minimization API"
}

struct NativeLiquidGlassPeriodTabs<Content: View>: View {
    @Binding var selection: PeriodTab
    let content: (PeriodTab) -> Content

    init(selection: Binding<PeriodTab>, @ViewBuilder content: @escaping (PeriodTab) -> Content) {
        self._selection = selection
        self.content = content
    }

    var body: some View {
        TabView(selection: $selection) {
            ForEach(PeriodTab.allCases, id: \.self) { period in
                content(period)
                    .tag(period)
                    .tabItem {
                        Label(period.title, systemImage: period.systemImage)
                    }
            }
        }
        .nativeLiquidGlassPeriodTabBehavior()
    }
}

private extension View {
    @ViewBuilder
    func nativeLiquidGlassPeriodTabBehavior() -> some View {
        #if os(iOS)
        if #available(iOS 26.0, *) {
            self.tabBarMinimizeBehavior(.onScrollDown)
        } else {
            self
        }
        #else
        self
        #endif
    }
}

// MARK: - Period Scroll View

struct PeriodScrollView: View {
    let summary: MobileSummary
    let state: MobileViewState
    let selectedPeriod: PeriodTab
    let refreshingPeriodID: String?
    let selection: MobileHistorySelection
    let onOffsetSelected: (Int) -> Void
    let onRefreshAsync: () async -> Void
    let onSettingsTapped: () -> Void

    private var isLoadingThisPeriod: Bool {
        refreshingPeriodID == selectedPeriod.periodID
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 10) {
                PeriodHeaderView(
                    lastServerReadText: state.home.lastServerReadText,
                    isRefreshing: isLoadingThisPeriod,
                    onSettingsTapped: onSettingsTapped,
                    onRefresh: { Task { await onRefreshAsync() } }
                )

                PeriodNavigationView(selection: selection, period: summary.period, onOffsetSelected: onOffsetSelected)
                if summary.generatedAt == nil {
                    Text(isLoadingThisPeriod ? "正在读取这个周期…" : "这个周期尚未加载")
                        .font(.callout).foregroundStyle(.secondary).frame(maxWidth: .infinity, minHeight: 210)
                } else {
                    PeriodHeroCard(state: state.home)
                    if summary.period.totalTokens == 0 {
                        Text("这个周期暂无用量").font(.footnote).foregroundStyle(.secondary)
                    }
                }

                if !summary.limits.windows.isEmpty {
                    QuotaRingsCard(limits: summary.limits)
                }

                PeriodSourcesCard(
                    sources: state.sources,
                    rows: SourcesDisplayState.rows(in: state.breakdown),
                    generatedAt: summary.generatedAt,
                    timezone: summary.timezone
                )
                .id(selection.cacheKey)


            }
            .padding(.horizontal, 16)
            .padding(.bottom, 12)
        }
        .refreshable {
            await onRefreshAsync()
        }
        .overlay {
            if isLoadingThisPeriod {
                Color.clear
                    .allowsHitTesting(false)
            }
        }
    }
}

struct PeriodNavigationView: View {
    let selection: MobileHistorySelection
    let period: MobilePeriod
    let onOffsetSelected: (Int) -> Void

    var body: some View {
        HStack(spacing: 8) {
            Button { onOffsetSelected(selection.earlier.offset) } label: {
                Image(systemName: "chevron.left").frame(width: 44, height: 44)
            }
            .disabled(!selection.canGoEarlier)
            .accessibilityLabel("更早一个周期")
            VStack(spacing: 3) {
                Text(MobilePeriodTitle.title(period, selection: selection))
                    .font(.system(size: 15, weight: .semibold))
                if selection.period != "today", let start = period.startDate, let end = period.endDate {
                    Text("\(start) — \(end)").font(.caption2).foregroundStyle(.secondary)
                }
            }.frame(maxWidth: .infinity)
            Button { onOffsetSelected(selection.later.offset) } label: {
                Image(systemName: "chevron.right").frame(width: 44, height: 44)
            }
            .disabled(!selection.canGoLater)
            .accessibilityLabel("更新一个周期")
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .contain)
    }
}

// MARK: - Header

struct PeriodHeaderView: View {
    let lastServerReadText: String
    let isRefreshing: Bool
    let onSettingsTapped: () -> Void
    let onRefresh: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            AIUsageBrandMark(size: 36)
                .onLongPressGesture { onSettingsTapped() }

            VStack(alignment: .leading, spacing: 2) {
                Text("AI Usage")
                    .font(.system(size: 18, weight: .semibold))
                Text(lastServerReadText)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
            }
            Spacer()
            Button(action: onRefresh) {
                Group {
                    if isRefreshing {
                        ProgressView().controlSize(.small)
                    } else {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 15, weight: .semibold))
                    }
                }
                .frame(width: 34, height: 34)
                .background(Color.cardBackground, in: Circle())
            }
            .buttonStyle(.plain)
            .disabled(isRefreshing)
            .accessibilityLabel("刷新数据")
        }
        .padding(.horizontal, 4)
        .padding(.vertical, 10)
    }
}

// MARK: - Hero Card

struct PeriodHeroCard: View {
    let state: MobileHomeState

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(state.totalText)
                .font(.system(size: 44, weight: .bold, design: .rounded))
                .monospacedDigit()
                .kerning(-1.5)
                .lineLimit(1)
                .minimumScaleFactor(0.68)
                .contentTransition(.numericText(value: Double(state.totalTokens)))
                .animation(.snappy(duration: 0.42), value: state.totalTokens)

            Text(state.tokenBreakdownText)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(.secondary)
                .lineLimit(1)

            InteractiveBarChart(points: state.trendPoints)
                .frame(height: 172)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .cardSurface()
    }
}

// MARK: - Interactive Bar Chart with Tooltip

struct InteractiveBarChart: View {
    let points: [MobileTrendPoint]
    @State private var selectedIndex: Int? = nil
    @State private var dismissTask: Task<Void, Never>? = nil

    init(points: [MobileTrendPoint]) {
        self.points = points
        #if DEBUG
        let showsDeterministicTooltip = ProcessInfo.processInfo.environment["AI_USAGE_DETERMINISTIC_TOOLTIP"] == "1"
        #else
        let showsDeterministicTooltip = false
        #endif
        self._selectedIndex = State(initialValue: showsDeterministicTooltip ? points.indices.last : nil)
    }

    private var chartPoints: [MobileTrendPoint] { TrendChartPresentation.points(from: points) }
    private var maxTokens: Int { max(chartPoints.map(\.tokens).max() ?? 1, 1) }
    private var maxLabel: String { TokenFormat.compact(maxTokens) }

    private var axisLabels: [String] {
        let labels = chartPoints.map(\.label).filter { !$0.isEmpty }
        guard labels.count >= 3 else { return labels.isEmpty ? ["00:00", "12:00", "23:59"] : labels }
        return [labels.first!, labels[labels.count / 2], labels.last!]
    }

    private func barHeight(for point: MobileTrendPoint) -> CGFloat {
        max(point.tokens == 0 ? 3 : 5, CGFloat(point.tokens) / CGFloat(maxTokens) * 52)
    }

    private let claudeColor = BrandColor.claudeOrange
    private let codexColor = Color(red: 0.039, green: 0.518, blue: 1)
    private let unknownColor = Color.secondary.opacity(0.45)

    var body: some View {
        VStack(spacing: 6) {
            GeometryReader { proxy in
                ZStack(alignment: .top) {
                    // Reference line
                    HStack {
                        Spacer()
                        Text(maxLabel)
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(.secondary.opacity(0.78))
                    }

                    // Bars
                    HStack(alignment: .bottom, spacing: 3) {
                        ForEach(Array(chartPoints.enumerated()), id: \.element.id) { idx, point in
                            stackedBar(point)
                                .frame(maxWidth: .infinity, alignment: .bottom)
                                .opacity(point.tokens == 0 ? 0.28 : 1)
                                .scaleEffect(y: selectedIndex == idx ? 1.06 : 1, anchor: .bottom)
                                .overlay {
                                    if selectedIndex == idx {
                                        RoundedRectangle(cornerRadius: 3)
                                            .stroke(Color.primary.opacity(0.45), lineWidth: 1)
                                    }
                                }
                        }
                    }
                    .frame(height: 52, alignment: .bottom)
                    .padding(.top, 66)

                    // Tooltip
                    if let idx = selectedIndex, idx < chartPoints.count {
                        let pt = chartPoints[idx]
                        ChartTooltip(lines: TrendChartPresentation.tooltipLines(for: pt))
                            .offset(x: tooltipX(idx: idx, width: proxy.size.width))
                            .offset(y: -2)
                            .zIndex(10)
                            .transition(.opacity.combined(with: .scale(scale: 0.92)))
                    }
                }
                .contentShape(Rectangle())
                .gesture(
                    DragGesture(minimumDistance: 0)
                        .onChanged { val in
                            let n = chartPoints.count
                            guard n > 0 else { return }
                            dismissTask?.cancel()
                            let step = proxy.size.width / CGFloat(n)
                            let idx = min(max(Int(val.location.x / step), 0), n - 1)
                            if selectedIndex != idx {
                                withAnimation(.easeOut(duration: 0.08)) { selectedIndex = idx }
                            }
                        }
                        .onEnded { _ in
                            // Keep tooltip visible; auto-dismiss after 4 s
                            dismissTask?.cancel()
                            dismissTask = Task {
                                try? await Task.sleep(for: .seconds(4))
                                await MainActor.run {
                                    withAnimation(.easeOut(duration: 0.22)) { selectedIndex = nil }
                                }
                            }
                        }
                )
            }
            .frame(height: 122)

            // Axis labels
            HStack {
                ForEach(axisLabels, id: \.self) { label in
                    Text(label)
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(.secondary)
                    if label != axisLabels.last { Spacer(minLength: 0) }
                }
            }

            HStack(spacing: 12) {
                chartLegend("Claude", color: claudeColor)
                chartLegend("Codex", color: codexColor)
                chartLegend("未知", color: unknownColor)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    @ViewBuilder
    private func stackedBar(_ point: MobileTrendPoint) -> some View {
        if point.tokens == 0 {
            RoundedRectangle(cornerRadius: 3)
                .fill(unknownColor)
                .frame(height: 3)
        } else {
            VStack(spacing: 0) {
                if point.unknownTokens > 0 {
                    Rectangle()
                        .fill(unknownColor)
                        .frame(height: segmentHeight(point.unknownTokens))
                }
                if point.claudeTokens > 0 {
                    Rectangle()
                        .fill(claudeColor)
                        .frame(height: segmentHeight(point.claudeTokens))
                }
                if point.codexTokens > 0 {
                    Rectangle()
                        .fill(codexColor)
                        .frame(height: segmentHeight(point.codexTokens))
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 3, style: .continuous))
            .frame(height: barHeight(for: point), alignment: .bottom)
        }
    }

    private func segmentHeight(_ tokens: Int) -> CGFloat {
        CGFloat(tokens) / CGFloat(maxTokens) * 52
    }

    private func chartLegend(_ label: String, color: Color) -> some View {
        HStack(spacing: 4) {
            Circle().fill(color).frame(width: 7, height: 7)
            Text(label).font(.system(size: 9, weight: .medium)).foregroundStyle(.secondary)
        }
    }

    private func tooltipX(idx: Int, width: CGFloat) -> CGFloat {
        let n = chartPoints.count
        guard n > 0 else { return 0 }
        let step = width / CGFloat(n)
        let centerX = CGFloat(idx) * step + step / 2
        let tipW: CGFloat = 196
        let clamped = max(tipW / 2, min(centerX, width - tipW / 2))
        return clamped - width / 2
    }
}

struct ChartTooltip: View {
    let lines: TrendTooltipLines

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(lines.total)
                .font(.system(size: 12, weight: .bold))
                .monospacedDigit()
            Text(lines.label)
                .font(.system(size: 9, weight: .semibold))
                .foregroundStyle(.secondary)
            Text("\(lines.claude) · \(lines.codex)")
                .font(.system(size: 9))
                .foregroundStyle(.secondary)
            if !lines.unknown.hasSuffix(" 0") {
                Text(lines.unknown)
                    .font(.system(size: 9))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
        .frame(width: 196, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 7))
        .overlay(RoundedRectangle(cornerRadius: 7).stroke(Color.primary.opacity(0.08), lineWidth: 0.5))
        .shadow(color: .black.opacity(0.14), radius: 6, y: 3)
    }
}

// MARK: - Quota Rings Card

struct QuotaRingsCard: View {
    let limits: MobileLimits

    private var groups: [LimitWindowGroup] {
        limitGroups(from: limits.windows)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("已用额度")
                .font(.system(size: 11, weight: .semibold))
                .textCase(.uppercase)
                .tracking(0.4)
                .foregroundStyle(.secondary)
                .padding(.horizontal, 4)

            if groups.isEmpty {
                Text("暂无可信额度数据")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 4)
            } else {
                HStack(alignment: .top, spacing: 8) {
                    ForEach(Array(groups.prefix(2)), id: \.id) { group in
                        ProviderQuotaCard(group: group)
                            .frame(maxWidth: .infinity)
                    }
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .cardSurface()
    }
}

struct ProviderQuotaCard: View {
    let group: LimitWindowGroup

    private var fiveHourWindow: MobileLimitWindow? {
        group.windows.first { w in
            let wl = w.window.lowercased()
            return wl.contains("5h") || (w.windowDurationMinutes > 0 && w.windowDurationMinutes <= 360)
        }
    }

    private var weeklyWindow: MobileLimitWindow? {
        group.windows.first { w in
            let wl = w.window.lowercased()
            return wl.contains("week") || wl.contains("7d") || wl == "周" || w.windowDurationMinutes > 360
        }
    }

    private var outerColor: Color { providerOuterColor(group.provider) }
    private var innerColor: Color { providerInnerColor(group.provider) }
    private var fiveHourDisplay: QuotaWindowDisplayState {
        QuotaWindowDisplayState.fiveHour(window: fiveHourWindow)
    }

    var body: some View {
        VStack(spacing: 10) {
            if let account = group.accountLabel {
                Text(AccountLabelText.compactEmail(account))
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                    .frame(maxWidth: .infinity)
            }

            // Ring
            ZStack {
                Circle()
                    .stroke(Color.primary.opacity(0.08), lineWidth: 9)
                    .frame(width: 80, height: 80)
                Circle()
                    .trim(from: 0, to: CGFloat((fiveHourWindow?.usedPercent ?? 0) / 100))
                    .stroke(outerColor, style: StrokeStyle(lineWidth: 9, lineCap: .round))
                    .frame(width: 80, height: 80)
                    .rotationEffect(.degrees(-90))
                    .animation(.easeOut(duration: 0.5), value: fiveHourWindow?.usedPercent)

                Circle()
                    .stroke(Color.primary.opacity(0.08), lineWidth: 7)
                    .frame(width: 52, height: 52)
                Circle()
                    .trim(from: 0, to: CGFloat((weeklyWindow?.usedPercent ?? 0) / 100))
                    .stroke(innerColor, style: StrokeStyle(lineWidth: 7, lineCap: .round))
                    .frame(width: 52, height: 52)
                    .rotationEffect(.degrees(-90))
                    .animation(.easeOut(duration: 0.5), value: weeklyWindow?.usedPercent)

                VStack(spacing: 1) {
                    Text(group.providerLabel)
                        .font(.system(size: 9, weight: .bold))
                    if let plan = group.accountPlanLabel {
                        Text(plan)
                            .font(.system(size: 8, weight: .semibold))
                    }
                }
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.72)
            }

            // Stat rows — compact, all data per row together
            VStack(spacing: 4) {
                QuotaRow(
                    windowLabel: "5h",
                    pct: fiveHourDisplay.percent,
                    resetText: fiveHourDisplay.resetText,
                    color: fiveHourDisplay.isKnown ? outerColor : Color.secondary,
                    isMuted: !fiveHourDisplay.isKnown
                )
                if let w = weeklyWindow {
                    QuotaRow(
                        windowLabel: "7d",
                        pct: Int(w.usedPercent.rounded()),
                        resetText: remainingTimeText(resetAt: w.resetAt),
                        color: innerColor
                    )
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity)
        .background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

}

struct QuotaRow: View {
    let windowLabel: String
    let pct: Int?
    let resetText: String
    let color: Color
    var isMuted: Bool = false

    var body: some View {
        HStack(spacing: 0) {
            // Left-aligned: label + percentage
            Text(windowLabel)
                .font(.system(size: 9, weight: .bold))
                .foregroundStyle(color)
                .frame(width: 16, alignment: .leading)
            Text(pct.map { "\($0)%" } ?? "--")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(color)
                .monospacedDigit()
            Spacer(minLength: 4)
            // Right-aligned: remaining time
            Text(resetText)
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
                .monospacedDigit()
                .lineLimit(1)
        }
        .opacity(isMuted ? 0.62 : 1)
    }
}

private func remainingTimeText(resetAt: String?) -> String {
    guard let resetAt else { return "--" }
    let formatter = ISO8601DateFormatter()
    formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    var date = formatter.date(from: resetAt)
    if date == nil {
        formatter.formatOptions = [.withInternetDateTime]
        date = formatter.date(from: resetAt)
    }
    if date == nil {
        let df = DateFormatter()
        df.locale = Locale(identifier: "en_US_POSIX")
        for fmt in ["yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd HH:mm:ssZ", "yyyy-MM-dd'T'HH:mm:ssZ"] {
            df.dateFormat = fmt
            if let d = df.date(from: resetAt) { date = d; break }
        }
    }
    guard let date else {
        // Fallback: show time portion of string
        if resetAt.count >= 16 {
            let start = resetAt.index(resetAt.startIndex, offsetBy: 11)
            let end = resetAt.index(resetAt.startIndex, offsetBy: 16)
            return String(resetAt[start..<end])
        }
        return resetAt
    }
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

private func providerOuterColor(_ provider: String) -> Color {
    let p = provider.lowercased()
    return (p.contains("claude") || p.contains("anthropic"))
        ? BrandColor.claudeOrange
        : BrandColor.openaiBlue
}

private func providerInnerColor(_ provider: String) -> Color {
    let p = provider.lowercased()
    return (p.contains("claude") || p.contains("anthropic"))
        ? BrandColor.claudePeach
        : BrandColor.openaiCyan
}

// MARK: - Sources Card

struct PeriodSourcesCard: View {
    let sources: [MobileSource]
    let rows: [MobileBreakdownRow]
    let generatedAt: String?
    let timezone: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("来源")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)
            if rows.isEmpty {
                Text("暂无来源数据").font(.footnote).foregroundStyle(.secondary)
            } else {
                VStack(spacing: 0) {
                    ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                        if index > 0 { Divider() }
                        PeriodSourceRow(row: row,
                            source: sources.first { row.sourceIDs?.count == 1 && row.sourceIDs?.first == $0.sourceID },
                            generatedAt: generatedAt, timezone: timezone)
                    }
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .cardSurface()
    }
}

struct PeriodSourceRow: View {
    let row: MobileBreakdownRow
    let source: MobileSource?
    let generatedAt: String?
    let timezone: String?
    @State private var isExpanded = false

    var body: some View {
        DisclosureGroup(isExpanded: $isExpanded) {
            if let agents = row.agents, !agents.isEmpty {
                ForEach(agents) { agent in
                    AgentUsageDisclosure(agent: agent)
                }
            } else {
                Text("Agent / 模型明细缺失")
                    .font(.footnote).foregroundStyle(.secondary).padding(.vertical, 8)
            }
        } label: {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 10) {
                    Circle().fill(source?.status == "ok" ? Color.green : Color.orange).frame(width: 7, height: 7)
                    Text(row.osUser ?? row.label).font(.system(size: 14, weight: .semibold))
                        .lineLimit(1).truncationMode(.middle)
                    Spacer(minLength: 8)
                    Text(TokenFormat.compact(row.tokens)).font(.system(size: 13, weight: .bold)).monospacedDigit()
                        .layoutPriority(1).fixedSize(horizontal: true, vertical: false)
                }
                HStack {
                    if let machine = row.machine ?? source?.machine {
                        Text(machine).lineLimit(1).truncationMode(.middle)
                    }
                    Spacer(minLength: 8)
                    Text(SourceUpdateDateText.format(source?.lastPushedAt ?? source?.lastObservedAt, timezone: timezone))
                }
                .font(.system(size: 11)).foregroundStyle(.secondary).padding(.leading, 17)
            }
        }
        .tint(.secondary)
        .padding(.vertical, 8)
    }
}

struct AgentUsageDisclosure: View {
    let agent: MobileAgentUsage
    @State private var isExpanded = false

    var body: some View {
        DisclosureGroup(isExpanded: $isExpanded) {
            if agent.models.isEmpty {
                Text("模型明细缺失").font(.footnote).foregroundStyle(.secondary)
            } else {
                ForEach(agent.models) { model in
                    HStack {
                        Text(model.displayLabel)
                        Spacer()
                        Text(model.usageText).monospacedDigit()
                    }
                    .font(.footnote).foregroundStyle(.secondary).padding(.vertical, 4)
                }
            }
        } label: {
            HStack {
                Text(agent.label)
                Spacer()
                Text(agent.usageText).monospacedDigit()
            }
            .font(.system(size: 13, weight: .medium))
        }
        .padding(.leading, 17).padding(.vertical, 6)
    }
}

// MARK: - Shared: Brand Icons

enum BrandKind: Equatable {
    case claudeCode
    case codex
    case faviconURL(String)
    case generic
}

struct BrandIcon: View {
    let kind: BrandKind
    let size: CGFloat

    static func kind(for raw: String) -> BrandKind {
        let lc = raw.lowercased()
        if lc.contains("claude") { return .claudeCode }
        if lc.contains("codex") || lc.contains("openai") || lc.contains("gpt") { return .codex }
        if lc.contains("deepseek") { return .faviconURL("deepseek.com") }
        if lc.contains("gemini") || lc.contains("google") { return .faviconURL("gemini.google.com") }
        if lc.contains("mistral") { return .faviconURL("mistral.ai") }
        return .generic
    }

    var body: some View {
        Group {
            switch kind {
            case .claudeCode:
                ClaudeCodeLogo().fill(BrandColor.claudeOrange)
                    .frame(width: size, height: size)
            case .codex:
                CodexLogo()
                    .frame(width: size, height: size)
            case .faviconURL(let domain):
                let url = URL(string: "https://www.google.com/s2/favicons?domain=\(domain)&sz=128")
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image.resizable().scaledToFit()
                            .clipShape(RoundedRectangle(cornerRadius: size * 0.22, style: .continuous))
                    default:
                        Image(systemName: "globe")
                            .font(.system(size: size * 0.72))
                            .foregroundStyle(.secondary)
                    }
                }
                .frame(width: size, height: size)
            case .generic:
                Image(systemName: "terminal")
                    .font(.system(size: size * 0.72, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .frame(width: size, height: size)
            }
        }
        .accessibilityHidden(true)
    }
}

struct ClaudeCodeLogo: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        func x(_ v: CGFloat) -> CGFloat { rect.minX + v / 24 * rect.width }
        func y(_ v: CGFloat) -> CGFloat { rect.minY + v / 24 * rect.height }
        p.move(to: CGPoint(x: x(20.998), y: y(10.949))); p.addLine(to: CGPoint(x: x(24), y: y(10.949)))
        p.addLine(to: CGPoint(x: x(24), y: y(14.051))); p.addLine(to: CGPoint(x: x(21), y: y(14.051)))
        p.addLine(to: CGPoint(x: x(21), y: y(17.079))); p.addLine(to: CGPoint(x: x(19.513), y: y(17.079)))
        p.addLine(to: CGPoint(x: x(19.513), y: y(20))); p.addLine(to: CGPoint(x: x(18), y: y(20)))
        p.addLine(to: CGPoint(x: x(18), y: y(17.079))); p.addLine(to: CGPoint(x: x(16.513), y: y(17.079)))
        p.addLine(to: CGPoint(x: x(16.513), y: y(20))); p.addLine(to: CGPoint(x: x(15), y: y(20)))
        p.addLine(to: CGPoint(x: x(15), y: y(17.079))); p.addLine(to: CGPoint(x: x(9), y: y(17.079)))
        p.addLine(to: CGPoint(x: x(9), y: y(20))); p.addLine(to: CGPoint(x: x(7.488), y: y(20)))
        p.addLine(to: CGPoint(x: x(7.488), y: y(17.079))); p.addLine(to: CGPoint(x: x(6), y: y(17.079)))
        p.addLine(to: CGPoint(x: x(6), y: y(20))); p.addLine(to: CGPoint(x: x(4.487), y: y(20)))
        p.addLine(to: CGPoint(x: x(4.487), y: y(17.079))); p.addLine(to: CGPoint(x: x(3), y: y(17.079)))
        p.addLine(to: CGPoint(x: x(3), y: y(14.05))); p.addLine(to: CGPoint(x: x(0), y: y(14.05)))
        p.addLine(to: CGPoint(x: x(0), y: y(10.95))); p.addLine(to: CGPoint(x: x(3), y: y(10.95)))
        p.addLine(to: CGPoint(x: x(3), y: y(5))); p.addLine(to: CGPoint(x: x(20.998), y: y(5)))
        p.closeSubpath()
        p.move(to: CGPoint(x: x(6), y: y(10.949))); p.addLine(to: CGPoint(x: x(7.488), y: y(10.949)))
        p.addLine(to: CGPoint(x: x(7.488), y: y(8.102))); p.addLine(to: CGPoint(x: x(6), y: y(8.102)))
        p.closeSubpath()
        p.move(to: CGPoint(x: x(16.51), y: y(10.949))); p.addLine(to: CGPoint(x: x(18), y: y(10.949)))
        p.addLine(to: CGPoint(x: x(18), y: y(8.102))); p.addLine(to: CGPoint(x: x(16.51), y: y(8.102)))
        p.closeSubpath()
        return p
    }
}

struct CodexLogo: Shape {
    func path(in rect: CGRect) -> Path {
        var p = Path()
        func x(_ v: CGFloat) -> CGFloat { rect.minX + v / 24 * rect.width }
        func y(_ v: CGFloat) -> CGFloat { rect.minY + v / 24 * rect.height }
        p.move(to: CGPoint(x: x(9.064), y: y(3.344)))
        p.addCurve(to: CGPoint(x: x(11.349), y: y(3.032)), control1: CGPoint(x: x(9.754), y: y(3.02)), control2: CGPoint(x: x(10.516), y: y(2.916)))
        p.addCurve(to: CGPoint(x: x(14.022), y: y(4.307)), control1: CGPoint(x: x(12.349), y: y(3.147)), control2: CGPoint(x: x(13.24), y: y(3.572)))
        p.addCurve(to: CGPoint(x: x(14.102), y: y(4.328)), control1: CGPoint(x: x(14.032), y: y(4.317)), control2: CGPoint(x: x(14.076), y: y(4.333)))
        p.addCurve(to: CGPoint(x: x(17.148), y: y(4.603)), control1: CGPoint(x: x(15.06), y: y(3.995)), control2: CGPoint(x: x(16.075), y: y(4.087)))
        p.addLine(to: CGPoint(x: x(17.311), y: y(4.682)))
        p.addCurve(to: CGPoint(x: x(19.499), y: y(7.081)), control1: CGPoint(x: x(18.321), y: y(5.177)), control2: CGPoint(x: x(19.05), y: y(5.977)))
        p.addCurve(to: CGPoint(x: x(19.68), y: y(9.899)), control1: CGPoint(x: x(19.84), y: y(7.914)), control2: CGPoint(x: x(19.9), y: y(8.854)))
        p.addCurve(to: CGPoint(x: x(19.71), y: y(10.014)), control1: CGPoint(x: x(19.672), y: y(9.94)), control2: CGPoint(x: x(19.683), y: y(9.984)))
        p.addCurve(to: CGPoint(x: x(20.893), y: y(12.184)), control1: CGPoint(x: x(20.304), y: y(10.621)), control2: CGPoint(x: x(20.698), y: y(11.344)))
        p.addCurve(to: CGPoint(x: x(20.006), y: y(16.038)), control1: CGPoint(x: x(21.182), y: y(13.609)), control2: CGPoint(x: x(20.886), y: y(14.894)))
        p.addLine(to: CGPoint(x: x(19.87), y: y(16.204)))
        p.addCurve(to: CGPoint(x: x(17.669), y: y(17.592)), control1: CGPoint(x: x(19.296), y: y(16.865)), control2: CGPoint(x: x(18.562), y: y(17.328)))
        p.addCurve(to: CGPoint(x: x(17.588), y: y(17.668)), control1: CGPoint(x: x(17.629), y: y(17.604)), control2: CGPoint(x: x(17.6), y: y(17.631)))
        p.addCurve(to: CGPoint(x: x(16.848), y: y(19.158)), control1: CGPoint(x: x(17.397), y: y(18.219)), control2: CGPoint(x: x(17.205), y: y(18.687)))
        p.addCurve(to: CGPoint(x: x(13.137), y: y(20.996)), control1: CGPoint(x: x(15.948), y: y(20.345)), control2: CGPoint(x: x(14.626), y: y(21.004)))
        p.addCurve(to: CGPoint(x: x(9.98), y: y(19.694)), control1: CGPoint(x: x(11.95), y: y(20.99)), control2: CGPoint(x: x(10.898), y: y(20.556)))
        p.addCurve(to: CGPoint(x: x(9.875), y: y(19.67)), control1: CGPoint(x: x(9.954), y: y(19.67)), control2: CGPoint(x: x(9.914), y: y(19.661)))
        p.addCurve(to: CGPoint(x: x(8.671), y: y(19.808)), control1: CGPoint(x: x(9.487), y: y(19.795)), control2: CGPoint(x: x(9.095), y: y(19.813)))
        p.addCurve(to: CGPoint(x: x(6.726), y: y(19.342)), control1: CGPoint(x: x(7.975), y: y(19.8)), control2: CGPoint(x: x(7.327), y: y(19.645)))
        p.addCurve(to: CGPoint(x: x(4.702), y: y(17.39)), control1: CGPoint(x: x(5.983), y: y(18.965)), control2: CGPoint(x: x(5.307), y: y(18.314)))
        p.addCurve(to: CGPoint(x: x(4.318), y: y(14.131)), control1: CGPoint(x: x(4.342), y: y(16.553)), control2: CGPoint(x: x(4.214), y: y(15.467)))
        p.addCurve(to: CGPoint(x: x(4.297), y: y(14.027)), control1: CGPoint(x: x(4.327), y: y(14.09)), control2: CGPoint(x: x(4.318), y: y(14.049)))
        p.addCurve(to: CGPoint(x: x(3.263), y: y(12.376)), control1: CGPoint(x: x(3.842), y: y(13.579)), control2: CGPoint(x: x(3.497), y: y(13.029)))
        p.addCurve(to: CGPoint(x: x(3.153), y: y(9.584)), control1: CGPoint(x: x(3.126), y: y(11.994)), control2: CGPoint(x: x(3.063), y: y(10.647)))
        p.addCurve(to: CGPoint(x: x(5.086), y: y(6.966)), control1: CGPoint(x: x(3.49), y: y(8.472)), control2: CGPoint(x: x(4.135), y: y(7.599)))
        p.addCurve(to: CGPoint(x: x(6.333), y: y(6.409)), control1: CGPoint(x: x(5.298), y: y(6.825)), control2: CGPoint(x: x(5.963), y: y(6.516)))
        p.addCurve(to: CGPoint(x: x(6.398), y: y(6.343)), control1: CGPoint(x: x(6.363), y: y(6.4)), control2: CGPoint(x: x(6.389), y: y(6.374)))
        p.addCurve(to: CGPoint(x: x(7.227), y: y(4.728)), control1: CGPoint(x: x(6.575), y: y(5.738)), control2: CGPoint(x: x(6.851), y: y(5.199)))
        p.addCurve(to: CGPoint(x: x(9.064), y: y(3.344)), control1: CGPoint(x: x(7.704), y: y(4.13)), control2: CGPoint(x: x(8.316), y: y(3.668)))
        p.closeSubpath()
        p.move(to: CGPoint(x: x(12.546), y: y(13.909)))
        p.addCurve(to: CGPoint(x: x(12.546), y: y(15.181)), control1: CGPoint(x: x(12.193), y: y(13.909)), control2: CGPoint(x: x(11.91), y: y(14.193)))
        p.addLine(to: CGPoint(x: x(16.182), y: y(15.181)))
        p.addCurve(to: CGPoint(x: x(16.182), y: y(13.909)), control1: CGPoint(x: x(17.03), y: y(15.181)), control2: CGPoint(x: x(17.03), y: y(13.909)))
        p.addLine(to: CGPoint(x: x(12.546), y: y(13.909))); p.closeSubpath()
        p.move(to: CGPoint(x: x(8.462), y: y(9.23)))
        p.addCurve(to: CGPoint(x: x(7.356), y: y(9.861)), control1: CGPoint(x: x(8.112), y: y(8.612)), control2: CGPoint(x: x(7.007), y: y(9.241)))
        p.addLine(to: CGPoint(x: x(8.628), y: y(12.085))); p.addLine(to: CGPoint(x: x(7.362), y: y(14.221)))
        p.addCurve(to: CGPoint(x: x(8.457), y: y(14.87)), control1: CGPoint(x: x(7.006), y: y(14.822)), control2: CGPoint(x: x(8.105), y: y(15.474)))
        p.addLine(to: CGPoint(x: x(9.911), y: y(12.415)))
        p.addCurve(to: CGPoint(x: x(9.916), y: y(11.775)), control1: CGPoint(x: x(10.025), y: y(12.222)), control2: CGPoint(x: x(10.027), y: y(11.968)))
        p.addLine(to: CGPoint(x: x(8.462), y: y(9.23))); p.closeSubpath()
        return p
    }
}

// MARK: - Shared: Colors & Surface

extension Color {
    static var appGroupedBackground: Color {
        #if canImport(UIKit)
        Color(UIColor.systemGroupedBackground)
        #elseif canImport(AppKit)
        Color(NSColor.windowBackgroundColor)
        #else
        Color.gray.opacity(0.12)
        #endif
    }

    static var cardBackground: Color {
        #if canImport(UIKit)
        Color(UIColor.secondarySystemGroupedBackground)
        #elseif canImport(AppKit)
        Color(NSColor.controlBackgroundColor)
        #else
        Color.white
        #endif
    }
}

private extension View {
    func cardSurface() -> some View {
        self.background(Color.cardBackground, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }
}

// MARK: - Shared: Helpers

func shortTime(_ value: String) -> String {
    guard value.count >= 16 else { return value }
    let start = value.index(value.startIndex, offsetBy: 11)
    let end   = value.index(value.startIndex, offsetBy: 16)
    return String(value[start..<end])
}

func statusLabel(_ status: String) -> String {
    switch status {
    case "ok":       return "正常"
    case "stale":    return "过期"
    case "observed": return "可信"
    case "missing":  return "缺失"
    default:         return status
    }
}

// MARK: - Settings Sheet (used in AIUsageMobileApp.swift)

public struct MobileServerSettingsView: View {
    let tokenStore: MobileTokenStore
    let period: String
    let onSaved: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var baseURLString: String
    @State private var token: String
    @State private var status: SettingsStatus?
    @State private var isTesting = false

    public init(tokenStore: MobileTokenStore, period: String, onSaved: @escaping () -> Void) {
        self.tokenStore = tokenStore
        self.period = period
        self.onSaved = onSaved
        let form = MobileSummaryRuntimeConfig.settingsForm(tokenStore: tokenStore)
        self._baseURLString = State(initialValue: form.baseURLString)
        self._token = State(initialValue: form.token)
    }

    public var body: some View {
        NavigationStack {
            Form {
                Section("服务") {
                    TextField("Server URL", text: $baseURLString)
                        .mobileURLTextInput()
                    SecureField("Token", text: $token)
                        .mobilePlainTextInput()
                }
                Section {
                    Button { save() } label: { Label("保存", systemImage: "tray.and.arrow.down") }
                    Button { Task { await testConnection() } } label: {
                        isTesting
                            ? Label("测试中", systemImage: "arrow.triangle.2.circlepath")
                            : Label("测试连接", systemImage: "network")
                    }
                    .disabled(isTesting)
                }
                if let status {
                    Section {
                        Label(status.message, systemImage: status.systemImage).foregroundStyle(status.color)
                    }
                }
            }
            .navigationTitle("服务设置")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() } }
            }
        }
    }

    private func save() {
        do {
            _ = try saveCurrentSettings()
            status = .success("已保存，正在刷新数据")
            onSaved()
        } catch MobileRuntimeConfigurationError.invalidBaseURL {
            status = .failure("服务地址格式不正确")
        } catch MobileRuntimeConfigurationError.missingToken {
            status = .failure("请填写 token")
        } catch MobileRuntimeConfigurationError.nonProductionServer {
            status = .failure("当前服务地址不受信任。请使用 HTTPS 域名。")
        } catch {
            status = .failure("保存失败，请重试")
        }
    }

    private func testConnection() async {
        isTesting = true
        defer { isTesting = false }
        do {
            let config = try saveCurrentSettings()
            _ = try await MobileSummaryAPIClient(config: config).load()
            status = .success("连接成功")
            onSaved()
        } catch MobileRuntimeConfigurationError.invalidBaseURL {
            status = .failure("服务地址格式不正确")
        } catch MobileRuntimeConfigurationError.missingToken {
            status = .failure("请填写 token")
        } catch MobileRuntimeConfigurationError.nonProductionServer {
            status = .failure("当前服务地址不受信任。请使用 HTTPS 域名。")
        } catch {
            status = .failure("连接失败，请检查服务地址或 token")
        }
    }

    private func saveCurrentSettings() throws -> MobileSummaryAPIConfig {
        try MobileSummaryRuntimeConfig.saveSettings(
            baseURLString: baseURLString,
            token: token,
            period: period.isEmpty ? MobileSummaryRuntimeConfig.initialPeriod() : period,
            tokenStore: tokenStore
        )
    }
}

private extension View {
    @ViewBuilder
    func mobileURLTextInput() -> some View {
        #if canImport(UIKit)
        self
            .keyboardType(.URL)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
        #else
        self
            .autocorrectionDisabled()
        #endif
    }

    @ViewBuilder
    func mobilePlainTextInput() -> some View {
        #if canImport(UIKit)
        self
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
        #else
        self
            .autocorrectionDisabled()
        #endif
    }
}

private struct SettingsStatus: Equatable {
    let message: String
    let isSuccess: Bool
    static func success(_ m: String) -> Self { .init(message: m, isSuccess: true) }
    static func failure(_ m: String) -> Self { .init(message: m, isSuccess: false) }
    var systemImage: String { isSuccess ? "checkmark.circle.fill" : "exclamationmark.triangle.fill" }
    var color: Color { isSuccess ? .green : .orange }
}
