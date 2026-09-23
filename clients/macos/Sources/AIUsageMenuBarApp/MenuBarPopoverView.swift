import AIUsageMenuBarCore
import AppKit
import SwiftUI

struct MenuBarPopoverView: View {
    @ObservedObject var model: MenuBarAppModel
    var onQuit: (() -> Void)?
    var onContentHeightChange: (() -> Void)?
    @State private var contentHeight: CGFloat
    @State private var hoveredBar: MenuTrendBar?
    @State private var hoverLocation: CGPoint?
    @State private var expandedSources: Set<String> = []
    @State private var expandedAgents: Set<String> = []
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    private let periods: [(String, String)] = [
        ("today", "日"), ("week", "周"), ("month", "月"),
    ]

    init(model: MenuBarAppModel, onQuit: (() -> Void)? = nil, onContentHeightChange: (() -> Void)? = nil) {
        self.model = model
        self.onQuit = onQuit
        self.onContentHeightChange = onContentHeightChange
        let initialEstimate: CGFloat = model.hasLoadedUsableSummary ? 560 : 200
        _contentHeight = State(initialValue: initialEstimate)
    }

    private var maxContentHeight: CGFloat {
        MenuBarPopoverLayout.maxContentHeight(screenHeight: NSScreen.main?.visibleFrame.height)
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            if !model.hasConfig {
                setupState
            } else {
                ScrollView {
                    mainContent.background(GeometryReader { geometry in
                        Color.clear.preference(key: PopoverContentHeight.self, value: geometry.size.height)
                    })
                }
                .frame(height: min(max(contentHeight, 200), maxContentHeight))
                .onPreferenceChange(PopoverContentHeight.self) { height in
                    guard height > 10 else { return }
                    guard abs(contentHeight - height) > 0.5 else { return }
                    contentHeight = height
                    DispatchQueue.main.async { onContentHeightChange?() }
                }
            }
        }
        .frame(width: MenuBarPopoverLayout.width)
        .fixedSize(horizontal: false, vertical: true)
        .modifier(PopoverGlassSurface(reduceTransparency: reduceTransparency, increasedContrast: contrast == .increased))
    }

    // MARK: – Header

    private var header: some View {
        HStack(spacing: 12) {
            DualRingAppIcon(size: 30)
                .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
            VStack(alignment: .leading, spacing: 3) {
                Text("AI Usage")
                    .font(.system(size: 15, weight: .semibold))
                Text("数据 \(model.state.lastUpdatedText)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if model.isLoading {
                ProgressView().controlSize(.small)
            }
            Button { model.refresh(force: true) } label: {
                Image(systemName: "arrow.clockwise").frame(width: 26, height: 26)
            }
            .buttonStyle(.borderless)
            .focusable(false)
            .help("刷新")
            Button {
                if let url = model.dashboardURL { NSWorkspace.shared.open(url) }
            } label: {
                Image(systemName: "safari").frame(width: 26, height: 26)
            }
            .buttonStyle(.borderless)
            .focusable(false)
            .help("打开 Dashboard")
            Button { onQuit?() } label: {
                Image(systemName: "power").frame(width: 26, height: 26)
            }
            .buttonStyle(.borderless)
            .focusable(false)
            .help("退出 AI Usage")
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .overlay(alignment: .bottom) { Divider() }
    }

    // MARK: – Setup state

    private var setupState: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("需要配置服务地址和访问 token", systemImage: "lock.shield")
                .font(.headline)
            Text("配置文件位置")
                .font(.caption)
                .foregroundStyle(.secondary)
            Text(model.paths.configURL.path)
                .font(.system(.caption, design: .monospaced))
                .textSelection(.enabled)
                .lineLimit(3)
            Text("安装脚本可以写入这个配置；运行时不会读取 Documents。")
                .font(.footnote)
                .foregroundStyle(.secondary)
            Spacer()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
    }

    // MARK: – Main content

    private var mainContent: some View {
        VStack(spacing: 0) {
            if let error = model.errorMessage {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 16)
                    .padding(.top, 8)
            }
            if let coverage = model.state.providerUsageCoverageText {
                Label(coverage, systemImage: "info.circle.fill")
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 16)
                    .padding(.top, 8)
            }

            Picker(selection: $model.selectedPeriodID) {
                ForEach(periods, id: \.0) { id, label in Text(label).tag(id) }
            } label: { EmptyView() }
            .pickerStyle(.segmented)
            .labelsHidden()
            .padding(.horizontal, 16)
            .padding(.top, 8)
            .padding(.bottom, 4)
            .onChange(of: model.selectedPeriodID) { _, newValue in
                model.refresh(periodID: newValue)
            }

            historyNavigation
            VStack(spacing: 8) {
                if model.hasLoadedUsableSummary {
                    heroCard
                } else {
                    Text(model.isLoading ? "正在读取所选日期…" : "所选日期暂无可用数据")
                        .font(.callout).foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 80)
                }
                if !model.state.quotaRings.isEmpty { quotaSection }
                if !model.state.sources.isEmpty { sourcesSection }
            }
            .padding(.horizontal, 16)
            .padding(.bottom, 16)
        }
        .onChange(of: model.state.trendBars) { _, _ in
            hoveredBar = nil; hoverLocation = nil
        }
    }

    private var historyNavigation: some View {
        HStack(spacing: 8) {
            Button { model.movePeriod(-1) } label: { Image(systemName: "chevron.left") }
                .disabled(!model.selection.canGoEarlier)
                .help("上一周期")
            VStack(spacing: 2) {
                Text(model.state.periodLabel).font(.system(size: 12, weight: .semibold))
                Text(model.state.dateRangeText).font(.system(size: 10)).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity)
            Button { model.movePeriod(1) } label: { Image(systemName: "chevron.right") }
                .disabled(!model.selection.canGoLater)
                .help("下一周期")
        }
        .buttonStyle(.borderless)
        .padding(.horizontal, 20)
        .padding(.bottom, 8)
        .onChange(of: model.selection) { _, _ in
            expandedSources.removeAll()
            expandedAgents.removeAll()
        }
    }

    // MARK: – Hero card

    private var heroCard: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(model.state.heroTotalText)
                .font(.system(size: 38, weight: .semibold, design: .rounded))
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.7)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.bottom, 6)

            Text(model.state.tokenBreakdownText)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
                .padding(.bottom, 12)

            PopoverTrendBars(
                bars: model.state.trendBars,
                ceilingFraction: model.state.trendCeilingFraction,
                ceilingText: model.state.trendRefCeilingText,
                midFraction: model.state.trendMidFraction,
                midText: model.state.trendMidText,
                hoveredBar: $hoveredBar,
                hoverLocation: $hoverLocation
            )
        }
        .padding(14)
        .background(cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(Color.primary.opacity(0.07), lineWidth: 0.5)
        )
    }

    // MARK: – Quota section

    private var quotaSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            sectionTitle("Provider 用量与额度")
            HStack(alignment: .top, spacing: 0) {
                ForEach(Array(model.state.quotaRings.enumerated()), id: \.element.id) { index, ring in
                    if index > 0 { Divider().padding(.vertical, 4) }
                    QuotaRingItem(data: ring).frame(maxWidth: .infinity)
                }
            }
        }
        .padding(12)
        .background(cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(Color.primary.opacity(0.07), lineWidth: 0.5)
        )
    }

    // MARK: – Sources section

    private var sourcesSection: some View {
        VStack(alignment: .leading, spacing: 0) {
            sectionTitle("来源").padding(.bottom, 10)
            ForEach(Array(model.state.sources.enumerated()), id: \.element.id) { index, row in
                if index > 0 { Divider().padding(.vertical, 4) }
                DisclosureGroup(isExpanded: expansionBinding(row.id, in: $expandedSources)) {
                    if let agents = row.agents, !agents.isEmpty {
                        ForEach(agents) { agent in
                            if agent.status == "available" {
                                DisclosureGroup(isExpanded: expansionBinding("\(row.id)/\(agent.id)", in: $expandedAgents)) {
                                    if agent.models.isEmpty {
                                        Text("模型明细缺失").font(.caption).foregroundStyle(.secondary)
                                    } else {
                                        ForEach(agent.models) { item in
                                            HStack {
                                                Text(item.title).lineLimit(2)
                                                Spacer(minLength: 8)
                                                Text(item.valueText).monospacedDigit()
                                            }
                                            .font(.system(size: 11))
                                            .foregroundStyle(.secondary)
                                            .help("\(item.title) · \(item.tokens) tokens")
                                            .padding(.vertical, 2)
                                        }
                                    }
                                } label: { agentLabel(agent) }
                            } else {
                                agentLabel(agent)
                            }
                        }
                    } else {
                        Text("Agent / 模型明细缺失")
                            .font(.caption).foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                } label: {
                    HStack(spacing: 10) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(row.title).font(.system(size: 13, weight: .medium)).lineLimit(1)
                            if !row.subtitle.isEmpty {
                                Text(row.subtitle).font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(2)
                            }
                        }
                        Spacer()
                        Text(row.value).font(.system(size: 12, weight: .semibold).monospacedDigit()).foregroundStyle(.secondary)
                    }
                    .frame(minHeight: 34)
                }
                .padding(.vertical, 2)
            }
        }
        .padding(12)
        .background(cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(Color.primary.opacity(0.07), lineWidth: 0.5)
        )
    }

    private func agentLabel(_ agent: MobileSourceAgent) -> some View {
        HStack {
            Text(agent.label)
            Spacer()
            Text(agent.valueText).monospacedDigit().foregroundStyle(.secondary)
        }
        .font(.system(size: 12))
        .padding(.vertical, 4)
        .help(agent.status == "available" ? "\(agent.label) · \(agent.tokens) tokens" : "\(agent.label) 数据缺失")
    }

    private func expansionBinding(_ id: String, in expanded: Binding<Set<String>>) -> Binding<Bool> {
        Binding(get: { expanded.wrappedValue.contains(id) }, set: { value in
            if value { expanded.wrappedValue.insert(id) } else { expanded.wrappedValue.remove(id) }
        })
    }

    // MARK: – Helpers

    private func sectionTitle(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 11, weight: .semibold))
            .tracking(0.4)
            .textCase(.uppercase)
            .foregroundStyle(.tertiary)
    }

    private var cardBackground: some ShapeStyle {
        Color(nsColor: .windowBackgroundColor).opacity(reduceTransparency || contrast == .increased ? 1 : 0.56)
    }
}

private struct PopoverContentHeight: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = nextValue() }
}

private struct PopoverGlassSurface: ViewModifier {
    let reduceTransparency: Bool
    let increasedContrast: Bool

    @ViewBuilder
    func body(content: Content) -> some View {
        if reduceTransparency || increasedContrast {
            content.background(Color(nsColor: .windowBackgroundColor))
        } else {
            // SwiftUI 7 ships the Glass API; runtime availability alone cannot
            // make that symbol compile against an older macOS SDK.
            #if canImport(SwiftUI, _version: 7.0)
            if #available(macOS 26.0, *) {
                content.glassEffect(.regular, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            } else {
                content.background(MacOSGlassBackground())
            }
            #else
            content.background(MacOSGlassBackground())
            #endif
        }
    }
}

private struct MacOSGlassBackground: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = .popover
        view.blendingMode = .behindWindow
        view.state = .active
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {
        nsView.material = .popover
        nsView.blendingMode = .behindWindow
        nsView.state = .active
    }
}

// MARK: – DualRingAppIcon

struct DualRingAppIcon: View {
    var size: CGFloat = 30

    var body: some View {
        ZStack {
            Color(nsColor: .controlColor)
            let s = size / 100
            // Outer ring: track + fill (Claude orange, 70%)
            Circle()
                .stroke(Color(red: 0.855, green: 0.467, blue: 0.337).opacity(0.18), lineWidth: 11 * s)
                .frame(width: 80 * s, height: 80 * s)
            Circle()
                .trim(from: 0, to: 0.70)
                .stroke(Color(red: 0.855, green: 0.467, blue: 0.337),
                        style: StrokeStyle(lineWidth: 11 * s, lineCap: .round))
                .frame(width: 80 * s, height: 80 * s)
                .rotationEffect(.degrees(-90))
            // Inner ring: track + fill (OpenAI blue, 45%)
            Circle()
                .stroke(Color(red: 0.039, green: 0.518, blue: 1.0).opacity(0.18), lineWidth: 9 * s)
                .frame(width: 52 * s, height: 52 * s)
            Circle()
                .trim(from: 0, to: 0.45)
                .stroke(Color(red: 0.039, green: 0.518, blue: 1.0),
                        style: StrokeStyle(lineWidth: 9 * s, lineCap: .round))
                .frame(width: 52 * s, height: 52 * s)
                .rotationEffect(.degrees(-90))
            // Center dot
            Circle()
                .fill(Color.white.opacity(0.65))
                .frame(width: 7 * s, height: 7 * s)
        }
        .frame(width: size, height: size)
    }
}

// MARK: – PopoverTrendBars

struct PopoverTrendBars: View {
    let bars: [MenuTrendBar]
    let ceilingFraction: Double
    let ceilingText: String
    let midFraction: Double
    let midText: String
    @Binding var hoveredBar: MenuTrendBar?
    @Binding var hoverLocation: CGPoint?

    private let chartHeight: CGFloat = 52

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            GeometryReader { geo in
                ZStack(alignment: .bottom) {
                    // Dashed reference line at top
                    Canvas { ctx, size in
                        var path = Path()
                        var x: CGFloat = 0
                        while x < size.width {
                            path.move(to: CGPoint(x: x, y: 0.5))
                            path.addLine(to: CGPoint(x: min(x + 3, size.width), y: 0.5))
                            x += 5
                        }
                        ctx.stroke(path, with: .color(Color.primary.opacity(0.22)), lineWidth: 1)
                    }
                    .frame(height: 1)
                    .frame(maxHeight: .infinity, alignment: .top)

                    // Ceiling label (top-right)
                    Text(ceilingText)
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(Color.primary.opacity(0.42))
                        .frame(maxWidth: .infinity, alignment: .trailing)
                        .frame(maxHeight: .infinity, alignment: .top)
                        .offset(y: -9)

                    // Mid reference line + label
                    if midFraction > 0 && !midText.isEmpty {
                        Canvas { ctx, size in
                            let y = size.height * CGFloat(1.0 - midFraction)
                            var path = Path()
                            var x: CGFloat = 0
                            while x < size.width {
                                path.move(to: CGPoint(x: x, y: y))
                                path.addLine(to: CGPoint(x: min(x + 3, size.width), y: y))
                                x += 5
                            }
                            ctx.stroke(path, with: .color(Color.primary.opacity(0.18)), lineWidth: 1)
                        }
                        .frame(height: chartHeight)
                        Text(midText)
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(Color.primary.opacity(0.35))
                            .frame(maxWidth: .infinity, maxHeight: chartHeight, alignment: .bottomTrailing)
                            .padding(.bottom, chartHeight * CGFloat(midFraction) + 2)
                    }

                    // Bars
                    HStack(alignment: .bottom, spacing: 4) {
                        ForEach(bars) { bar in
                            stackedBar(
                                bar,
                                height: max(
                                    4,
                                    chartHeight * CGFloat(bar.ratio * max(ceilingFraction, 0.05))
                                )
                            )
                                .frame(maxWidth: .infinity)
                                .help("\(bar.tooltipTitle) · \(bar.valueText)")
                        }
                    }

                    // Hover crosshair + tooltip
                    if let hb = hoveredBar, let hl = hoverLocation {
                        Rectangle()
                            .fill(Color.blue.opacity(0.22))
                            .frame(width: 1, height: chartHeight)
                            .position(x: hl.x, y: chartHeight / 2)
                        trendTooltip(hb)
                            .position(
                                x: min(max(hl.x, 80), geo.size.width - 80),
                                y: chartHeight / 2 - 18
                            )
                    }
                }
                .frame(height: chartHeight)
                .contentShape(Rectangle())
                .onContinuousHover { phase in
                    switch phase {
                    case .active(let loc):
                        hoverLocation = loc
                        hoveredBar = MenuTrendSelection.nearestBar(
                            in: bars, xLocation: Double(loc.x), width: Double(geo.size.width))
                    case .ended:
                        hoveredBar = nil; hoverLocation = nil
                    }
                }
            }
            .frame(height: chartHeight)

            // Time axis: show only labeled bars
            HStack {
                ForEach(bars.filter { !$0.label.isEmpty }) { bar in
                    Text(bar.label)
                        .font(.system(size: 9, weight: .medium))
                        .foregroundStyle(Color.primary.opacity(0.5))
                        .frame(maxWidth: .infinity)
                }
            }
            .frame(height: 12)

            HStack(spacing: 12) {
                ForEach(MenuTrendProvider.allCases, id: \.rawValue) { provider in
                    HStack(spacing: 4) {
                        Circle()
                            .fill(providerColor(provider))
                            .frame(width: 6, height: 6)
                        Text(provider.displayName)
                            .font(.system(size: 9, weight: .medium))
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func stackedBar(_ bar: MenuTrendBar, height: CGFloat) -> some View {
        if bar.totalTokens == 0 || bar.segments.isEmpty {
            RoundedRectangle(cornerRadius: 3)
                .fill(providerColor(.unknown))
                .frame(height: height)
                .opacity(0.28)
        } else {
            VStack(spacing: 0) {
                ForEach(bar.segments) { segment in
                    Rectangle()
                        .fill(providerColor(segment.provider))
                        .frame(height: height * CGFloat(segment.fraction))
                }
            }
            .frame(height: height, alignment: .bottom)
            .clipShape(RoundedRectangle(cornerRadius: 3, style: .continuous))
            .opacity(0.9)
        }
    }

    private func providerColor(_ provider: MenuTrendProvider) -> Color {
        let color = provider.color
        return Color(red: color.red, green: color.green, blue: color.blue, opacity: color.opacity)
    }

    private func trendTooltip(_ bar: MenuTrendBar) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(bar.tooltipTitle).font(.system(size: 10, weight: .semibold))
            Text(bar.valueText).font(.system(size: 11, weight: .semibold, design: .rounded).monospacedDigit())
        }
        .foregroundStyle(.primary)
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
        .background(Color(nsColor: .windowBackgroundColor).opacity(0.94))
        .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 7, style: .continuous).stroke(Color.primary.opacity(0.10), lineWidth: 1))
        .shadow(color: .black.opacity(0.12), radius: 8, x: 0, y: 3)
        .allowsHitTesting(false)
    }
}

// MARK: – QuotaRingItem

struct QuotaRingItem: View {
    let data: QuotaRingData

    var body: some View {
        VStack(spacing: 6) {
            ZStack {
                let outer = Color(red: data.outerRed, green: data.outerGreen, blue: data.outerBlue)
                let inner = Color(red: data.innerRed, green: data.innerGreen, blue: data.innerBlue)
                // Outer track + fill (r=40 → frame 88pt, stroke 11pt)
                Circle().stroke(outer.opacity(0.10), lineWidth: 11).frame(width: 88, height: 88)
                Circle()
                    .trim(from: 0, to: CGFloat(min(data.outerFraction, 1.0)))
                    .stroke(outer, style: StrokeStyle(lineWidth: 11, lineCap: .round))
                    .frame(width: 88, height: 88)
                    .rotationEffect(.degrees(-90))
                // Inner track + fill (r=26 → frame 57.2pt, stroke 9.9pt)
                Circle().stroke(inner.opacity(0.10), lineWidth: 9.9).frame(width: 57.2, height: 57.2)
                Circle()
                    .trim(from: 0, to: CGFloat(min(data.innerFraction, 1.0)))
                    .stroke(inner, style: StrokeStyle(lineWidth: 9.9, lineCap: .round))
                    .frame(width: 57.2, height: 57.2)
                    .rotationEffect(.degrees(-90))
                // Center name
                Text(data.displayName)
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(.primary)
            }
            .frame(width: 92, height: 92)

            VStack(spacing: 3) {
                Text(data.usageText)
                    .font(.system(size: 10, weight: .semibold).monospacedDigit())
                    .foregroundStyle(data.usageText == "用量不可用" ? Color.orange : .secondary)
                ringRow(key: data.outerLabel, pct: data.outerPctText, time: data.outerTimeText,
                        color: Color(red: data.outerRed, green: data.outerGreen, blue: data.outerBlue))
                ringRow(key: data.innerLabel, pct: data.innerPctText, time: data.innerTimeText,
                        color: Color(red: data.innerRed, green: data.innerGreen, blue: data.innerBlue))
                HStack(spacing: 4) {
                    Text(data.availabilityText)
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(data.availabilityText == "官方额度" ? Color.secondary : Color.orange)
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)
                    Spacer(minLength: 2)
                    Text(data.updatedText)
                        .font(.system(size: 9))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            .padding(.horizontal, 6)
        }
    }

    private func ringRow(key: String, pct: String, time: String, color: Color) -> some View {
        HStack(spacing: 5) {
            Text(key)
                .font(.system(size: 9.5, weight: .semibold))
                .foregroundStyle(color)
                .frame(minWidth: 22, alignment: .leading)
            Text(pct)
                .font(.system(size: 12, weight: .bold).monospacedDigit())
                .foregroundStyle(color)
                .frame(minWidth: 32, alignment: .leading)
            Spacer(minLength: 0)
            Text(time)
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
    }
}
