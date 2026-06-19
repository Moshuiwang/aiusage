import SwiftUI
#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

public struct AIUsageMobileRootView: View {
    private let state: MobileViewState
    private let onPeriodSelected: (String) -> Void
    private let onRefresh: (String) -> Void
    private let refreshingPeriodID: String?
    @State private var selectedTab: AppTab
    @State private var selectedPeriodID: String

    public init(
        summary: MobileSummary,
        initialTabID: String = "home",
        refreshingPeriodID: String? = nil,
        onPeriodSelected: @escaping (String) -> Void = { _ in },
        onRefresh: @escaping (String) -> Void = { _ in }
    ) {
        self.state = MobileViewModel.build(from: summary)
        self.onPeriodSelected = onPeriodSelected
        self.onRefresh = onRefresh
        self.refreshingPeriodID = refreshingPeriodID
        self._selectedTab = State(initialValue: AppTab(id: initialTabID))
        self._selectedPeriodID = State(initialValue: summary.period.id)
    }

    public var body: some View {
        ZStack(alignment: .bottom) {
            Group {
                switch selectedTab {
                case .home:
                    HomeView(
                        state: state.home,
                        selectedTab: $selectedTab,
                        selectedPeriodID: $selectedPeriodID,
                        refreshingPeriodID: refreshingPeriodID,
                        onPeriodSelected: onPeriodSelected,
                        onRefresh: onRefresh
                    )
                case .limits:
                    LimitsView(limits: state.limits)
                case .breakdown:
                    BreakdownView(
                        breakdown: state.breakdown,
                        selectedPeriodID: $selectedPeriodID,
                        refreshingPeriodID: refreshingPeriodID,
                        onPeriodSelected: onPeriodSelected
                    )
                case .sources:
                    SourcesView(sources: state.sources)
                }
            }
            .transition(.opacity)
            .animation(.snappy(duration: 0.22), value: selectedTab)

            CustomGlassTabBar(selection: $selectedTab)
                .padding(.horizontal, 14)
                .padding(.bottom, 10)
        }
        .dynamicTypeSize(.xSmall ... .large)
        .onChange(of: state.home.periodID) { _, newPeriodID in
            selectedPeriodID = newPeriodID
        }
    }
}

enum AppTab: Hashable {
    case home
    case limits
    case breakdown
    case sources

    static let allCases: [AppTab] = [.home, .limits, .breakdown, .sources]

    init(id: String) {
        switch id {
        case "limits":
            self = .limits
        case "breakdown":
            self = .breakdown
        case "sources":
            self = .sources
        default:
            self = .home
        }
    }

    var title: String {
        switch self {
        case .home:
            return "首页"
        case .limits:
            return "额度"
        case .breakdown:
            return "明细"
        case .sources:
            return "来源"
        }
    }

    var systemImage: String {
        switch self {
        case .home:
            return "house"
        case .limits:
            return "gauge.with.dots.needle.33percent"
        case .breakdown:
            return "chart.bar.xaxis"
        case .sources:
            return "antenna.radiowaves.left.and.right"
        }
    }
}

struct HomeView: View {
    let state: MobileHomeState
    @Binding var selectedTab: AppTab
    @Binding var selectedPeriodID: String
    let refreshingPeriodID: String?
    let onPeriodSelected: (String) -> Void
    let onRefresh: (String) -> Void

    var body: some View {
        AppScrollView(bottomPadding: 128) {
            CrossPlatformHomeHeader(
                lastServerReadText: state.lastServerReadText,
                isRefreshing: refreshingPeriodID == selectedPeriodID,
                onRefresh: {
                    onRefresh(selectedPeriodID)
                }
            )
            PeriodSelector(
                selectedPeriodID: $selectedPeriodID,
                refreshingPeriodID: refreshingPeriodID,
                onPeriodSelected: onPeriodSelected
            )
            CrossPlatformHeroPanel(state: state) {
                selectedTab = .breakdown
            }
            CrossPlatformQuotaSection(groups: state.refreshGroups) {
                selectedTab = .limits
            }
            CrossPlatformSourcesSection(
                rows: state.topSources,
                healthText: state.healthText
            ) {
                selectedTab = .sources
            }
        }
    }

    private var topSourceMax: Int {
        max(state.topSources.map(\.tokens).max() ?? 1, 1)
    }
}

struct CrossPlatformHomeHeader: View {
    let lastServerReadText: String
    let isRefreshing: Bool
    let onRefresh: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            AIUsageBrandMark(size: 30)
            VStack(alignment: .leading, spacing: 2) {
                Text("AI Usage")
                    .font(.system(size: 18, weight: .semibold))
                    .kerning(0)
                Text(lastServerReadText)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
            }
            Spacer()
            RefreshActionButton(isRefreshing: isRefreshing, action: onRefresh)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .glassSurface(cornerRadius: 10)
    }
}

struct CrossPlatformHeroPanel: View {
    let state: MobileHomeState
    let onDetails: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .lastTextBaseline, spacing: 8) {
                Text(state.totalText)
                    .font(.system(size: 42, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.68)
                    .contentTransition(.numericText(value: Double(state.totalTokens)))
                    .animation(.snappy(duration: 0.42), value: state.totalTokens)
                Text(state.healthText)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(healthColor)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(healthColor.opacity(0.12), in: RoundedRectangle(cornerRadius: 5, style: .continuous))
                Spacer(minLength: 0)
            }

            Text(state.tokenBreakdownText)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.72)

            CompactHandoffBarChart(points: state.trendPoints)
                .frame(height: 76)

            HStack {
                Text(state.rangeText)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.76)
                Spacer()
                UnifiedDetailLink(action: onDetails)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassSurface(cornerRadius: 10)
    }

    private var healthColor: Color {
        state.healthText.lowercased().contains("issue") || state.healthText.contains("异常") ? .orange : .green
    }
}

struct CompactHandoffBarChart: View {
    let points: [MobileTrendPoint]

    var body: some View {
        VStack(spacing: 6) {
            ZStack(alignment: .topTrailing) {
                Rectangle()
                    .fill(Color.secondary.opacity(0.18))
                    .frame(height: 1)
                    .offset(y: 8)
                Text(maxLabel)
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(.secondary.opacity(0.78))
                HStack(alignment: .bottom, spacing: 4) {
                    ForEach(chartPoints) { point in
                        RoundedRectangle(cornerRadius: 3, style: .continuous)
                            .fill(
                                LinearGradient(
                                    colors: [Color(red: 10 / 255, green: 132 / 255, blue: 1), Color(red: 90 / 255, green: 200 / 255, blue: 250 / 255)],
                                    startPoint: .top,
                                    endPoint: .bottom
                                )
                            )
                            .frame(height: barHeight(for: point))
                            .frame(maxWidth: .infinity, alignment: .bottom)
                            .opacity(point.tokens == 0 ? 0.28 : 1)
                    }
                }
                .frame(height: 52, alignment: .bottom)
                .padding(.top, 10)
            }
            HStack {
                ForEach(axisLabels, id: \.self) { label in
                    Text(label)
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(.secondary)
                    if label != axisLabels.last {
                        Spacer(minLength: 0)
                    }
                }
            }
        }
    }

    private var chartPoints: [MobileTrendPoint] {
        Array(points.suffix(18))
    }

    private var maxTokens: Int {
        max(chartPoints.map(\.tokens).max() ?? 1, 1)
    }

    private var maxLabel: String {
        TokenFormat.compact(maxTokens)
    }

    private var axisLabels: [String] {
        let labels = chartPoints.map(\.label).filter { !$0.isEmpty }
        guard !labels.isEmpty else {
            return ["00:00", "12:00", "23:59"]
        }
        if labels.count >= 3 {
            return [labels.first ?? "", labels[labels.count / 2], labels.last ?? ""]
        }
        return labels
    }

    private func barHeight(for point: MobileTrendPoint) -> CGFloat {
        max(point.tokens == 0 ? 4 : 6, CGFloat(point.tokens) / CGFloat(maxTokens) * 52)
    }
}

struct CrossPlatformQuotaSection: View {
    let groups: [LimitWindowGroup]
    let onDetails: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "额度") {
                UnifiedDetailLink(action: onDetails)
            }
            if groups.isEmpty {
                Text("暂无可信额度数据")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else {
                VStack(spacing: 10) {
                    ForEach(groups) { group in
                        CrossPlatformQuotaRow(group: group)
                    }
                }
            }
        }
        .padding(12)
        .glassSurface(cornerRadius: 10)
    }
}

struct CrossPlatformQuotaRow: View {
    let group: LimitWindowGroup

    var body: some View {
        HStack(spacing: 12) {
            BrandIcon(kind: BrandIcon.kind(for: group.provider), size: 20)
                .frame(width: 32, height: 32)
                .glassSurface(cornerRadius: 8)
            VStack(alignment: .leading, spacing: 2) {
                Text(group.providerLabel)
                    .font(.system(size: 14, weight: .semibold))
                    .lineLimit(1)
                Text(group.sourceID)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 4) {
                resetChip("5h", group.fiveHourResetText, color: Color(red: 10 / 255, green: 132 / 255, blue: 1))
                resetChip("7d", group.weeklyResetText, color: Color(red: 218 / 255, green: 119 / 255, blue: 86 / 255))
            }
        }
        .padding(10)
        .background(Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private func resetChip(_ label: String, _ value: String, color: Color) -> some View {
        HStack(spacing: 5) {
            Text(label)
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(color)
            Text(shortReset(value))
                .font(.system(size: 11, weight: .semibold).monospacedDigit())
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
    }

    private func shortReset(_ value: String) -> String {
        guard value.count >= 16 else {
            return value
        }
        let start = value.index(value.startIndex, offsetBy: 11)
        let end = value.index(value.startIndex, offsetBy: 16)
        return String(value[start..<end])
    }
}

struct CrossPlatformSourcesSection: View {
    let rows: [MobileBreakdownRow]
    let healthText: String
    let onDetails: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: "来源") {
                UnifiedDetailLink(action: onDetails)
            }
            if rows.isEmpty {
                Text("暂无来源数据")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else {
                VStack(spacing: 10) {
                    ForEach(rows) { row in
                        CrossPlatformSourceRow(row: row, maxValue: maxValue)
                    }
                }
            }
            HStack(spacing: 7) {
                Circle()
                    .fill(healthText.lowercased().contains("issue") ? Color.orange : Color.green)
                    .frame(width: 7, height: 7)
                Text(healthText)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.secondary)
                Spacer()
            }
        }
        .padding(12)
        .glassSurface(cornerRadius: 10)
    }

    private var maxValue: Int {
        max(rows.map(\.tokens).max() ?? 1, 1)
    }
}

struct CrossPlatformSourceRow: View {
    let row: MobileBreakdownRow
    let maxValue: Int

    var body: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(Color.green)
                .frame(width: 7, height: 7)
            VStack(alignment: .leading, spacing: 5) {
                HStack {
                    Text(row.label)
                        .font(.system(size: 13, weight: .semibold))
                        .lineLimit(1)
                    Spacer()
                    Text(TokenFormat.compact(row.tokens))
                        .font(.system(size: 12, weight: .bold).monospacedDigit())
                }
                GeometryReader { proxy in
                    RoundedRectangle(cornerRadius: 3, style: .continuous)
                        .fill(Color.secondary.opacity(0.14))
                        .overlay(alignment: .leading) {
                            RoundedRectangle(cornerRadius: 3, style: .continuous)
                                .fill(
                                    LinearGradient(
                                        colors: [Color(red: 10 / 255, green: 132 / 255, blue: 1), Color(red: 90 / 255, green: 200 / 255, blue: 250 / 255)],
                                        startPoint: .leading,
                                        endPoint: .trailing
                                    )
                                )
                                .frame(width: max(8, proxy.size.width * CGFloat(row.tokens) / CGFloat(max(maxValue, 1))))
                        }
                }
                .frame(height: 6)
            }
        }
    }
}

struct SourcesView: View {
    let sources: [MobileSource]

    var body: some View {
        AppScrollView(topPadding: 14, bottomPadding: 128) {
            SummaryStrip(
                eyebrow: "采集",
                title: "采集来源",
                subtitle: "按机器与系统账户查看上报状态",
                value: "\(healthyCount)/\(sources.count)",
                label: "正常"
            )

            MaterialCard {
                SectionHeader(title: "采集列表") {
                    Text("\(sources.count) 个来源")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                VStack(spacing: 12) {
                    ForEach(sources) { source in
                        SourceCard(source: source)
                    }
                }
            }
        }
    }

    private var healthyCount: Int {
        sources.filter { $0.status == "ok" }.count
    }
}

struct BreakdownView: View {
    let breakdown: MobileBreakdown
    @Binding var selectedPeriodID: String
    let refreshingPeriodID: String?
    let onPeriodSelected: (String) -> Void
    @State private var dimension: BreakdownDimension = .date
    @State private var selectedRow: MobileBreakdownRow?

    var body: some View {
        AppScrollView(topPadding: 14, bottomPadding: 128) {
            if let selectedRow {
                BreakdownDrilldownView(
                    row: selectedRow,
                    dimension: dimension,
                    sections: BreakdownDrilldown.sections(
                        for: selectedRow,
                        dimension: dimension,
                        breakdown: breakdown
                    )
                ) {
                    self.selectedRow = nil
                }
            } else {
                SummaryStrip(
                    eyebrow: "明细",
                    title: "用量明细",
                    subtitle: "按不同维度拆解当前周期",
                    value: "5",
                    label: "维度"
                )

                PeriodSelector(
                    selectedPeriodID: $selectedPeriodID,
                    refreshingPeriodID: refreshingPeriodID,
                    onPeriodSelected: onPeriodSelected
                )
                BreakdownSegmentedControl(selection: $dimension)

                MaterialCard {
                    SectionHeader(title: dimension.title) {
                        Text("Tokens")
                            .font(.caption.monospaced())
                            .foregroundStyle(.secondary)
                    }
                    VStack(spacing: 12) {
                        ForEach(rows) { row in
                            Button {
                                selectedRow = row
                            } label: {
                                BarRow(label: row.label, value: row.tokens, maxValue: maxValue)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
        }
        .onChange(of: dimension) { _, _ in
            selectedRow = nil
        }
        .onChange(of: selectedPeriodID) { _, _ in
            selectedRow = nil
        }
    }

    private var rows: [MobileBreakdownRow] {
        switch dimension {
        case .machine:
            return breakdown.byMachine
        case .account:
            return breakdown.byOSUser
        case .agent:
            return breakdown.byAgent
        case .model:
            return breakdown.byModel
        case .date:
            return breakdown.byDate
        }
    }

    private var maxValue: Int {
        max(rows.map(\.tokens).max() ?? 1, 1)
    }
}

struct LimitsView: View {
    let limits: MobileLimits
    @State private var reminderEnabled = true

    var body: some View {
        AppScrollView(topPadding: 14, bottomPadding: 128) {
            QuotaPageHeader(
                observedCount: limits.observedCount,
                totalCount: limits.totalCount
            )

            LimitReminderRow(isOn: $reminderEnabled)

            VStack(spacing: 12) {
                ForEach(limitGroups(from: limits.windows)) { group in
                    LimitAccountGroupCard(group: group)
                }
            }
        }
    }
}

struct QuotaPageHeader: View {
    let observedCount: Int
    let totalCount: Int

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Quota")
                    .font(.caption.monospaced())
                    .textCase(.uppercase)
                    .foregroundStyle(.secondary)
                Text("额度")
                    .font(.system(size: 30, weight: .bold, design: .rounded))
                Text("可用百分比越高，剩余额度越多")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            Gauge(value: Double(observedCount), in: 0...Double(max(totalCount, 1))) {
                EmptyView()
            } currentValueLabel: {
                Text("\(observedCount)/\(totalCount)")
                    .font(.caption.monospacedDigit().weight(.semibold))
            }
            .gaugeStyle(.accessoryCircularCapacity)
            .tint(.blue)
            .frame(width: 58, height: 58)
        }
        .padding(14)
        .glassSurface()
    }
}

struct RefreshSummaryCard: View {
    let group: LimitWindowGroup

    var body: some View {
        HStack(spacing: 12) {
            BrandIcon(kind: BrandIcon.kind(for: group.provider), size: 20)
                .frame(width: 32, height: 32)
                .glassSurface(cornerRadius: 8)
            VStack(alignment: .leading, spacing: 3) {
                Text(group.providerLabel)
                    .font(.subheadline.weight(.semibold))
                Text(group.sourceID)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 5) {
                Text("周 \(group.weeklyResetText)")
                    .font(.caption.monospacedDigit().weight(.semibold))
                Text("5h \(group.fiveHourResetText)")
                    .font(.caption.monospacedDigit().weight(.semibold))
            }
            .foregroundStyle(.secondary)
        }
        .padding(12)
        .glassSurface()
    }
}

struct LimitAccountGroupCard: View {
    let group: LimitWindowGroup

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                BrandIcon(kind: BrandIcon.kind(for: group.provider), size: 24)
                    .frame(width: 34, height: 34)
                    .glassSurface(cornerRadius: 8)
                VStack(alignment: .leading, spacing: 3) {
                    Text(group.providerLabel)
                        .font(.headline.weight(.semibold))
                    Text(group.sourceID)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer()
                Text(group.statText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            ForEach(group.windows) { window in
                LimitWindowCard(window: window)
            }
        }
        .padding(12)
        .glassSurface()
    }
}

struct RefreshActionButton: View {
    let isRefreshing: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Group {
                if isRefreshing {
                    ProgressView()
                        .controlSize(.small)
                } else {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 16, weight: .semibold))
                }
            }
            .frame(width: 36, height: 36)
            .glassSurface()
        }
        .buttonStyle(.plain)
        .disabled(isRefreshing)
        .accessibilityLabel("刷新数据")
    }
}

struct PeriodSelector: View {
    @Binding var selectedPeriodID: String
    let refreshingPeriodID: String?
    let onPeriodSelected: (String) -> Void

    private let periods: [(id: String, title: String)] = [
        ("today", "今天"),
        ("week", "周"),
        ("month", "月"),
        ("all", "全部")
    ]

    var body: some View {
        HStack(spacing: 4) {
            ForEach(periods, id: \.id) { period in
                let isActive = selectedPeriodID == period.id
                let isRefreshing = refreshingPeriodID == period.id
                Button {
                    guard selectedPeriodID != period.id else {
                        return
                    }
                    selectedPeriodID = period.id
                    onPeriodSelected(period.id)
                } label: {
                    HStack(spacing: 5) {
                        Text(period.title)
                        if isRefreshing {
                            ProgressView()
                                .controlSize(.small)
                        }
                    }
                        .font(.system(size: 14, weight: isActive ? .semibold : .regular))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 7)
                        .foregroundStyle(isActive ? Color.primary : Color.secondary)
                        .background {
                            if isActive {
                                RoundedRectangle(cornerRadius: 8, style: .continuous)
                                    .fill(.background)
                                    .shadow(color: .black.opacity(0.08), radius: 8, y: 2)
                            }
                        }
                }
                .buttonStyle(.plain)
            }
        }
        .padding(4)
        .glassSurface()
    }
}

struct LimitReminderRow: View {
    @Binding var isOn: Bool

    var body: some View {
        Toggle(isOn: $isOn) {
            VStack(alignment: .leading, spacing: 3) {
                Text("重置提醒")
                    .font(.subheadline.weight(.semibold))
                Text(isOn ? "已开启；窗口 reset 时通知" : "窗口 reset 时通知")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .toggleStyle(.switch)
        .padding(.vertical, 8)
    }
}

struct UnifiedDetailLink: View {
    let action: () -> Void

    var body: some View {
        Button("查看明细", action: action)
            .font(.footnote.weight(.semibold))
            .buttonStyle(.plain)
            .foregroundStyle(.blue)
    }
}

struct HealthCompactRow: View {
    let text: String
    let action: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.green)
            Text(text)
                .font(.system(size: 15, weight: .semibold))
            Spacer()
            UnifiedDetailLink(action: action)
        }
        .padding(12)
        .glassSurface()
    }
}

struct SummaryStrip: View {
    let eyebrow: String
    let title: String
    let subtitle: String
    let value: String
    let label: String

    var body: some View {
        HStack(alignment: .center, spacing: 16) {
            VStack(alignment: .leading, spacing: 4) {
                Text(eyebrow)
                    .font(.caption.monospaced())
                    .textCase(.uppercase)
                    .foregroundStyle(.secondary)
                Text(title)
                    .font(.title3.weight(.bold))
                Text(subtitle)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            VStack(spacing: 2) {
                Text(value)
                    .font(.title3.monospacedDigit().weight(.semibold))
                Text(label)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .frame(minWidth: 72)
            .padding(.vertical, 10)
            .glassSurface()
        }
        .padding(12)
        .glassSurface()
    }
}

struct SectionHeader<Trailing: View>: View {
    let title: String
    @ViewBuilder let trailing: Trailing

    var body: some View {
        HStack {
            Text(title)
                .font(.system(size: 17, weight: .bold))
            Spacer()
            trailing
        }
    }
}

struct MaterialCard<Content: View>: View {
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .glassSurface()
    }
}

struct SourceCard: View {
    let source: MobileSource

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                HStack(spacing: 7) {
                    BrandIcon(kind: BrandIcon.kind(for: sourceBrandHint), size: 18)
                    Text(source.displayName ?? source.machine ?? source.sourceID)
                        .font(.subheadline.weight(.semibold))
                }
                Spacer()
                Text(statusLabel(source.status))
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(statusColor.opacity(0.13), in: Capsule())
                    .foregroundStyle(statusColor)
            }
            Text(sourceMeta)
                .font(.caption)
                .foregroundStyle(.secondary)
            if let error = source.errorMessage, !error.isEmpty {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.orange)
            }
        }
        .padding(.vertical, 4)
    }

    private var sourceBrandHint: String {
        [
            source.sourceID,
            source.displayName,
            source.machine,
            source.platform
        ]
        .compactMap { $0 }
        .joined(separator: " ")
    }

    private var statusColor: Color {
        switch source.status {
        case "ok":
            return .green
        case "stale":
            return .orange
        default:
            return .red
        }
    }

    private var sourceMeta: String {
        [
            source.sourceID,
            source.platform,
            source.osUser.map { "user \($0)" },
            source.lastObservedAt.map { "观测 \(shortTime($0))" },
            source.lastPushedAt.map { "上报 \(shortTime($0))" }
        ]
        .compactMap { $0 }
        .joined(separator: " · ")
    }
}

struct BreakdownSegmentedControl: View {
    @Binding var selection: BreakdownDimension

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(BreakdownDimension.allCases, id: \.self) { dimension in
                    let isSelected = selection == dimension
                    Button {
                        selection = dimension
                    } label: {
                        Text(dimension.label)
                            .font(.system(size: 13, weight: isSelected ? .semibold : .regular))
                            .padding(.horizontal, 12)
                            .padding(.vertical, 8)
                            .foregroundStyle(isSelected ? Color.primary : Color.secondary)
                            .background(segmentBackground(isSelected: isSelected), in: Capsule())
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(4)
        }
        .glassSurface()
    }
}

struct BreakdownDrilldownView: View {
    let row: MobileBreakdownRow
    let dimension: BreakdownDimension
    let sections: [BreakdownDrilldownSection]
    let onBack: () -> Void

    var body: some View {
        SummaryStrip(
            eyebrow: dimension.label,
            title: row.label,
            subtitle: detailMeta,
            value: TokenFormat.compact(row.tokens),
            label: "Tokens"
        )

        Button {
            onBack()
        } label: {
            Label("返回明细", systemImage: "chevron.left")
                .font(.footnote.weight(.semibold))
        }
        .buttonStyle(.plain)
        .foregroundStyle(.blue)
        .frame(maxWidth: .infinity, alignment: .leading)

        ForEach(sections) { section in
            DrilldownSectionCard(section: section)
        }
    }

    private var detailMeta: String {
        let sourceCount = row.sourceIDs?.count ?? 0
        if sourceCount > 0 {
            return "\(sourceCount) 个来源 · 当前周期下钻"
        }
        return "当前周期下钻"
    }
}

struct DrilldownSectionCard: View {
    let section: BreakdownDrilldownSection

    var body: some View {
        MaterialCard {
            SectionHeader(title: section.title) {
                Text("\(section.rows.count)")
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            VStack(spacing: 12) {
                ForEach(section.rows) { row in
                    BarRow(label: row.label, value: row.tokens, maxValue: maxValue)
                }
            }
        }
    }

    private var maxValue: Int {
        max(section.rows.map(\.tokens).max() ?? 1, 1)
    }
}

struct BarRow: View {
    let label: String
    let value: Int
    let maxValue: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text(label)
                    .font(.subheadline.weight(.semibold))
                    .lineLimit(1)
                Spacer()
                Text(TokenFormat.compact(value))
                    .font(.subheadline.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(Color.secondary.opacity(0.14))
                    Capsule()
                        .fill(LinearGradient(colors: [.blue, .mint], startPoint: .leading, endPoint: .trailing))
                        .frame(width: max(8, proxy.size.width * CGFloat(value) / CGFloat(max(maxValue, 1))))
                }
            }
            .frame(height: 8)
        }
    }
}

struct LimitWindowCard: View {
    let window: MobileLimitWindow

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            BrandIcon(kind: BrandIcon.kind(for: window.provider), size: 24)
                .frame(width: 34, height: 34)
                .glassSurface(cornerRadius: 8)
            VStack(alignment: .leading, spacing: 9) {
                HStack(alignment: .firstTextBaseline) {
                    Text("\(window.provider.capitalized) · \(window.window)")
                        .font(.subheadline.weight(.semibold))
                    Spacer()
                    Text(statusLabel(window.isOfficialObserved ? "observed" : window.confidence))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(window.isOfficialObserved ? Color.green : Color.orange)
                }
                if window.isOfficialObserved {
                    Gauge(value: window.remainingPercent, in: 0...100) {
                        EmptyView()
                    } currentValueLabel: {
                        Text("\(Int(window.remainingPercent.rounded()))%")
                            .font(.caption.monospacedDigit().weight(.semibold))
                    }
                    .gaugeStyle(.accessoryLinearCapacity)
                    .tint(limitTint)
                    ProgressView(value: window.remainingPercent, total: 100)
                        .tint(limitTint)
                    Text("剩余 \(Int(window.remainingPercent.rounded()))% · 重置 \(window.resetAt ?? "--") · \(window.sourceType ?? "--")")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    Text(window.status)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(12)
        .glassSurface()
    }

    private var limitTint: Color {
        if window.remainingPercent < 35 {
            return .red
        }
        if window.remainingPercent < 60 {
            return .orange
        }
        return .green
    }
}

enum BrandKind: Equatable {
    case claudeCode
    case codex
    case generic
}

struct BrandIcon: View {
    let kind: BrandKind
    let size: CGFloat

    static func kind(for rawValue: String) -> BrandKind {
        let lowercased = rawValue.lowercased()
        if lowercased.contains("claude") {
            return .claudeCode
        }
        if lowercased.contains("codex") || lowercased.contains("openai") || lowercased.contains("gpt") {
            return .codex
        }
        return .generic
    }

    var body: some View {
        Group {
            switch kind {
            case .claudeCode:
                ClaudeCodeLogo()
                    .fill(Color(red: 0.85, green: 0.47, blue: 0.34))
            case .codex:
                CodexLogo()
            case .generic:
                Image(systemName: "terminal")
                    .font(.system(size: size * 0.72, weight: .semibold))
                    .foregroundStyle(.secondary)
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

struct ClaudeCodeLogo: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        func x(_ value: CGFloat) -> CGFloat { rect.minX + value / 24 * rect.width }
        func y(_ value: CGFloat) -> CGFloat { rect.minY + value / 24 * rect.height }
        path.move(to: CGPoint(x: x(20.998), y: y(10.949)))
        path.addLine(to: CGPoint(x: x(24), y: y(10.949)))
        path.addLine(to: CGPoint(x: x(24), y: y(14.051)))
        path.addLine(to: CGPoint(x: x(21), y: y(14.051)))
        path.addLine(to: CGPoint(x: x(21), y: y(17.079)))
        path.addLine(to: CGPoint(x: x(19.513), y: y(17.079)))
        path.addLine(to: CGPoint(x: x(19.513), y: y(20)))
        path.addLine(to: CGPoint(x: x(18), y: y(20)))
        path.addLine(to: CGPoint(x: x(18), y: y(17.079)))
        path.addLine(to: CGPoint(x: x(16.513), y: y(17.079)))
        path.addLine(to: CGPoint(x: x(16.513), y: y(20)))
        path.addLine(to: CGPoint(x: x(15), y: y(20)))
        path.addLine(to: CGPoint(x: x(15), y: y(17.079)))
        path.addLine(to: CGPoint(x: x(9), y: y(17.079)))
        path.addLine(to: CGPoint(x: x(9), y: y(20)))
        path.addLine(to: CGPoint(x: x(7.488), y: y(20)))
        path.addLine(to: CGPoint(x: x(7.488), y: y(17.079)))
        path.addLine(to: CGPoint(x: x(6), y: y(17.079)))
        path.addLine(to: CGPoint(x: x(6), y: y(20)))
        path.addLine(to: CGPoint(x: x(4.487), y: y(20)))
        path.addLine(to: CGPoint(x: x(4.487), y: y(17.079)))
        path.addLine(to: CGPoint(x: x(3), y: y(17.079)))
        path.addLine(to: CGPoint(x: x(3), y: y(14.05)))
        path.addLine(to: CGPoint(x: x(0), y: y(14.05)))
        path.addLine(to: CGPoint(x: x(0), y: y(10.95)))
        path.addLine(to: CGPoint(x: x(3), y: y(10.95)))
        path.addLine(to: CGPoint(x: x(3), y: y(5)))
        path.addLine(to: CGPoint(x: x(20.998), y: y(5)))
        path.closeSubpath()
        path.move(to: CGPoint(x: x(6), y: y(10.949)))
        path.addLine(to: CGPoint(x: x(7.488), y: y(10.949)))
        path.addLine(to: CGPoint(x: x(7.488), y: y(8.102)))
        path.addLine(to: CGPoint(x: x(6), y: y(8.102)))
        path.closeSubpath()
        path.move(to: CGPoint(x: x(16.51), y: y(10.949)))
        path.addLine(to: CGPoint(x: x(18), y: y(10.949)))
        path.addLine(to: CGPoint(x: x(18), y: y(8.102)))
        path.addLine(to: CGPoint(x: x(16.51), y: y(8.102)))
        path.closeSubpath()
        return path
    }
}

struct CodexLogo: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        func x(_ value: CGFloat) -> CGFloat { rect.minX + value / 24 * rect.width }
        func y(_ value: CGFloat) -> CGFloat { rect.minY + value / 24 * rect.height }

        path.move(to: CGPoint(x: x(9.064), y: y(3.344)))
        path.addCurve(to: CGPoint(x: x(11.349), y: y(3.032)), control1: CGPoint(x: x(9.754), y: y(3.02)), control2: CGPoint(x: x(10.516), y: y(2.916)))
        path.addCurve(to: CGPoint(x: x(14.022), y: y(4.307)), control1: CGPoint(x: x(12.349), y: y(3.147)), control2: CGPoint(x: x(13.24), y: y(3.572)))
        path.addCurve(to: CGPoint(x: x(14.102), y: y(4.328)), control1: CGPoint(x: x(14.032), y: y(4.317)), control2: CGPoint(x: x(14.076), y: y(4.333)))
        path.addCurve(to: CGPoint(x: x(17.148), y: y(4.603)), control1: CGPoint(x: x(15.06), y: y(3.995)), control2: CGPoint(x: x(16.075), y: y(4.087)))
        path.addLine(to: CGPoint(x: x(17.311), y: y(4.682)))
        path.addCurve(to: CGPoint(x: x(19.499), y: y(7.081)), control1: CGPoint(x: x(18.321), y: y(5.177)), control2: CGPoint(x: x(19.05), y: y(5.977)))
        path.addCurve(to: CGPoint(x: x(19.68), y: y(9.899)), control1: CGPoint(x: x(19.84), y: y(7.914)), control2: CGPoint(x: x(19.9), y: y(8.854)))
        path.addCurve(to: CGPoint(x: x(19.71), y: y(10.014)), control1: CGPoint(x: x(19.672), y: y(9.94)), control2: CGPoint(x: x(19.683), y: y(9.984)))
        path.addCurve(to: CGPoint(x: x(20.893), y: y(12.184)), control1: CGPoint(x: x(20.304), y: y(10.621)), control2: CGPoint(x: x(20.698), y: y(11.344)))
        path.addCurve(to: CGPoint(x: x(20.006), y: y(16.038)), control1: CGPoint(x: x(21.182), y: y(13.609)), control2: CGPoint(x: x(20.886), y: y(14.894)))
        path.addLine(to: CGPoint(x: x(19.87), y: y(16.204)))
        path.addCurve(to: CGPoint(x: x(17.669), y: y(17.592)), control1: CGPoint(x: x(19.296), y: y(16.865)), control2: CGPoint(x: x(18.562), y: y(17.328)))
        path.addCurve(to: CGPoint(x: x(17.588), y: y(17.668)), control1: CGPoint(x: x(17.629), y: y(17.604)), control2: CGPoint(x: x(17.6), y: y(17.631)))
        path.addCurve(to: CGPoint(x: x(16.848), y: y(19.158)), control1: CGPoint(x: x(17.397), y: y(18.219)), control2: CGPoint(x: x(17.205), y: y(18.687)))
        path.addCurve(to: CGPoint(x: x(13.137), y: y(20.996)), control1: CGPoint(x: x(15.948), y: y(20.345)), control2: CGPoint(x: x(14.626), y: y(21.004)))
        path.addCurve(to: CGPoint(x: x(9.98), y: y(19.694)), control1: CGPoint(x: x(11.95), y: y(20.99)), control2: CGPoint(x: x(10.898), y: y(20.556)))
        path.addCurve(to: CGPoint(x: x(9.875), y: y(19.67)), control1: CGPoint(x: x(9.954), y: y(19.67)), control2: CGPoint(x: x(9.914), y: y(19.661)))
        path.addCurve(to: CGPoint(x: x(8.671), y: y(19.808)), control1: CGPoint(x: x(9.487), y: y(19.795)), control2: CGPoint(x: x(9.095), y: y(19.813)))
        path.addCurve(to: CGPoint(x: x(6.726), y: y(19.342)), control1: CGPoint(x: x(7.975), y: y(19.8)), control2: CGPoint(x: x(7.327), y: y(19.645)))
        path.addCurve(to: CGPoint(x: x(4.702), y: y(17.39)), control1: CGPoint(x: x(5.983), y: y(18.965)), control2: CGPoint(x: x(5.307), y: y(18.314)))
        path.addCurve(to: CGPoint(x: x(4.318), y: y(14.131)), control1: CGPoint(x: x(4.342), y: y(16.553)), control2: CGPoint(x: x(4.214), y: y(15.467)))
        path.addCurve(to: CGPoint(x: x(4.297), y: y(14.027)), control1: CGPoint(x: x(4.327), y: y(14.09)), control2: CGPoint(x: x(4.318), y: y(14.049)))
        path.addCurve(to: CGPoint(x: x(3.263), y: y(12.376)), control1: CGPoint(x: x(3.842), y: y(13.579)), control2: CGPoint(x: x(3.497), y: y(13.029)))
        path.addCurve(to: CGPoint(x: x(3.153), y: y(9.584)), control1: CGPoint(x: x(3.126), y: y(11.994)), control2: CGPoint(x: x(3.063), y: y(10.647)))
        path.addCurve(to: CGPoint(x: x(5.086), y: y(6.966)), control1: CGPoint(x: x(3.49), y: y(8.472)), control2: CGPoint(x: x(4.135), y: y(7.599)))
        path.addCurve(to: CGPoint(x: x(6.333), y: y(6.409)), control1: CGPoint(x: x(5.298), y: y(6.825)), control2: CGPoint(x: x(5.963), y: y(6.516)))
        path.addCurve(to: CGPoint(x: x(6.398), y: y(6.343)), control1: CGPoint(x: x(6.363), y: y(6.4)), control2: CGPoint(x: x(6.389), y: y(6.374)))
        path.addCurve(to: CGPoint(x: x(7.227), y: y(4.728)), control1: CGPoint(x: x(6.575), y: y(5.738)), control2: CGPoint(x: x(6.851), y: y(5.199)))
        path.addCurve(to: CGPoint(x: x(9.064), y: y(3.344)), control1: CGPoint(x: x(7.704), y: y(4.13)), control2: CGPoint(x: x(8.316), y: y(3.668)))
        path.closeSubpath()

        path.move(to: CGPoint(x: x(12.546), y: y(13.909)))
        path.addCurve(to: CGPoint(x: x(12.546), y: y(15.181)), control1: CGPoint(x: x(12.193), y: y(13.909)), control2: CGPoint(x: x(11.91), y: y(14.193)))
        path.addLine(to: CGPoint(x: x(16.182), y: y(15.181)))
        path.addCurve(to: CGPoint(x: x(16.182), y: y(13.909)), control1: CGPoint(x: x(17.03), y: y(15.181)), control2: CGPoint(x: x(17.03), y: y(13.909)))
        path.addLine(to: CGPoint(x: x(12.546), y: y(13.909)))
        path.closeSubpath()

        path.move(to: CGPoint(x: x(8.462), y: y(9.23)))
        path.addCurve(to: CGPoint(x: x(7.356), y: y(9.861)), control1: CGPoint(x: x(8.112), y: y(8.612)), control2: CGPoint(x: x(7.007), y: y(9.241)))
        path.addLine(to: CGPoint(x: x(8.628), y: y(12.085)))
        path.addLine(to: CGPoint(x: x(7.362), y: y(14.221)))
        path.addCurve(to: CGPoint(x: x(8.457), y: y(14.87)), control1: CGPoint(x: x(7.006), y: y(14.822)), control2: CGPoint(x: x(8.105), y: y(15.474)))
        path.addLine(to: CGPoint(x: x(9.911), y: y(12.415)))
        path.addCurve(to: CGPoint(x: x(9.916), y: y(11.775)), control1: CGPoint(x: x(10.025), y: y(12.222)), control2: CGPoint(x: x(10.027), y: y(11.968)))
        path.addLine(to: CGPoint(x: x(8.462), y: y(9.23)))
        path.closeSubpath()

        return path
    }
}

struct CustomGlassTabBar: View {
    @Binding var selection: AppTab

    var body: some View {
        HStack(spacing: 2) {
            ForEach(AppTab.allCases, id: \.self) { tab in
                LiquidGlassTabButton(
                    tab: tab,
                    isSelected: selection == tab
                ) {
                    selection = tab
                }
            }
        }
        .padding(6)
        .glassSurface(cornerRadius: 8)
    }
}

struct LiquidGlassTabButton: View {
    let tab: AppTab
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 3) {
                Image(systemName: tab.systemImage)
                    .font(.system(size: 21, weight: .semibold))
                    .frame(width: 42, height: 30)
                    .background {
                        if isSelected {
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(.ultraThinMaterial)
                                .overlay {
                                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                                        .stroke(.white.opacity(0.55), lineWidth: 1)
                                }
                        }
                    }
                Text(tab.title)
                    .font(.caption2.weight(.semibold))
            }
            .frame(maxWidth: .infinity)
            .foregroundStyle(isSelected ? Color.blue : Color.secondary)
        }
        .buttonStyle(.plain)
    }
}

struct AppScrollView<Content: View>: View {
    var topPadding: CGFloat = 0
    var bottomPadding: CGFloat = 110
    @ViewBuilder let content: Content

    var body: some View {
        ScrollView {
            VStack(spacing: 10) {
                content
            }
            .padding(.top, topPadding)
            .padding(.horizontal, 14)
            .padding(.bottom, 12)
        }
        .background {
            ZStack(alignment: .top) {
                Color.appGroupedBackground
                    .ignoresSafeArea()
                LinearGradient(
                    colors: [Color.blue.opacity(0.14), Color.mint.opacity(0.08), .clear],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
                .frame(height: 220)
                .ignoresSafeArea()
            }
        }
        .safeAreaInset(edge: .bottom) {
            Color.clear.frame(height: bottomPadding)
        }
    }
}

private func segmentBackground(isSelected: Bool) -> Color {
    isSelected ? Color.appSecondaryGroupedBackground : Color.clear
}

private extension Color {
    static var appGroupedBackground: Color {
        #if canImport(UIKit)
        Color(UIColor.systemGroupedBackground)
        #elseif canImport(AppKit)
        Color(NSColor.windowBackgroundColor)
        #else
        Color.gray.opacity(0.12)
        #endif
    }

    static var appSecondaryGroupedBackground: Color {
        #if canImport(UIKit)
        Color(UIColor.secondarySystemGroupedBackground)
        #elseif canImport(AppKit)
        Color(NSColor.controlBackgroundColor)
        #else
        Color.gray.opacity(0.18)
        #endif
    }
}

private extension View {
    func glassSurface(cornerRadius: CGFloat = 8) -> some View {
        modifier(GlassSurface(cornerRadius: cornerRadius))
    }
}

struct GlassSurface: ViewModifier {
    let cornerRadius: CGFloat

    func body(content: Content) -> some View {
        content
            .background(
                ZStack {
                    RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                        .fill(.ultraThinMaterial)
                    RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                        .fill(
                            LinearGradient(
                                colors: [
                                    .white.opacity(0.46),
                                    .white.opacity(0.10),
                                    .white.opacity(0.30)
                                ],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                }
            )
            .overlay {
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(.white.opacity(0.46), lineWidth: 1)
            }
            .shadow(color: .black.opacity(0.08), radius: 14, y: 6)
    }
}

enum BreakdownDimension: CaseIterable {
    static let allCases: [BreakdownDimension] = [.date, .machine, .account, .model, .agent]

    case machine
    case account
    case agent
    case model
    case date

    var label: String {
        switch self {
        case .machine:
            return "Machine"
        case .account:
            return "OS User"
        case .agent:
            return "Agent"
        case .model:
            return "Model"
        case .date:
            return "Date"
        }
    }

    var title: String {
        switch self {
        case .machine:
            return "按机器"
        case .account:
            return "按系统账户"
        case .agent:
            return "按 Agent"
        case .model:
            return "按模型"
        case .date:
            return "按日期"
        }
    }
}

func statusLabel(_ status: String) -> String {
    switch status {
    case "ok":
        return "正常"
    case "stale":
        return "过期"
    case "observed":
        return "可信"
    case "missing":
        return "缺失"
    default:
        return status
    }
}

func shortTime(_ value: String) -> String {
    if value.count >= 16 {
        let start = value.index(value.startIndex, offsetBy: 11)
        let end = value.index(value.startIndex, offsetBy: 16)
        return String(value[start..<end])
    }
    return value
}
