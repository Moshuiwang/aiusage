import AIUsageMobileCore
import SwiftUI
import WidgetKit

struct AIUsageWidgetEntry: TimelineEntry {
    let date: Date
    let summary: MobileSummary
}

struct AIUsageWidgetProvider: TimelineProvider {
    func placeholder(in context: Context) -> AIUsageWidgetEntry {
        AIUsageWidgetEntry(date: Date(), summary: WidgetFixtureLoader.load())
    }

    func getSnapshot(in context: Context, completion: @escaping (AIUsageWidgetEntry) -> Void) {
        completion(AIUsageWidgetEntry(date: Date(), summary: WidgetFixtureLoader.load()))
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<AIUsageWidgetEntry>) -> Void) {
        let entry = AIUsageWidgetEntry(date: Date(), summary: WidgetFixtureLoader.load())
        completion(Timeline(entries: [entry], policy: .after(Date().addingTimeInterval(15 * 60))))
    }
}

struct AIUsageWidgetEntryView: View {
    @Environment(\.widgetFamily) private var family
    let entry: AIUsageWidgetEntry

    var body: some View {
        let state = WidgetSummaryBuilder.build(from: entry.summary)
        Group {
            if family == .systemMedium {
                AIUsageMediumWidgetContentView(
                    state: state,
                    topSources: entry.summary.breakdown.byMachine
                )
            } else {
                AIUsageSmallWidgetContentView(state: state)
            }
        }
        .containerBackground(.background, for: .widget)
    }
}

struct AIUsageMobileWidget: Widget {
    let kind = "AIUsageMobileWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: AIUsageWidgetProvider()) { entry in
            AIUsageWidgetEntryView(entry: entry)
        }
        .configurationDisplayName("AI Usage")
        .description("查看当前 AI usage 和额度状态。")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

@main
struct AIUsageMobileWidgetBundle: WidgetBundle {
    var body: some Widget {
        AIUsageMobileWidget()
    }
}

enum WidgetFixtureLoader {
    static func load(bundle: Bundle = .main) -> MobileSummary {
        guard let url = bundle.url(forResource: "mobile-summary", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let summary = try? JSONDecoder().decode(MobileSummary.self, from: data)
        else {
            return MobileSummaryFixture.empty
        }
        return summary
    }
}

enum MobileSummaryFixture {
    static let empty = MobileSummary(
        schemaVersion: 1,
        client: "ios",
        generatedAt: nil,
        timezone: "Asia/Shanghai",
        period: MobilePeriod(
            id: "today",
            date: nil,
            startDate: nil,
            endDate: nil,
            totalTokens: 0,
            inputTokens: 0,
            outputTokens: 0,
            cacheTokens: 0,
            cacheRatio: 0,
            machine: nil,
            account: nil
        ),
        trend: MobileTrend(period: "today", granularity: "hour", startDate: nil, endDate: nil, points: []),
        sources: [],
        breakdown: MobileBreakdown(byMachine: [], byOSUser: [], byAgent: [], byModel: [], byDate: []),
        limits: MobileLimits(observedCount: 0, totalCount: 0, windows: [])
    )
}
