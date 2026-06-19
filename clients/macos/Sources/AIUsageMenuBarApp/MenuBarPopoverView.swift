import AIUsageMenuBarCore
import AppKit
import SwiftUI

struct MenuBarPopoverView: View {
    @ObservedObject var model: MenuBarAppModel

    private let periods: [(String, String)] = [
        ("today", "今天"),
        ("week", "本周"),
        ("month", "本月"),
        ("all", "全部"),
    ]

    var body: some View {
        ZStack {
            VisualEffectView(material: .popover, blendingMode: .behindWindow)
            VStack(spacing: 0) {
                header
                if !model.hasConfig {
                    setupState
                } else {
                    content
                }
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private var header: some View {
        HStack(spacing: 12) {
            AIUsageBrandMark(size: 30)
            VStack(alignment: .leading, spacing: 2) {
                Text("AI Usage")
                    .font(.system(size: 15, weight: .semibold))
                Text(model.state.lastUpdatedText)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if model.isLoading {
                ProgressView()
                    .controlSize(.small)
            }
            iconButton("arrow.clockwise", help: "刷新") {
                model.refresh()
            }
            iconButton("safari", help: "打开 Dashboard") {
                if let url = model.dashboardURL {
                    NSWorkspace.shared.open(url)
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
    }

    private func iconButton(_ name: String, help: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: name)
                .font(.system(size: 13, weight: .semibold))
                .frame(width: 26, height: 26)
                .background(Color.primary.opacity(0.001))
                .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
        }
        .buttonStyle(.borderless)
        .help(help)
    }

    private var setupState: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("需要配置服务地址和访问 token", systemImage: "lock.shield")
                .font(.headline)
            Text(model.paths.configURL.path)
                .font(.system(.caption, design: .monospaced))
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
                .lineLimit(4)
            Text("配置后会只读生产摘要，不执行采集。")
                .font(.footnote)
                .foregroundStyle(.secondary)
            Spacer()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
    }

    private var content: some View {
        VStack(spacing: 10) {
            if let error = model.errorMessage {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 16)
            }

            Picker("周期", selection: $model.selectedPeriodID) {
                ForEach(periods, id: \.0) { id, label in
                    Text(label).tag(id)
                }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 16)
            .onChange(of: model.selectedPeriodID) { _, newValue in
                model.refresh(periodID: newValue)
            }

            overviewHero
            quotaSection
            sourcesSection
            Spacer(minLength: 0)
        }
    }

    private var overviewHero: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .lastTextBaseline, spacing: 8) {
                Text(model.state.heroTotalText)
                    .font(.system(size: 38, weight: .semibold))
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                Text(model.state.healthText)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(model.state.healthText.contains("异常") ? .red : .green)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 2)
                    .background((model.state.healthText.contains("异常") ? Color.red : Color.green).opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: 5, style: .continuous))
            }
            Text(model.state.tokenBreakdownText)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
            DashboardHandoffBarChart(bars: model.state.trendBars)
                .frame(height: 74)
        }
        .padding(14)
        .background(cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(Color.primary.opacity(0.07), lineWidth: 0.5)
        )
        .padding(.horizontal, 16)
    }

    private var quotaSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("额度")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
            QuotaRingPair(windows: model.summary.limits.windows)
        }
        .padding(12)
        .background(cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(Color.primary.opacity(0.06), lineWidth: 0.5)
        )
        .padding(.horizontal, 16)
    }

    private var sourcesSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("来源")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
            if model.summary.breakdown.byMachine.isEmpty {
                Text("暂无来源数据")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(model.summary.breakdown.byMachine.prefix(3)) { row in
                    HStack(spacing: 10) {
                        Circle()
                            .fill(Color.green)
                            .frame(width: 7, height: 7)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(row.label)
                                .font(.system(size: 13, weight: .medium))
                                .lineLimit(1)
                            Text(sourceSubtitle(for: row))
                                .font(.system(size: 11))
                                .foregroundStyle(.secondary)
                                .lineLimit(1)
                        }
                        Spacer()
                        Text(TokenFormat.compact(row.tokens))
                            .font(.system(size: 12, weight: .bold))
                            .monospacedDigit()
                    }
                    .padding(.vertical, 2)
                }
            }
        }
        .padding(12)
        .background(cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(Color.primary.opacity(0.06), lineWidth: 0.5)
        )
        .padding(.horizontal, 16)
        .padding(.bottom, 16)
    }

    private func sourceSubtitle(for row: MobileBreakdownRow) -> String {
        guard let count = row.sourceIDs?.count ?? row.contributions?.count, count > 0 else {
            return model.state.lastUpdatedText
        }
        return "\(count) 个来源 · \(model.state.lastUpdatedText)"
    }

    private var cardBackground: some ShapeStyle {
        Color(nsColor: .windowBackgroundColor).opacity(0.82)
    }
}

private struct DashboardHandoffBarChart: View {
    let bars: [MenuTrendBar]

    var body: some View {
        VStack(spacing: 5) {
            ZStack(alignment: .topTrailing) {
                Rectangle()
                    .stroke(style: StrokeStyle(lineWidth: 0.6, dash: [3, 3]))
                    .foregroundStyle(Color.secondary.opacity(0.18))
                    .frame(height: 1)
                Text(maxLabel)
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(.secondary.opacity(0.7))
                    .offset(y: -8)
                if bars.isEmpty {
                    HStack(alignment: .bottom, spacing: 4) {
                        ForEach(0..<12, id: \.self) { _ in
                            RoundedRectangle(cornerRadius: 3, style: .continuous)
                                .fill(Color.blue.opacity(0.18))
                                .frame(height: 4)
                                .frame(maxWidth: .infinity, alignment: .bottom)
                        }
                    }
                    .frame(height: 52, alignment: .bottom)
                } else {
                    HStack(alignment: .bottom, spacing: 4) {
                        ForEach(bars) { bar in
                            RoundedRectangle(cornerRadius: 3, style: .continuous)
                                .fill(Color.blue.gradient)
                                .frame(height: max(4, 52 * bar.ratio))
                                .frame(maxWidth: .infinity, alignment: .bottom)
                                .help("\(bar.tooltipTitle) · \(bar.valueText)")
                        }
                    }
                    .frame(height: 52, alignment: .bottom)
                }
            }
            HStack {
                ForEach(axisLabels, id: \.self) { label in
                    Text(label)
                        .font(.system(size: 9, weight: .medium))
                        .foregroundStyle(.secondary)
                    if label != axisLabels.last {
                        Spacer(minLength: 0)
                    }
                }
            }
        }
    }

    private var axisLabels: [String] {
        let labels = bars.map(\.label).filter { !$0.isEmpty }
        if labels.count >= 3 {
            return [labels.first ?? "", labels[labels.count / 2], labels.last ?? ""]
        }
        return labels.isEmpty ? ["00:00", "12:00", "23:59"] : labels
    }

    private var maxLabel: String {
        bars.map(\.valueText).first(where: { $0 != "0" }) ?? "0"
    }
}

private struct QuotaRingPair: View {
    let windows: [MobileLimitWindow]

    var body: some View {
        HStack(spacing: 0) {
            QuotaRingItem(
                title: "Claude",
                outer: best(provider: "claude", window: "session"),
                inner: best(provider: "claude", window: "week"),
                outerColor: Color(red: 218 / 255, green: 119 / 255, blue: 86 / 255),
                innerColor: Color(red: 234 / 255, green: 168 / 255, blue: 130 / 255)
            )
            Divider()
                .frame(height: 118)
                .padding(.horizontal, 6)
            QuotaRingItem(
                title: "OpenAI",
                outer: best(provider: "codex", window: "session"),
                inner: best(provider: "codex", window: "week"),
                outerColor: Color(red: 10 / 255, green: 132 / 255, blue: 1),
                innerColor: Color(red: 90 / 255, green: 200 / 255, blue: 250 / 255)
            )
        }
    }

    private func best(provider: String, window: String) -> MobileLimitWindow? {
        windows
            .filter { $0.provider.lowercased().contains(provider) || (provider == "codex" && $0.provider.lowercased().contains("openai")) }
            .filter { window == "session" ? $0.window == "session" : $0.window == "week" || $0.window == "weekly" }
            .filter(\.isOfficialObserved)
            .sorted { $0.remainingPercent < $1.remainingPercent }
            .first
    }
}

private struct QuotaRingItem: View {
    let title: String
    let outer: MobileLimitWindow?
    let inner: MobileLimitWindow?
    let outerColor: Color
    let innerColor: Color

    var body: some View {
        VStack(spacing: 6) {
            ZStack {
                Circle()
                    .stroke(Color.primary.opacity(0.08), lineWidth: 10)
                    .frame(width: 92, height: 92)
                Circle()
                    .trim(from: 0, to: CGFloat((outer?.usedPercent ?? 0) / 100))
                    .stroke(outerColor, style: StrokeStyle(lineWidth: 10, lineCap: .round))
                    .frame(width: 92, height: 92)
                    .rotationEffect(.degrees(-90))
                Circle()
                    .stroke(Color.primary.opacity(0.08), lineWidth: 9)
                    .frame(width: 60, height: 60)
                Circle()
                    .trim(from: 0, to: CGFloat((inner?.usedPercent ?? 0) / 100))
                    .stroke(innerColor, style: StrokeStyle(lineWidth: 9, lineCap: .round))
                    .frame(width: 60, height: 60)
                    .rotationEffect(.degrees(-90))
                Text(title)
                    .font(.system(size: 10, weight: .bold))
            }
            VStack(spacing: 3) {
                quotaRow("5h", outer, color: outerColor)
                quotaRow("7d", inner, color: innerColor)
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func quotaRow(_ label: String, _ window: MobileLimitWindow?, color: Color) -> some View {
        HStack(spacing: 5) {
            Text(label)
                .font(.system(size: 9.5, weight: .semibold))
                .foregroundStyle(color)
                .frame(width: 16, alignment: .leading)
            Text(window.map { "\(Int($0.usedPercent.rounded()))%" } ?? "--")
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(color)
                .frame(width: 32, alignment: .leading)
            Text(window.flatMap(resetText) ?? "无可信数据")
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
        }
    }

    private func resetText(_ window: MobileLimitWindow) -> String? {
        guard let resetAt = window.resetAt, resetAt.count >= 16 else {
            return nil
        }
        let timeStart = resetAt.index(resetAt.startIndex, offsetBy: 11)
        let timeEnd = resetAt.index(resetAt.startIndex, offsetBy: 16)
        return String(resetAt[timeStart..<timeEnd])
    }
}

private struct VisualEffectView: NSViewRepresentable {
    let material: NSVisualEffectView.Material
    let blendingMode: NSVisualEffectView.BlendingMode

    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = material
        view.blendingMode = blendingMode
        view.state = .active
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {
        nsView.material = material
        nsView.blendingMode = blendingMode
    }
}

private struct AIUsageBrandMark: View {
    let size: CGFloat

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.225, style: .continuous)
                .fill(
                    RadialGradient(
                        colors: [
                            Color(red: 30 / 255, green: 32 / 255, blue: 53 / 255),
                            Color(red: 12 / 255, green: 13 / 255, blue: 24 / 255),
                        ],
                        center: UnitPoint(x: 0.35, y: 0.30),
                        startRadius: 0,
                        endRadius: size * 0.74
                    )
                )

            Circle()
                .stroke(Color(red: 218 / 255, green: 119 / 255, blue: 86 / 255).opacity(0.18), lineWidth: size * 0.11)
                .frame(width: size * 0.76, height: size * 0.76)
            Circle()
                .trim(from: 0, to: 0.70)
                .stroke(Color(red: 218 / 255, green: 119 / 255, blue: 86 / 255), style: StrokeStyle(lineWidth: size * 0.11, lineCap: .round))
                .frame(width: size * 0.76, height: size * 0.76)
                .rotationEffect(.degrees(-90))

            Circle()
                .stroke(Color(red: 10 / 255, green: 132 / 255, blue: 1).opacity(0.18), lineWidth: size * 0.09)
                .frame(width: size * 0.40, height: size * 0.40)
            Circle()
                .trim(from: 0, to: 0.45)
                .stroke(Color(red: 10 / 255, green: 132 / 255, blue: 1), style: StrokeStyle(lineWidth: size * 0.09, lineCap: .round))
                .frame(width: size * 0.40, height: size * 0.40)
                .rotationEffect(.degrees(-90))

            Circle()
                .fill(Color.white.opacity(0.65))
                .frame(width: size * 0.07, height: size * 0.07)
        }
        .frame(width: size, height: size)
        .accessibilityLabel("AI Usage")
    }
}
