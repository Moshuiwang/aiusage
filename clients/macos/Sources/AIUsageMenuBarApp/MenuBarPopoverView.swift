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

            LiquidGlassPeriodPicker(selection: $model.selectedPeriodID, periods: periods)
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
                if index > 0 {
                    Divider().padding(.vertical, 8)
                }
                VStack(alignment: .leading, spacing: 7) {
                    HStack(alignment: .center, spacing: 9) {
                        ServerIcon(platform: row.platform, title: row.title, size: 24)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(row.title)
                                .font(.system(size: 13, weight: .semibold))
                                .lineLimit(1)
                            if !row.subtitle.isEmpty {
                                Text(row.subtitle)
                                    .font(.system(size: 10))
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                            }
                        }
                        Spacer(minLength: 8)
                        Text(row.value)
                            .font(.system(size: 12.5, weight: .semibold).monospacedDigit())
                            .foregroundStyle(.secondary)
                    }

                    if let models = row.flatModels, !models.isEmpty {
                        VStack(spacing: 3) {
                            ForEach(models) { item in
                                HStack(spacing: 8) {
                                    BrandIcon(kind: BrandIcon.kind(for: item.label, agent: item.agentID), size: 14)
                                    Text(item.title)
                                        .lineLimit(1)
                                        .truncationMode(.tail)
                                    Spacer(minLength: 8)
                                    Text(item.valueText)
                                        .monospacedDigit()
                                        .fontWeight(.medium)
                                    if let quotaWeekly = item.quotaWeeklyPercentText {
                                        Text(quotaWeekly)
                                            .font(.system(size: 10))
                                            .foregroundStyle(.tertiary)
                                    }
                                }
                                .font(.system(size: 11.5))
                                .foregroundStyle(.secondary)
                                .help("\(item.title) · \(item.tokens) tokens")
                                .padding(.vertical, 2.5)
                            }
                        }
                        .padding(.leading, 33)
                        .padding(.top, 2)
                    } else if let agents = row.agents, !agents.isEmpty {
                        VStack(spacing: 3) {
                            ForEach(agents) { agent in
                                ForEach(agent.models) { item in
                                    HStack(spacing: 8) {
                                        BrandIcon(kind: BrandIcon.kind(for: item.label, agent: agent.id), size: 14)
                                        Text(item.title).lineLimit(1).truncationMode(.tail)
                                        Spacer(minLength: 8)
                                        Text(item.valueText).monospacedDigit()
                                    }
                                    .font(.system(size: 11.5))
                                    .foregroundStyle(.secondary)
                                    .padding(.vertical, 2.5)
                                }
                            }
                        }
                        .padding(.leading, 33)
                        .padding(.top, 2)
                    } else {
                        Text("模型明细缺失")
                            .font(.caption).foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.leading, 33)
                            .padding(.vertical, 2)
                    }
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
                // segments 自底向上排列，VStack 自顶向下绘制，反转后 Claude 在底。
                ForEach(bar.segments.reversed()) { segment in
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
                    if !data.availabilityText.isEmpty {
                        Text(data.availabilityText)
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(Color.orange)
                            .lineLimit(1)
                            .minimumScaleFactor(0.8)
                    }
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

// MARK: – LiquidGlassPeriodPicker

struct LiquidGlassPeriodPicker: View {
    @Binding var selection: String
    let periods: [(String, String)]
    @Namespace private var animationNamespace

    var body: some View {
        HStack(spacing: 0) {
            ForEach(periods, id: \.0) { id, label in
                let isSelected = selection == id
                Button {
                    withAnimation(.spring(response: 0.28, dampingFraction: 0.78)) {
                        selection = id
                    }
                } label: {
                    Text(label)
                        .font(.system(size: 12, weight: isSelected ? .semibold : .medium))
                        .foregroundStyle(isSelected ? Color.primary : Color.secondary)
                        .frame(maxWidth: .infinity)
                        .frame(height: 24)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .focusable(false)
                .background {
                    if isSelected {
                        RoundedRectangle(cornerRadius: 6, style: .continuous)
                            .fill(Color(nsColor: .controlBackgroundColor).opacity(0.88))
                            .shadow(color: Color.black.opacity(0.10), radius: 2, x: 0, y: 1)
                            .overlay(
                                RoundedRectangle(cornerRadius: 6, style: .continuous)
                                    .stroke(Color.primary.opacity(0.12), lineWidth: 0.5)
                            )
                            .matchedGeometryEffect(id: "ActivePeriodPill", in: animationNamespace)
                    }
                }
            }
        }
        .padding(3)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color(nsColor: .controlColor).opacity(0.42))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .stroke(Color.primary.opacity(0.08), lineWidth: 0.5)
                )
        )
    }
}

// MARK: – Server & Machine Icons

struct ServerIcon: View {
    let platform: String?
    let title: String
    let size: CGFloat

    init(platform: String?, title: String, size: CGFloat = 24) {
        self.platform = platform
        self.title = title
        self.size = size
    }

    private var iconConfig: (name: String, tint: Color, background: Color) {
        let p = (platform ?? "").lowercased()
        let t = title.lowercased()

        if p == "darwin" || t.contains("mac") {
            return ("apple.logo", Color.primary.opacity(0.85), Color.primary.opacity(0.08))
        } else if t.contains("aws") || t.contains("cloud") || t.contains("ec2") {
            return ("cloud.fill", Color(red: 255 / 255, green: 153 / 255, blue: 0 / 255), Color.orange.opacity(0.12))
        } else if p == "linux" || t.contains("server") || t.contains("linux") || t.contains("gpu") || t.contains("tz") {
            return ("server.rack", Color(red: 70 / 255, green: 130 / 255, blue: 240 / 255), Color.blue.opacity(0.10))
        } else if p.contains("win") || t.contains("win") {
            return ("pc", Color.cyan, Color.cyan.opacity(0.10))
        } else {
            return ("server.rack", Color.secondary, Color.primary.opacity(0.06))
        }
    }

    var body: some View {
        let config = iconConfig
        ZStack {
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(config.background)
            Image(systemName: config.name)
                .font(.system(size: size * 0.54, weight: .medium))
                .foregroundStyle(config.tint)
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

// MARK: – BrandIcon & Model Logos

enum BrandKind: Equatable {
    case claudeCode
    case codex
    case gemini
    case deepseek
    case generic
}

struct BrandIcon: View {
    let kind: BrandKind
    let size: CGFloat

    static func kind(for raw: String, agent: String = "") -> BrandKind {
        let modelLower = raw.lowercased()
        if modelLower.contains("deepseek") { return .deepseek }
        if modelLower.contains("claude") { return .claudeCode }
        if modelLower.contains("codex") || modelLower.contains("openai") || modelLower.contains("gpt") || modelLower.contains("o1") || modelLower.contains("o3") { return .codex }
        if modelLower.contains("gemini") || modelLower.contains("google") || modelLower.contains("antigravity") { return .gemini }

        let agentLower = agent.lowercased()
        if agentLower.contains("claude") { return .claudeCode }
        if agentLower.contains("codex") { return .codex }
        if agentLower.contains("antigravity") || agentLower.contains("gemini") { return .gemini }
        return .generic
    }

    var body: some View {
        Group {
            switch kind {
            case .claudeCode:
                ClaudeCodeLogo()
                    .fill(Color(red: 218 / 255, green: 119 / 255, blue: 86 / 255))
                    .frame(width: size, height: size)
            case .codex:
                CodexLogo()
                    .fill(Color(red: 10 / 255, green: 132 / 255, blue: 1.0))
                    .frame(width: size, height: size)
            case .deepseek:
                Image(systemName: "bolt.horizontal.fill")
                    .resizable()
                    .scaledToFit()
                    .foregroundStyle(Color.cyan)
                    .frame(width: size, height: size)
            case .gemini:
                Image(systemName: "sparkles")
                    .resizable()
                    .scaledToFit()
                    .foregroundStyle(Color.blue)
                    .frame(width: size, height: size)
            case .generic:
                Image(systemName: "cube.fill")
                    .resizable()
                    .scaledToFit()
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
