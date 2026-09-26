import AIUsageMenuBarCore
import SwiftUI

/// #177：额度条容器——横排若干个额度环。
/// 性能第二步：hoveredQuotaID 下沉到本容器自己持有，Popover 顶层不再持有悬停状态。
struct MenuBarQuotaSectionView: View {
    let rings: [QuotaRingData]
    @State private var hoveredQuotaID: String?
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    var body: some View {
        HStack(alignment: .top, spacing: 6) {
            ForEach(rings) { ring in
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

    private var cardBackground: some ShapeStyle {
        Color(nsColor: .windowBackgroundColor).opacity(reduceTransparency || contrast == .increased ? 1 : 0.55)
    }
}

/// #177：单环额度条——46pt 圆环，线宽 5，轨道 = 品牌色 16%，中心百分数；
/// 不可用时同色虚线圆环 + "—" + "暂不可用"。悬停展示 7 天 / 5 小时两个窗口（用 .popover 呈现，
/// 不与后方兄弟视图共用一层 zIndex，避免被截断/遮挡）。
struct MenuBarQuotaRingItem: View {
    let data: QuotaRingData
    @Binding var hoveredID: String?

    private var isHovered: Bool { hoveredID == data.id }

    private var brandColor: Color {
        Color(red: data.brandColor.red, green: data.brandColor.green, blue: data.brandColor.blue, opacity: data.brandColor.opacity)
    }

    var body: some View {
        // #177 真机反馈：三列等宽时圆环右侧空间放不下「Antigravity」会被截成「Antigra…」——
        // 名称/倒计时改放到圆环下方居中，三家统一布局，不再依赖圆环右侧的窄列宽度。
        VStack(spacing: 3) {
            ring
            VStack(spacing: 1) {
                Text(data.displayName)
                    .font(.system(size: 10.5, weight: .semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.85)
                    .allowsTightening(true)
                    .kerning(-0.2)
                Text(data.isAvailable ? data.resetCountdownText : "暂不可用")
                    .font(.system(size: 10))
                    .foregroundStyle(Color(nsColor: .secondaryLabelColor))
                    .lineLimit(1)
            }
        }
        // #177 真机反馈：悬停不能改变布局（之前 vertical padding 随悬停变化会让整体下沉 ~1pt）——
        // 悬停只改背景色，不改几何尺寸。
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(isHovered ? Color.primary.opacity(0.05) : Color.clear)
        )
        .onHover { isHovering in
            hoveredID = isHovering ? data.id : (hoveredID == data.id ? nil : hoveredID)
        }
        .popover(isPresented: Binding(
            get: { hoveredID == data.id },
            set: { if !$0, hoveredID == data.id { hoveredID = nil } }
        ), arrowEdge: .bottom) {
            MenuBarQuotaTooltip(data: data)
        }
    }

    @ViewBuilder
    private var ring: some View {
        ZStack {
            if data.isAvailable {
                Circle().stroke(brandColor.opacity(0.16), lineWidth: 5)
                Circle()
                    .trim(from: 0, to: CGFloat(min(max(data.primaryFraction, 0), 1)))
                    .stroke(brandColor, style: StrokeStyle(lineWidth: 5, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                // #177 Opus 审查：primaryPctText 已经带 %（例如 "26%"），不能再拼一次 Text("%")
                // 拼出「26%%」——中心数字用不带 % 的 primaryPctNumberText，只拼一次单独字号的 %。
                (Text(data.primaryPctNumberText).font(.system(size: 11.5, weight: .semibold))
                    + Text("%").font(.system(size: 8.5, weight: .semibold)))
                    .monospacedDigit()
                    .foregroundStyle(.primary)
            } else {
                Circle().stroke(brandColor.opacity(0.55), style: StrokeStyle(lineWidth: 2, dash: [3, 4]))
                Text("—")
                    .font(.system(size: 12))
                    .foregroundStyle(Color(nsColor: .tertiaryLabelColor))
            }
        }
        .frame(width: 46, height: 46)
    }
}

/// #177：额度条悬停浮层——只渲染 ViewModel 提供的 hoverRows，isAvailable=false 时
/// ViewModel 已经保证 hoverRows 不含任何百分比（不泄露「最近成功值」残留的旧数字）。
struct MenuBarQuotaTooltip: View {
    let data: QuotaRingData

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(data.displayName).font(.system(size: 12, weight: .semibold))
            ForEach(data.hoverRows) { row in
                HStack(alignment: .top, spacing: 8) {
                    Text(row.label)
                        .font(.system(size: 11.5))
                        .foregroundStyle(Color(nsColor: .secondaryLabelColor))
                        .frame(minWidth: 32, alignment: .leading)
                    Text(row.valueText)
                        .font(.system(size: 11.5, weight: .semibold).monospacedDigit())
                        .lineLimit(2)
                }
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .frame(minWidth: 190, alignment: .leading)
    }
}
