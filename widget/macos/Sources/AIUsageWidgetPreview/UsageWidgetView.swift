import AIUsageWidgetCore
import SwiftUI

struct UsageWidgetContainer: View {
    let loadState: SnapshotLoadState
    let path: String

    var body: some View {
        switch loadState {
        case .missing:
            EmptyStateView(
                title: "无可用快照",
                detail: "未找到 data/latest.json",
                path: path
            )
        case .unreadable(let message):
            EmptyStateView(
                title: "数据不可读",
                detail: message,
                path: path
            )
        case .ready(let snapshot):
            UsageWidgetView(summary: UsageSummaryBuilder.build(from: snapshot))
        }
    }
}

struct UsageWidgetView: View {
    let summary: UsageSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            header
            totalBlock
            Divider()
            GroupSection(title: "机器", rows: summary.machineTotals)
            GroupSection(title: "OS 用户", rows: summary.accountTotals)
            GroupSection(title: "Agent", rows: summary.agentTotals)
            SourceStatusView(summary: summary)
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 4) {
                Text("AI Usage")
                    .font(.headline)
                Text(summary.today)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 4) {
                Text(summary.generatedAt ?? "采集时间未知")
                    .font(.caption2)
                    .foregroundStyle(summary.hasGeneratedAt ? Color.secondary : Color.orange)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Text("\(summary.okSourceCount)/\(summary.totalSourceCount) sources")
                    .font(.caption2)
                    .foregroundStyle(summary.failedSources.isEmpty ? Color.secondary : Color.orange)
            }
        }
    }

    private var totalBlock: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(TokenFormat.compact(summary.totalTokens))
                .font(.system(size: 44, weight: .semibold, design: .rounded))
                .contentTransition(.numericText())
            Text(summary.hasTodayData ? "\(TokenFormat.full(summary.totalTokens)) tokens today" : "今日暂无数据")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}

struct GroupSection: View {
    let title: String
    let rows: [GroupTotal]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            if rows.isEmpty {
                Text("暂无今日数据")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(rows.prefix(4)) { row in
                    HStack {
                        Text(row.name)
                            .font(.callout)
                            .lineLimit(1)
                        Spacer()
                        Text(TokenFormat.compact(row.totalTokens))
                            .font(.callout.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }
}

struct SourceStatusView: View {
    let summary: UsageSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Source")
                .font(.caption)
                .foregroundStyle(.secondary)
            if summary.failedSources.isEmpty {
                Label("全部采集成功", systemImage: "checkmark.circle.fill")
                    .font(.callout)
                    .foregroundStyle(.green)
            } else {
                ForEach(summary.failedSources.prefix(3)) { source in
                    Label {
                        Text("\(source.sourceID): \(source.errorType ?? source.status)")
                            .lineLimit(1)
                    } icon: {
                        Image(systemName: "exclamationmark.triangle.fill")
                    }
                    .font(.callout)
                    .foregroundStyle(.orange)
                }
            }
        }
    }
}

struct EmptyStateView: View {
    let title: String
    let detail: String
    let path: String

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("AI Usage")
                .font(.headline)
            Spacer()
            Image(systemName: "chart.bar.xaxis")
                .font(.system(size: 34))
                .foregroundStyle(.secondary)
            Text(title)
                .font(.title3.weight(.semibold))
            Text(detail)
                .font(.callout)
                .foregroundStyle(.secondary)
            Text(path)
                .font(.caption2.monospaced())
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .truncationMode(.middle)
            Spacer()
        }
        .padding(20)
        .frame(width: 420, height: 520, alignment: .leading)
        .background(Color(nsColor: .windowBackgroundColor))
    }
}
