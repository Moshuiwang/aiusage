import AIUsageMenuBarCore
import AppKit
import SwiftUI

struct MenuBarPopoverView: View {
    @ObservedObject var model: MenuBarAppModel
    @State private var selectedTab: MenuTab = .overview
    @State private var hoveredTrend: MenuTrendBar?
    @State private var trendHoverLocation: CGPoint?

    private let periods: [(String, String)] = [
        ("today", "今天"),
        ("week", "本周"),
        ("month", "本月"),
        ("all", "全部"),
    ]

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [
                    Color(nsColor: .windowBackgroundColor),
                    Color(nsColor: .controlBackgroundColor).opacity(0.86),
                ],
                startPoint: .top,
                endPoint: .bottom
            )
            VStack(spacing: 0) {
                header
                if !model.hasConfig {
                    setupState
                } else {
                    content
                }
            }
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            Image(systemName: "chart.bar.xaxis")
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(.white)
                .frame(width: 30, height: 30)
                .background(Color.blue)
                .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
            VStack(alignment: .leading, spacing: 3) {
                Text("AI Usage")
                    .font(.system(size: 15, weight: .semibold))
                Text("生产摘要 · \(model.state.lastUpdatedText)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            if model.isLoading {
                ProgressView()
                    .controlSize(.small)
            }
            Button {
                model.refresh()
            } label: {
                Image(systemName: "arrow.clockwise")
                    .frame(width: 24, height: 24)
            }
            .buttonStyle(.borderless)
            .help("刷新")
            Button {
                if let url = model.dashboardURL {
                    NSWorkspace.shared.open(url)
                }
            } label: {
                Image(systemName: "safari")
                    .frame(width: 24, height: 24)
            }
            .buttonStyle(.borderless)
            .help("打开 Dashboard")
            Button {
                NSApplication.shared.terminate(nil)
            } label: {
                Image(systemName: "xmark.circle")
                    .frame(width: 24, height: 24)
            }
            .buttonStyle(.borderless)
            .help("退出")
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
    }

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

    private var content: some View {
        VStack(spacing: 12) {
            if let error = model.errorMessage {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.caption)
                    .foregroundStyle(.orange)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 14)
                    .padding(.top, 8)
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

            Picker("视图", selection: $selectedTab) {
                ForEach(MenuTab.allCases) { tab in
                    Label(tab.title, systemImage: tab.symbol).tag(tab)
                }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, 16)

            ScrollView {
                VStack(spacing: 12) {
                    switch selectedTab {
                    case .overview:
                        overviewTab
                    case .limits:
                        rowsSection(title: "额度窗口", rows: model.state.limitRows)
                    case .sources:
                        rowsSection(title: "采集来源", rows: model.state.sources)
                    case .breakdown:
                        breakdownTab
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 16)
            }
        }
        .onChange(of: model.state.trendBars) { _, _ in
            hoveredTrend = nil
            trendHoverLocation = nil
        }
    }

    private var overviewHero: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Text(model.state.periodLabel)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.blue)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color.blue.opacity(0.10))
                    .clipShape(Capsule())
                Spacer()
                Label(model.state.healthText, systemImage: model.state.healthText.contains("异常") ? "exclamationmark.triangle.fill" : "checkmark.seal.fill")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(model.state.healthText.contains("异常") ? .orange : .green)
                    .lineLimit(1)
            }
            Text(model.state.heroTotalText)
                .font(.system(size: 38, weight: .semibold, design: .rounded))
                .monospacedDigit()
                .lineLimit(1)
                .minimumScaleFactor(0.7)
                .frame(maxWidth: .infinity, alignment: .leading)
            Text(model.state.tokenBreakdownText)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
            HStack(spacing: 6) {
                Image(systemName: "gauge.with.dots.needle.33percent")
                    .font(.caption.weight(.semibold))
                Text(model.state.primaryLimitText)
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
            }
            .foregroundStyle(.primary)
            .padding(.horizontal, 9)
            .padding(.vertical, 6)
            .background(Color(nsColor: .windowBackgroundColor).opacity(0.78))
            .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
            trend
        }
        .padding(16)
        .background(heroBackground)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Color.primary.opacity(0.07), lineWidth: 1)
        )
        .padding(.horizontal, 16)
    }

    private var trend: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack {
                Text("趋势")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer()
            }
            GeometryReader { proxy in
                ZStack(alignment: .topLeading) {
                    VStack(spacing: 0) {
                        HStack(alignment: .bottom, spacing: 4) {
                            ForEach(model.state.trendBars) { bar in
                                RoundedRectangle(cornerRadius: 3)
                                    .fill(Color.blue.gradient)
                                    .frame(maxWidth: 16)
                                    .frame(height: max(6, 48 * bar.ratio))
                                    .frame(maxWidth: .infinity, alignment: .bottom)
                                    .help("\(bar.tooltipTitle) · \(bar.valueText)")
                            }
                        }
                        .frame(height: 52, alignment: .bottom)

                        axisLabelLayer(width: proxy.size.width)
                            .frame(height: 14)
                    }

                    if let hoveredTrend, let trendHoverLocation {
                        Rectangle()
                            .fill(Color.blue.opacity(0.22))
                            .frame(width: 1, height: 52)
                            .position(x: trendHoverLocation.x, y: 26)
                        trendTooltip(hoveredTrend)
                            .position(x: tooltipX(trendHoverLocation.x, width: proxy.size.width), y: 18)
                    }
                }
                .contentShape(Rectangle())
                .onContinuousHover { phase in
                    switch phase {
                    case .active(let location):
                        updateTrendHover(location: location, width: proxy.size.width)
                    case .ended:
                        hoveredTrend = nil
                        trendHoverLocation = nil
                    }
                }
                .gesture(
                    DragGesture(minimumDistance: 0)
                        .onChanged { value in
                            updateTrendHover(location: value.location, width: proxy.size.width)
                        }
                        .onEnded { _ in
                            hoveredTrend = nil
                            trendHoverLocation = nil
                        }
                )
            }
            .frame(height: 66)
        }
        .frame(height: 80)
    }

    private func updateTrendHover(location: CGPoint, width: CGFloat) {
        trendHoverLocation = location
        hoveredTrend = MenuTrendSelection.nearestBar(
            in: model.state.trendBars,
            xLocation: Double(location.x),
            width: Double(width)
        )
    }

    private func axisLabelLayer(width: CGFloat) -> some View {
        ZStack(alignment: .topLeading) {
            ForEach(Array(model.state.trendBars.enumerated()), id: \.element.id) { index, bar in
                if !bar.label.isEmpty {
                    Text(bar.label)
                        .font(.system(size: 9, weight: .medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .frame(width: 46, height: 12)
                        .position(x: labelX(index: index, count: model.state.trendBars.count, width: width), y: 7)
                }
            }
        }
    }

    private func trendTooltip(_ bar: MenuTrendBar) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(bar.tooltipTitle)
                .font(.system(size: 10, weight: .semibold))
            Text(bar.valueText)
                .font(.system(size: 11, weight: .semibold, design: .rounded).monospacedDigit())
        }
        .foregroundStyle(.primary)
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
        .background(Color(nsColor: .windowBackgroundColor).opacity(0.94))
        .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 7, style: .continuous)
                .stroke(Color.primary.opacity(0.10), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.12), radius: 8, x: 0, y: 3)
    }

    private func labelX(index: Int, count: Int, width: CGFloat) -> CGFloat {
        guard count > 1 else {
            return width / 2
        }
        let raw = CGFloat(index) / CGFloat(count - 1) * width
        return min(max(raw, 23), max(width - 23, 23))
    }

    private func tooltipX(_ x: CGFloat, width: CGFloat) -> CGFloat {
        min(max(x, 48), max(width - 48, 48))
    }

    private var overviewTab: some View {
        VStack(spacing: 12) {
            rowsSection(title: "主要来源", rows: Array(model.state.sources.prefix(4)))
            rowsSection(title: "额度", rows: Array(model.state.limitRows.prefix(4)))
        }
    }

    private var breakdownTab: some View {
        VStack(spacing: 12) {
            ForEach(model.state.breakdownSections) { section in
                rowsSection(title: section.title, rows: section.rows)
            }
        }
    }

    private func rowsSection(title: String, rows: [MenuDisplayRow]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(.subheadline.weight(.semibold))
            if rows.isEmpty {
                Text("暂无数据")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(10)
            } else {
                ForEach(rows) { row in
                    rowView(row)
                }
            }
        }
        .padding(12)
        .background(sectionBackground)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Color.primary.opacity(0.06), lineWidth: 1)
        )
    }

    private func rowView(_ row: MenuDisplayRow) -> some View {
        HStack(spacing: 10) {
            Image(systemName: row.status == "ok" ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(statusColor(row.status))
                .frame(width: 16)
            VStack(alignment: .leading, spacing: 2) {
                Text(row.title)
                    .font(.system(size: 13, weight: .medium))
                    .lineLimit(1)
                if !row.subtitle.isEmpty {
                    Text(row.subtitle)
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
            Spacer()
            Text(row.value)
                .font(.system(size: 12, weight: .semibold, design: .rounded).monospacedDigit())
                .foregroundStyle(.primary.opacity(0.72))
                .lineLimit(1)
        }
        .frame(minHeight: 34)
    }

    private var heroBackground: some ShapeStyle {
        LinearGradient(
            colors: [
                Color(nsColor: .windowBackgroundColor).opacity(0.94),
                Color.blue.opacity(0.08),
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    private var sectionBackground: some ShapeStyle {
        Color(nsColor: .windowBackgroundColor).opacity(0.82)
    }

    private func statusColor(_ status: String) -> Color {
        switch status {
        case "ok":
            return .green
        case "missing", "disabled":
            return .secondary
        default:
            return .orange
        }
    }
}

private enum MenuTab: String, CaseIterable, Identifiable {
    case overview
    case limits
    case sources
    case breakdown

    var id: String { rawValue }

    var title: String {
        switch self {
        case .overview:
            return "概览"
        case .limits:
            return "额度"
        case .sources:
            return "来源"
        case .breakdown:
            return "明细"
        }
    }

    var symbol: String {
        switch self {
        case .overview:
            return "square.grid.2x2"
        case .limits:
            return "gauge.with.dots.needle.33percent"
        case .sources:
            return "antenna.radiowaves.left.and.right"
        case .breakdown:
            return "chart.bar"
        }
    }
}
