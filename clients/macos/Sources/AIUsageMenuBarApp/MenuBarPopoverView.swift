import AIUsageMenuBarCore
import AppKit
import SwiftUI

struct MenuBarPopoverView: View {
    @ObservedObject var model: MenuBarAppModel
    var onQuit: (() -> Void)?
    var onMore: (() -> Void)?
    var onContentHeightChange: (() -> Void)?
    @State private var contentHeight: CGFloat
    @State private var hoveredBar: MenuTrendBar?
    @State private var hoverLocation: CGPoint?
    @State private var hoveredQuotaID: String?
    @State private var periodMenuOpen = false
    @State private var expandedServerID: String?
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    init(
        model: MenuBarAppModel,
        onQuit: (() -> Void)? = nil,
        onMore: (() -> Void)? = nil,
        onContentHeightChange: (() -> Void)? = nil
    ) {
        self.model = model
        self.onQuit = onQuit
        self.onMore = onMore
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
        HStack(alignment: .center, spacing: 8) {
            VStack(alignment: .leading, spacing: 1) {
                Text("AI Usage")
                    .font(.system(size: 15, weight: .semibold))
                Text("\(model.state.headerUpdatedText) · \(model.state.onlineServerCount) 台 Server")
                    .font(.system(size: 11))
                    .foregroundStyle(secondaryTextColor)
            }
            Spacer(minLength: 4)
            glassCircleButton(systemName: "arrow.clockwise", help: "立即同步", accessibilityLabel: "立即同步", isBusy: model.isLoading) {
                model.refresh(force: true)
            }
            glassCircleButton(systemName: "ellipsis", help: "更多", accessibilityLabel: "更多") {
                onMore?()
            }
        }
        .padding(.leading, 18)
        .padding(.trailing, 12)
        .padding(.top, 14)
        .padding(.bottom, 12)
    }

    private func glassCircleButton(
        systemName: String,
        help: String,
        accessibilityLabel: String,
        isBusy: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.system(size: 12, weight: .medium))
                .rotationEffect(isBusy ? .degrees(360) : .degrees(0))
                .animation(isBusy ? .linear(duration: 0.9).repeatForever(autoreverses: false) : .default, value: isBusy)
                .frame(width: 28, height: 28)
        }
        .buttonStyle(.plain)
        .focusable(false)
        .disabled(isBusy && systemName == "arrow.clockwise")
        .background(
            Circle()
                .fill(Color(nsColor: .controlBackgroundColor).opacity(reduceTransparency ? 1 : 0.5))
                .overlay(Circle().stroke(Color.primary.opacity(0.12), lineWidth: 1))
        )
        .help(help)
        .accessibilityLabel(accessibilityLabel)
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
        VStack(spacing: 10) {
            if let error = model.errorMessage {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            if let coverage = model.state.providerUsageCoverageText {
                Label(coverage, systemImage: "info.circle.fill")
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }

            if !model.state.quotaRings.isEmpty {
                quotaSection
            }

            if model.hasLoadedUsableSummary {
                MenuBarUsageSectionView(
                    model: model,
                    periodMenuOpen: $periodMenuOpen,
                    hoveredBar: $hoveredBar,
                    hoverLocation: $hoverLocation
                )
            } else {
                Text(model.isLoading ? "正在读取所选日期…" : "所选日期暂无可用数据")
                    .font(.callout).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 80)
            }

            if !model.state.serverCards.isEmpty {
                MenuBarServerListView(cards: model.state.serverCards, quotaHeader: model.state.serverModelQuotaHeader, expandedServerID: $expandedServerID)
            }
        }
        .padding(.horizontal, 10)
        .padding(.bottom, 12)
        .onChange(of: model.state.trendBars) { _, _ in
            hoveredBar = nil; hoverLocation = nil
        }
    }

    // MARK: – Quota section

    private var quotaSection: some View {
        HStack(alignment: .top, spacing: 6) {
            ForEach(model.state.quotaRings) { ring in
                // #177 Opus 审查：悬停浮层改用原生 .popover（独立窗口），不再靠手工 overlay + zIndex
                // 定位——那样会被期间菜单等后方兄弟视图截断/遮挡。
                MenuBarQuotaRingItem(data: ring, hoveredID: $hoveredQuotaID)
                    .frame(maxWidth: .infinity)
            }
        }
        .padding(12)
        .background(cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(Color.primary.opacity(0.07), lineWidth: 0.5)
        )
    }

    // MARK: – Helpers

    private var cardBackground: some ShapeStyle {
        Color(nsColor: .windowBackgroundColor).opacity(reduceTransparency || contrast == .increased ? 1 : 0.55)
    }

    private var secondaryTextColor: Color {
        Color(nsColor: .secondaryLabelColor)
    }
}

struct PopoverContentHeight: PreferenceKey {
    static let defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = nextValue() }
}

struct PopoverGlassSurface: ViewModifier {
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
                content.glassEffect(.regular, in: RoundedRectangle(cornerRadius: 24, style: .continuous))
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

    /// #177：中性灰图标，只按平台/机型区分形状，不再用彩色区分 Server。
    private var symbolName: String {
        let p = (platform ?? "").lowercased()
        let t = title.lowercased()

        if p == "darwin" || t.contains("mac") || t.contains("macbook") {
            return "laptopcomputer"
        } else if t.contains("aws") || t.contains("cloud") || t.contains("ec2") || t.contains("gcp") || t.contains("azure") {
            return "cloud.fill"
        } else if p.contains("win") || t.contains("win") {
            return "pc"
        } else {
            return "server.rack"
        }
    }

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(Color.primary.opacity(0.08))
            Image(systemName: symbolName)
                .font(.system(size: size * 0.54, weight: .medium))
                .foregroundStyle(Color(nsColor: .tertiaryLabelColor))
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}
