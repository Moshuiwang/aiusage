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
        // #177 第三轮真机反馈：三列强制等宽（约 101pt/列）时圆环右侧留给文字的空间不够放
        // 「Antigravity」，之前把名称/倒计时整个挪到圆环下方——偏离设计稿（圆环在左、
        // 名称+倒计时在右）。改回设计稿版式：每项按自身内容的自然宽度排布，项之间用
        // Spacer 均分剩余空间，不再强制等宽。
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(rings.enumerated()), id: \.element.id) { index, ring in
                MenuBarQuotaRingItem(data: ring, hoveredID: $hoveredQuotaID)
                if index < rings.count - 1 {
                    Spacer(minLength: 6)
                }
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
        // #177 第三轮真机反馈：回到设计稿版式——圆环在左，名称 + 倒计时在右侧纵排。
        // 名称 11pt semibold 一行完整显示，不缩放/不截断；容器（MenuBarQuotaSectionView）
        // 已改成按内容自然宽度 + Spacer 均分布局，不再有等宽列挤压这一行的空间。
        HStack(alignment: .center, spacing: 6) {
            ring
            VStack(alignment: .leading, spacing: 1) {
                Text(data.displayName)
                    .font(.system(size: 11, weight: .semibold))
                    .lineLimit(1)
                    .fixedSize()
                Text(data.isAvailable ? data.resetCountdownText : "暂不可用")
                    .font(.system(size: 10.5))
                    .foregroundStyle(Color(nsColor: .secondaryLabelColor))
                    .lineLimit(1)
                    .fixedSize()
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
