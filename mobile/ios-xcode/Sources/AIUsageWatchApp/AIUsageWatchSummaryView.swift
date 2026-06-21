#if os(watchOS)
import SwiftUI

struct AIUsageWatchSummaryView: View {
    let summary: WatchMobileSummary?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    AIUsageBrandMark(size: 30)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("AI Usage")
                            .font(.headline.weight(.semibold))
                        Text(headerSubtitle)
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }

                VStack(alignment: .leading, spacing: 3) {
                    Text(periodLabel)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    Text(totalText)
                        .font(.title3.weight(.semibold))
                        .lineLimit(2)
                        .minimumScaleFactor(0.76)
                    Text(statusText)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }

                HStack(spacing: 6) {
                    WatchMetricPill(title: "Input", value: inputText)
                    WatchMetricPill(title: "Output", value: outputText)
                }

                WatchMetricPill(title: "Codex", value: quotaText)

                VStack(alignment: .leading, spacing: 6) {
                    ForEach(sourceRows) { row in
                        WatchSourceRow(name: row.label, state: TokenFormat.compact(row.tokens))
                    }
                }
            }
            .padding(.vertical, 8)
        }
        .containerBackground(for: .navigation) {
            Color.black
        }
    }

    private var periodLabel: String {
        summary == nil ? "No Cache" : "Today"
    }

    private var headerSubtitle: String {
        guard let summary else {
            return "等待手机同步"
        }
        let prefix = WatchSummaryFreshness.isStale(summary) ? "Stale" : "Updated"
        return "\(prefix) · \(updatedText)"
    }

    private var totalText: String {
        guard let summary else {
            return "等待手机同步"
        }
        return TokenFormat.compact(summary.period.totalTokens)
    }

    private var inputText: String {
        summary.map { TokenFormat.compact($0.period.inputTokens) } ?? "--"
    }

    private var outputText: String {
        summary.map { TokenFormat.compact($0.period.outputTokens) } ?? "--"
    }

    private var statusText: String {
        guard let summary else {
            return "打开 iPhone App 后会同步真实缓存。"
        }
        if WatchSummaryFreshness.isStale(summary) {
            return "Stale cache · open iPhone App"
        }
        let healthy = summary.sources.filter { $0.status == "ok" }.count
        return "\(healthy)/\(summary.sources.count) sources · \(summary.timezone ?? TimeZone.current.identifier)"
    }

    private var updatedText: String {
        summary.map { WatchSummaryFreshness.updatedText($0) } ?? "--"
    }

    private var quotaText: String {
        guard let summary else {
            return "--"
        }
        let quota = WatchSummaryDisplay.quotaText(from: summary)
        let reset = WatchSummaryDisplay.resetText(from: summary)
        return "\(quota) · \(reset)"
    }

    private var sourceRows: [WatchBreakdownRow] {
        Array((summary?.breakdown.byMachine ?? []).prefix(4))
    }
}

struct WatchMetricPill: View {
    let title: String
    let value: String

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title)
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(value)
                .font(.caption.weight(.semibold))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(7)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

struct WatchSourceRow: View {
    let name: String
    let state: String

    var body: some View {
        HStack {
            Text(name)
                .font(.caption)
                .lineLimit(1)
            Spacer()
            Text(state)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 3)
    }
}

struct AIUsageBrandMark: View {
    let size: CGFloat

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.22, style: .continuous)
                .fill(
                    RadialGradient(
                        colors: [
                            Color(red: 45 / 255, green: 49 / 255, blue: 72 / 255),
                            Color(red: 7 / 255, green: 9 / 255, blue: 16 / 255)
                        ],
                        center: UnitPoint(x: 0.34, y: 0.27),
                        startRadius: 0,
                        endRadius: size * 0.88
                    )
                )
            RingArc(startAngle: -96, endAngle: 157)
                .stroke(Color(red: 218 / 255, green: 119 / 255, blue: 86 / 255), style: StrokeStyle(lineWidth: size * 0.09, lineCap: .round))
                .frame(width: size * 0.70, height: size * 0.70)
            RingArc(startAngle: -90, endAngle: 124)
                .stroke(Color(red: 10 / 255, green: 132 / 255, blue: 1), style: StrokeStyle(lineWidth: size * 0.076, lineCap: .round))
                .frame(width: size * 0.38, height: size * 0.38)
            Circle()
                .fill(Color.white.opacity(0.84))
                .frame(width: size * 0.11, height: size * 0.11)
            Circle()
                .fill(Color(red: 10 / 255, green: 132 / 255, blue: 1))
                .frame(width: size * 0.035, height: size * 0.035)
        }
        .frame(width: size, height: size)
        .accessibilityLabel("AI Usage")
    }
}

private struct RingArc: Shape {
    let startAngle: Double
    let endAngle: Double

    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.addArc(
            center: CGPoint(x: rect.midX, y: rect.midY),
            radius: min(rect.width, rect.height) / 2,
            startAngle: .degrees(startAngle),
            endAngle: .degrees(endAngle),
            clockwise: false
        )
        return path
    }
}
#endif
