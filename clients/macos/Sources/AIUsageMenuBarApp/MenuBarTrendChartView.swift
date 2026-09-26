import AIUsageMenuBarCore
import SwiftUI

/// #177：按 Agent 堆叠的趋势柱状图——顶部虚线参考线 + 最大值标签，悬停联动图例。
struct MenuBarTrendChartView: View {
    let bars: [MenuTrendBar]
    let legendTotals: [MenuTrendSegment]
    let ceilingFraction: Double
    let ceilingText: String
    @Binding var hoveredBar: MenuTrendBar?
    @Binding var hoverLocation: CGPoint?

    private let chartHeight: CGFloat = 92

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            GeometryReader { geo in
                ZStack(alignment: .top) {
                    Canvas { ctx, size in
                        var path = Path()
                        var x: CGFloat = 4
                        while x < size.width {
                            path.move(to: CGPoint(x: x, y: 0.5))
                            path.addLine(to: CGPoint(x: min(x + 3, size.width), y: 0.5))
                            x += 5
                        }
                        ctx.stroke(path, with: .color(Color.primary.opacity(0.16)), lineWidth: 1)
                    }
                    .frame(height: 1)

                    Text(ceilingText)
                        .font(.system(size: 9.5))
                        .foregroundStyle(Color(nsColor: .tertiaryLabelColor))
                        .frame(maxWidth: .infinity, alignment: .trailing)
                        .offset(y: -9)

                    HStack(alignment: .bottom, spacing: 4) {
                        ForEach(bars) { bar in
                            // #177 真机反馈：删除柱子上方的系统 .help 小浮层——它会被 Popover 右边缘截断，
                            // 且下方图例 legendRow 已经联动显示该柱的时间与数值，浮层是多余的重复展示。
                            stackedBar(bar)
                                .frame(maxWidth: .infinity)
                                .opacity(dimmed(bar) ? 0.4 : 1)
                        }
                    }
                    .frame(height: chartHeight, alignment: .bottom)
                }
                .frame(height: chartHeight, alignment: .top)
                .contentShape(Rectangle())
                .onContinuousHover { phase in
                    switch phase {
                    case .active(let loc):
                        hoverLocation = loc
                        hoveredBar = MenuTrendSelection.nearestBar(in: bars, xLocation: Double(loc.x), width: Double(geo.size.width))
                    case .ended:
                        hoveredBar = nil; hoverLocation = nil
                    }
                }
            }
            .frame(height: chartHeight)

            HStack {
                ForEach(bars.filter { !$0.label.isEmpty }) { bar in
                    Text(bar.label)
                        .font(.system(size: 9, weight: .medium))
                        .foregroundStyle(Color(nsColor: .tertiaryLabelColor))
                        .frame(maxWidth: .infinity)
                }
            }
            .frame(height: 12)

            legendRow
        }
    }

    private func dimmed(_ bar: MenuTrendBar) -> Bool {
        guard let hoveredBar else { return false }
        return hoveredBar.id != bar.id
    }

    @ViewBuilder
    private func stackedBar(_ bar: MenuTrendBar) -> some View {
        if bar.isFuture {
            RoundedRectangle(cornerRadius: 2)
                .fill(Color.primary.opacity(0.12))
                .frame(height: 4)
        } else if bar.totalTokens == 0 || bar.segments.isEmpty {
            RoundedRectangle(cornerRadius: 3)
                .fill(Color.primary.opacity(0.10))
                .frame(height: 4)
        } else {
            let height = max(4, chartHeight * CGFloat(bar.ratio * max(ceilingFraction, 0.05)))
            VStack(spacing: 0) {
                // segments 自底向上排列，VStack 自顶向下绘制，反转后 Claude 在底。
                ForEach(bar.segments.reversed()) { segment in
                    Rectangle().fill(providerColor(segment.provider))
                        .frame(height: height * CGFloat(segment.fraction))
                }
            }
            .frame(height: height, alignment: .bottom)
            .clipShape(RoundedRectangle(cornerRadius: 3, style: .continuous))
        }
    }

    private var legendRow: some View {
        // #177 真机反馈：「Claude」「Antigravity」之前会在图例里被折成两行——名称/数值一律
        // lineLimit(1) 禁止折行，空间不足时靠 ViewThatFits 整体降级到更小字号，不允许单词断行。
        ViewThatFits(in: .horizontal) {
            legendContent(nameSize: 11, valueSize: 11)
            legendContent(nameSize: 10, valueSize: 10)
            legendContent(nameSize: 9, valueSize: 9)
        }
        .frame(minHeight: 16)
    }

    private func legendContent(nameSize: CGFloat, valueSize: CGFloat) -> some View {
        HStack(spacing: 12) {
            Text(hoveredBar.map { $0.isFuture ? "合计" : $0.tooltipTitle } ?? "合计")
                .font(.system(size: 11, weight: .semibold))
                .lineLimit(1)
            let activeSegments = (hoveredBar.flatMap { $0.isFuture ? nil : $0.segments }) ?? legendTotals
            // 图例只展示三个固定 Agent；unknown 段仍参与堆叠配色，但不占图例位。
            ForEach(MenuTrendProvider.allCases.filter { $0 != .unknown }, id: \.rawValue) { provider in
                HStack(spacing: 5) {
                    Circle().fill(providerColor(provider)).frame(width: 7, height: 7)
                    Text(provider.displayName)
                        .font(.system(size: nameSize))
                        .lineLimit(1)
                        .fixedSize(horizontal: true, vertical: false)
                    Text(valueText(for: provider, in: activeSegments))
                        .font(.system(size: valueSize))
                        .foregroundStyle(Color(nsColor: .secondaryLabelColor))
                        .lineLimit(1)
                        .fixedSize(horizontal: true, vertical: false)
                }
            }
        }
    }

    private func valueText(for provider: MenuTrendProvider, in segments: [MenuTrendSegment]) -> String {
        guard let segment = segments.first(where: { $0.provider == provider }), segment.tokens > 0 else {
            return "—"
        }
        return TokenFormat.compact(segment.tokens)
    }

    private func providerColor(_ provider: MenuTrendProvider) -> Color {
        let c = provider.color
        return Color(red: c.red, green: c.green, blue: c.blue, opacity: c.opacity)
    }
}
