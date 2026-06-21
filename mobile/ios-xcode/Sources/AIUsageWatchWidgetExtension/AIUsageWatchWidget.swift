#if os(watchOS)
import SwiftUI
import WidgetKit

struct AIUsageWatchWidgetEntry: TimelineEntry {
    let date: Date
    let summary: WatchMobileSummary?
}

struct AIUsageWatchWidgetProvider: TimelineProvider {
    func placeholder(in context: Context) -> AIUsageWatchWidgetEntry {
        AIUsageWatchWidgetEntry(date: Date(), summary: WatchSummaryStore.read())
    }

    func getSnapshot(in context: Context, completion: @escaping (AIUsageWatchWidgetEntry) -> Void) {
        completion(AIUsageWatchWidgetEntry(date: Date(), summary: WatchSummaryStore.read()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<AIUsageWatchWidgetEntry>) -> Void) {
        let entry = AIUsageWatchWidgetEntry(date: Date(), summary: WatchSummaryStore.read())
        completion(Timeline(entries: [entry], policy: .after(Date().addingTimeInterval(15 * 60))))
    }
}

struct AIUsageWatchWidgetEntryView: View {
    @Environment(\.widgetFamily) private var family
    let entry: AIUsageWatchWidgetEntry

    var body: some View {
        Group {
            switch family {
            case .accessoryCircular:
                AIUsageCircularAccessory(summary: entry.summary)
            case .accessoryInline:
                AIUsageInlineAccessory(summary: entry.summary)
            default:
                AIUsageRectangularAccessory(summary: entry.summary)
            }
        }
        .containerBackground(.background, for: .widget)
    }
}

struct AIUsageRectangularAccessory: View {
    let summary: WatchMobileSummary?

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(statusTitle)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(WatchSummaryDisplay.quotaText(from: summary))
                .font(.headline.weight(.semibold))
                .minimumScaleFactor(0.72)
                .lineLimit(1)
            Text(WatchSummaryDisplay.resetText(from: summary))
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
    }

    private var statusTitle: String {
        guard let summary else {
            return "No Cache"
        }
        return WatchSummaryFreshness.isStale(summary) ? "Stale" : "AI Usage"
    }
}

struct AIUsageCircularAccessory: View {
    let summary: WatchMobileSummary?

    var body: some View {
        Gauge(value: Double(usedPercent), in: 0...100) {
            Text("AI")
        } currentValueLabel: {
            Text(WatchSummaryDisplay.circularText(from: summary))
                .font(.caption2.weight(.semibold))
        }
        .gaugeStyle(.accessoryCircularCapacity)
    }

    private var usedPercent: Int {
        guard let summary,
              let window = WatchSummaryDisplay.preferredCodexWindow(from: summary),
              !WatchSummaryFreshness.isStale(summary)
        else {
            return 0
        }
        return window.usedPercent
    }
}

struct AIUsageInlineAccessory: View {
    let summary: WatchMobileSummary?

    var body: some View {
        Text(text)
    }

    private var text: String {
        guard let summary else {
            return "AI Usage no cache"
        }
        if WatchSummaryFreshness.isStale(summary) {
            return "AI Usage stale"
        }
        return WatchSummaryDisplay.quotaText(from: summary)
    }
}

struct AIUsageWatchWidget: Widget {
    let kind = "AIUsageWatchWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: AIUsageWatchWidgetProvider()) { entry in
            AIUsageWatchWidgetEntryView(entry: entry)
        }
        .configurationDisplayName("AI Usage")
        .description("查看 Codex 额度和 reset time。")
        .supportedFamilies([.accessoryRectangular, .accessoryCircular, .accessoryInline])
    }
}

@main
struct AIUsageWatchWidgetBundle: WidgetBundle {
    var body: some Widget {
        AIUsageWatchWidget()
    }
}
#endif
