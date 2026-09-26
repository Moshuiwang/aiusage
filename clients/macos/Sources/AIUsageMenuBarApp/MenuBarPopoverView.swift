import AIUsageMenuBarCore
import AppKit
import SwiftUI

struct MenuBarPopoverView: View {
    @ObservedObject var model: MenuBarAppModel
    var onQuit: (() -> Void)?
    var onMore: (() -> Void)?
    @State private var periodMenuOpen = false
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    init(
        model: MenuBarAppModel,
        onQuit: (() -> Void)? = nil,
        onMore: (() -> Void)? = nil
    ) {
        self.model = model
        self.onQuit = onQuit
        self.onMore = onMore
    }

    private var maxContentHeight: CGFloat {
        MenuBarPopoverLayout.maxContentHeight(screenHeight: NSScreen.main?.visibleFrame.height)
    }

    // 性能第二步：改用 NSHostingController.sizingOptions = [.preferredContentSize]（由
    // StatusBarController 设置）让 Popover 跟随 SwiftUI 内容的理想尺寸，不再手工测量/回报高度。
    // `ScrollView { content }.frame(maxHeight: maxContentHeight)` 在向 SwiftUI 询问「理想尺寸」
    // （height 提议为 nil）时会先报告内容自身的自然高度——内容比 maxContentHeight 矮就直接贴合，
    // 不留空白；只有内容超过 maxContentHeight 才会被这个 frame 夹到 maxContentHeight 并允许滚动。
    // 实测过 ViewThatFits(先裸内容、超限才落回 ScrollView) 在真实内容（多 Server 卡片）逼近
    // maxContentHeight 边界时不会被外层 frame(maxHeight:) 夹住（量出 935pt，上限 875pt）——
    // 换成单一 ScrollView + frame(maxHeight:) 后同样场景稳定夹在上限内，见测试。
    var body: some View {
        VStack(spacing: 0) {
            header
            if !model.hasConfig {
                setupState
            } else {
                ScrollView {
                    mainContent
                }
                .frame(maxHeight: maxContentHeight)
            }
        }
        .frame(width: MenuBarPopoverLayout.width)
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
                model.syncNow()
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
                MenuBarQuotaSectionView(rings: model.state.quotaRings)
            }

            if model.hasLoadedUsableSummary {
                MenuBarUsageSectionView(model: model, periodMenuOpen: $periodMenuOpen)
            } else {
                Text(model.isLoading ? "正在读取所选日期…" : "所选日期暂无可用数据")
                    .font(.callout).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, minHeight: 80)
            }

            if !model.state.serverCards.isEmpty {
                MenuBarServerListView(cards: model.state.serverCards, quotaHeader: model.state.serverModelQuotaHeader)
            }
        }
        .padding(.horizontal, 10)
        .padding(.bottom, 12)
    }

    // MARK: – Helpers

    private var secondaryTextColor: Color {
        Color(nsColor: .secondaryLabelColor)
    }
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
