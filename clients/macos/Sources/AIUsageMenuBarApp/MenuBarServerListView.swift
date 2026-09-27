import AIUsageMenuBarCore
import SwiftUI

/// #177：Server 卡片列表——中性配色，展开显示按 Agent 色点区分的模型明细。
/// #177 第四轮真机反馈：展开状态改成集合（允许多张同时展开），并持久化到 UserDefaults
/// （见 `ServerExpansionState`）——下次打开面板保持上次的展开状态；首次（无存量）默认全部收起。
/// #177 第四轮 Opus 审查：`ServerExpansionState` 的 API 面上没有「按当前 cards 集合清理」的
/// 入口，切换所选期间（cards 随之变化）不会影响已展开的 id，避免上一轮「切期再切回展开状态被
/// 冲掉」的 bug。
struct MenuBarServerListView: View {
    let cards: [MenuServerCard]
    let quotaHeader: String
    @StateObject private var expansion: ServerExpansionState

    init(cards: [MenuServerCard], quotaHeader: String, defaults: UserDefaults = .standard) {
        self.cards = cards
        self.quotaHeader = quotaHeader
        _expansion = StateObject(wrappedValue: ServerExpansionState(defaults: defaults))
    }

    var body: some View {
        VStack(spacing: 8) {
            ForEach(cards) { card in
                MenuBarServerCardView(
                    card: card,
                    quotaHeader: quotaHeader,
                    isExpanded: expansion.isExpanded(card.id),
                    onToggle: { expansion.toggle(card.id) }
                )
            }
        }
    }
}

private struct MenuBarServerCardView: View {
    let card: MenuServerCard
    let quotaHeader: String
    let isExpanded: Bool
    let onToggle: () -> Void
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        Button(action: onToggle) {
            VStack(alignment: .leading, spacing: 9) {
                header
                if isExpanded {
                    expandedContent
                        // #177 第四轮 Opus 审查：只让内容本身的透明度带自己的动画曲线，不用
                        // withAnimation 包裹 onToggle——withAnimation 会让这个 VStack 的高度变化
                        // （布局）也参与动画，而 popover 窗口尺寸是即时跳变的（上一轮为性能关掉了
                        // NSPopover 的尺寸动画），两者时间线不一致就会显得卡片/下方卡片位置跟着抖动。
                        .transition(.opacity.animation(.easeOut(duration: 0.15)))
                }
            }
            .padding(12)
        }
        .buttonStyle(.hoverHighlight(RoundedRectangle(cornerRadius: 16, style: .continuous)))
        .focusable(false)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color(nsColor: .windowBackgroundColor).opacity(0.55))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(Color.primary.opacity(0.07), lineWidth: 0.5)
        )
    }

    private var header: some View {
        HStack(spacing: 10) {
            ServerIcon(platform: card.platform, title: card.title, size: 30)
            VStack(alignment: .leading, spacing: 1) {
                Text(card.title)
                    .font(.system(size: 13, weight: .semibold))
                    .lineLimit(1)
                Text(card.subtitle)
                    .font(.system(size: 11))
                    .foregroundStyle(Color(nsColor: .secondaryLabelColor))
                    .lineLimit(1)
            }
            Spacer(minLength: 8)
            VStack(alignment: .trailing, spacing: 1) {
                Text(card.valueText)
                    .font(.system(size: 14, weight: .semibold).monospacedDigit())
                Text(card.sharePercentText)
                    .font(.system(size: 10.5))
                    .foregroundStyle(Color(nsColor: .secondaryLabelColor))
            }
            Image(systemName: "chevron.right")
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(Color(nsColor: .tertiaryLabelColor))
                .rotationEffect(.degrees(isExpanded ? 90 : 0))
                // 只让箭头旋转这一个纯视觉属性动画——不影响布局，尊重「减少动态效果」。
                .animation(reduceMotion ? nil : .easeOut(duration: 0.15), value: isExpanded)
        }
    }

    private var expandedContent: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 8) {
                Text("模型").frame(maxWidth: .infinity, alignment: .leading)
                Text("用量")
                Text(quotaHeader).frame(width: 92, alignment: .trailing)
            }
            .font(.system(size: 10))
            .foregroundStyle(Color(nsColor: .tertiaryLabelColor))
            .padding(.leading, 15)

            if card.models.isEmpty {
                Text("暂无模型明细")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(card.models) { model in
                    HStack(spacing: 8) {
                        Circle()
                            .fill(Color(red: model.agentBrandColor.red, green: model.agentBrandColor.green, blue: model.agentBrandColor.blue, opacity: model.agentBrandColor.opacity))
                            .frame(width: 7, height: 7)
                        Text(model.modelLabel)
                            .lineLimit(1)
                            .truncationMode(.tail)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .foregroundStyle(Color(nsColor: .labelColor).opacity(0.85))
                        Text(model.valueText)
                            .fontWeight(.medium)
                            .monospacedDigit()
                        Text(model.quotaText)
                            .font(.system(size: 11))
                            .foregroundStyle(Color(nsColor: .secondaryLabelColor))
                            .frame(width: 92, alignment: .trailing)
                    }
                    .font(.system(size: 12))
                }
            }
        }
        .padding(.leading, 40)
    }
}
