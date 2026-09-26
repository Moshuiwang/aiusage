import AIUsageMenuBarCore
import SwiftUI

/// #177：Server 卡片列表——中性配色，展开显示按 Agent 色点区分的模型明细。
/// 性能第二步：expandedServerID 下沉到本视图自己持有，Popover 顶层不再持有展开状态。
struct MenuBarServerListView: View {
    let cards: [MenuServerCard]
    let quotaHeader: String
    @State private var expandedServerID: String?

    var body: some View {
        VStack(spacing: 8) {
            ForEach(cards) { card in
                MenuBarServerCardView(
                    card: card,
                    quotaHeader: quotaHeader,
                    isExpanded: expandedServerID == card.id,
                    onToggle: {
                        expandedServerID = expandedServerID == card.id ? nil : card.id
                    }
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

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            Button(action: onToggle) {
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
                }
            }
            .buttonStyle(.plain)
            .focusable(false)

            if isExpanded {
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
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color(nsColor: .windowBackgroundColor).opacity(0.55))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(Color.primary.opacity(0.07), lineWidth: 0.5)
        )
    }
}
