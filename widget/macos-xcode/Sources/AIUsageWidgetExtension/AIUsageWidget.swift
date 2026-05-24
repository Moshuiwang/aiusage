import AIUsageWidgetCore
import SwiftUI
import WidgetKit

struct AIUsageEntry: TimelineEntry {
    let date: Date
    let loadState: SnapshotLoadState
    let path: String
}

struct AIUsageProvider: TimelineProvider {
    func placeholder(in context: Context) -> AIUsageEntry {
        AIUsageEntry(date: Date(), loadState: .ready(Self.placeholderSnapshot), path: SnapshotLoader.defaultPath())
    }

    func getSnapshot(in context: Context, completion: @escaping (AIUsageEntry) -> Void) {
        completion(loadEntry())
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<AIUsageEntry>) -> Void) {
        let entry = loadEntry()
        let nextRefresh = Calendar.current.date(byAdding: .minute, value: 15, to: Date()) ?? Date()
        completion(Timeline(entries: [entry], policy: .after(nextRefresh)))
    }

    private func loadEntry() -> AIUsageEntry {
        let loader = SnapshotLoader(path: SnapshotLoader.defaultPath())
        return AIUsageEntry(date: Date(), loadState: loader.load(), path: loader.path)
    }

    private static let placeholderSnapshot = LatestSnapshot(
        generatedAt: "2026-05-22T13:03:51+08:00",
        timezone: "Asia/Shanghai",
        items: [
            UsageItem(
                machine: "macbook",
                account: "local",
                agent: "all",
                date: "2026-05-22",
                inputTokens: 1_972_563,
                outputTokens: 135_613,
                cacheCreationTokens: 0,
                cacheReadTokens: 14_484_608,
                totalTokens: 16_592_784
            )
        ],
        sourceStatus: [
            SourceStatus(sourceID: "mac-local", status: "ok", errorType: nil, message: nil),
            SourceStatus(sourceID: "linux-wang", status: "ok", errorType: nil, message: nil),
            SourceStatus(sourceID: "linux-ubuntu", status: "ok", errorType: nil, message: nil)
        ]
    )
}

struct AIUsageWidgetEntryView: View {
    let entry: AIUsageEntry
    @Environment(\.widgetFamily) private var family

    var body: some View {
        WidgetContentView(loadState: entry.loadState, family: family)
            .containerBackground(.background, for: .widget)
    }
}

struct WidgetContentView: View {
    let loadState: SnapshotLoadState
    let family: WidgetFamily

    var body: some View {
        switch loadState {
        case .missing:
            WidgetEmptyView(title: "无快照", detail: "请先同步 latest.json")
        case .unreadable:
            WidgetEmptyView(title: "数据不可读", detail: "latest.json 解析失败")
        case .ready(let snapshot):
            let summary = UsageSummaryBuilder.build(from: snapshot)
            switch family {
            case .systemMedium:
                MediumUsageWidget(summary: summary)
            default:
                LargeUsageWidget(summary: summary)
            }
        }
    }
}

struct MediumUsageWidget: View {
    let summary: UsageSummary

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text("AI Usage")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(TokenFormat.compact(summary.totalTokens))
                    .font(.system(size: 34, weight: .semibold, design: .rounded))
                    .minimumScaleFactor(0.75)
                    .lineLimit(1)
                Text("\(TokenFormat.full(summary.totalTokens)) tokens")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.75)
                Spacer(minLength: 0)
                SourceBadge(summary: summary)
            }
            VStack(alignment: .leading, spacing: 7) {
                CompactGroup(title: "机器", rows: Array(summary.machineTotals.prefix(3)))
                CompactGroup(title: "用户", rows: Array(summary.accountTotals.prefix(3)))
            }
        }
        .padding(14)
    }
}

struct LargeUsageWidget: View {
    let summary: UsageSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 3) {
                    Text("AI Usage")
                        .font(.headline)
                    Text(summary.today)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                SourceBadge(summary: summary)
            }

            VStack(alignment: .leading, spacing: 3) {
                Text(TokenFormat.compact(summary.totalTokens))
                    .font(.system(size: 40, weight: .semibold, design: .rounded))
                    .minimumScaleFactor(0.75)
                    .lineLimit(1)
                Text("\(TokenFormat.full(summary.totalTokens)) tokens today")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Divider()

            CompactGroup(title: "机器", rows: Array(summary.machineTotals.prefix(3)))
            CompactGroup(title: "OS 用户", rows: Array(summary.accountTotals.prefix(3)))
            CompactGroup(title: "Agent", rows: Array(summary.agentTotals.prefix(2)))
        }
        .padding(16)
    }
}

struct CompactGroup: View {
    let title: String
    let rows: [GroupTotal]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .font(.caption2.weight(.medium))
                .foregroundStyle(.secondary)
            if rows.isEmpty {
                Text("暂无今日数据")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                ForEach(rows) { row in
                    HStack(spacing: 8) {
                        Text(row.name)
                            .font(.caption)
                            .lineLimit(1)
                            .minimumScaleFactor(0.75)
                        Spacer(minLength: 4)
                        Text(TokenFormat.compact(row.totalTokens))
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
            }
        }
    }
}

struct SourceBadge: View {
    let summary: UsageSummary

    var body: some View {
        if summary.failedSources.isEmpty {
            Label("\(summary.okSourceCount)/\(summary.totalSourceCount)", systemImage: "checkmark.circle.fill")
                .font(.caption2)
                .foregroundStyle(.green)
                .labelStyle(.titleAndIcon)
                .lineLimit(1)
        } else {
            Label("\(summary.failedSources.count)", systemImage: "exclamationmark.triangle.fill")
                .font(.caption2)
                .foregroundStyle(.orange)
                .labelStyle(.titleAndIcon)
                .lineLimit(1)
        }
    }
}

struct WidgetEmptyView: View {
    let title: String
    let detail: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Image(systemName: "chart.bar.xaxis")
                .font(.title2)
                .foregroundStyle(.secondary)
            Text(title)
                .font(.headline)
                .lineLimit(1)
            Text(detail)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            Spacer(minLength: 0)
        }
        .padding(16)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

struct AIUsageWidget: Widget {
    let kind = "AIUsageWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: AIUsageProvider()) { entry in
            AIUsageWidgetEntryView(entry: entry)
        }
        .configurationDisplayName("AI Usage")
        .description("今日 AI coding agent token 使用量。")
        .supportedFamilies([.systemMedium, .systemLarge])
        .contentMarginsDisabled()
    }
}

@main
struct AIUsageWidgetBundle: WidgetBundle {
    var body: some Widget {
        AIUsageWidget()
    }
}
