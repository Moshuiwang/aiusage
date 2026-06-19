import Foundation
import SwiftUI

public struct WidgetSummaryState: Equatable, Sendable {
    public let primaryText: String
    public let secondaryText: String
    public let statusText: String
    public let periodText: String
    public let updatedText: String
    public let status: WidgetStatus
    public let usesObservedLimit: Bool
}

public enum WidgetStatus: String, Equatable, Sendable {
    case ok
    case stale
    case issue
}

public enum WidgetSummaryBuilder {
    public static func build(from summary: MobileSummary, now: Date = Date()) -> WidgetSummaryState {
        let failedSources = summary.sources.filter { $0.status != "ok" && $0.status != "disabled" && $0.status != "stale" }
        let staleSources = summary.sources.filter { $0.status == "stale" }

        let status: WidgetStatus
        let statusText: String
        if !MobileSummaryCache.isCompanionEligible(summary) {
            status = .issue
            statusText = "非今日缓存"
        } else if MobileSummaryCache.isStale(summary, now: now) {
            status = .stale
            statusText = "缓存过期"
        } else if !failedSources.isEmpty {
            status = .issue
            statusText = "\(failedSources.count) source issue"
        } else if !staleSources.isEmpty {
            status = .stale
            statusText = "\(staleSources.count) stale source"
        } else {
            status = .ok
            statusText = "\(summary.sources.filter { $0.status == "ok" }.count)/\(summary.sources.count) sources"
        }

        return WidgetSummaryState(
            primaryText: TokenFormat.compact(summary.period.totalTokens),
            secondaryText: [
                "Input \(TokenFormat.compact(summary.period.inputTokens))",
                "Output \(TokenFormat.compact(summary.period.outputTokens))",
                "Cache \(TokenFormat.compact(summary.period.cacheTokens))"
            ].joined(separator: " · "),
            statusText: statusText,
            periodText: periodText(for: summary.period.id),
            updatedText: MobileSummaryCache.formattedGeneratedAt(summary.generatedAt),
            status: status,
            usesObservedLimit: false
        )
    }

    private static func periodText(for periodID: String) -> String {
        switch periodID {
        case "today":
            return "Today"
        case "week":
            return "Week"
        case "month":
            return "Month"
        case "all":
            return "All"
        default:
            return periodID
        }
    }
}

public struct AIUsageSmallWidgetContentView: View {
    private let state: WidgetSummaryState

    public init(state: WidgetSummaryState) {
        self.state = state
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 7) {
                AIUsageBrandMark(size: 22)
                Text("AI Usage")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                Text(state.periodText)
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
            VStack(alignment: .leading, spacing: 4) {
                Text(state.primaryText)
                    .font(.system(size: 44, weight: .bold))
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.62)
                statusBadge
            }
        }
        .padding(14)
    }

    private var statusBadge: some View {
        Text(state.statusText)
            .font(.system(size: 11, weight: .semibold))
            .foregroundStyle(statusColor)
            .lineLimit(1)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(statusColor.opacity(0.12), in: RoundedRectangle(cornerRadius: 5, style: .continuous))
    }

    private var statusColor: Color {
        switch state.status {
        case .ok:
            return .green
        case .stale:
            return .orange
        case .issue:
            return .red
        }
    }
}

public struct AIUsageMediumWidgetContentView: View {
    private let state: WidgetSummaryState
    private let summary: MobileSummary

    public init(state: WidgetSummaryState, summary: MobileSummary) {
        self.state = state
        self.summary = summary
    }

    public var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 7) {
                    AIUsageBrandMark(size: 22)
                    Text("AI Usage")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
                HStack(alignment: .lastTextBaseline, spacing: 7) {
                    Text(state.primaryText)
                        .font(.system(size: 36, weight: .bold))
                        .monospacedDigit()
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                    statusDot
                }
                Text(shortBreakdown)
                    .font(.system(size: 10.5))
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                Text(statusLine)
                    .font(.system(size: 10.5, weight: .semibold))
                    .foregroundStyle(statusColor)
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            WidgetMiniBarChart(points: summary.trend.points, height: 78)
                .frame(width: 148)
        }
        .padding(14)
    }

    private var statusDot: some View {
        Circle()
            .fill(statusColor)
            .frame(width: 8, height: 8)
    }

    private var statusColor: Color {
        switch state.status {
        case .ok:
            return .green
        case .stale:
            return .orange
        case .issue:
            return .red
        }
    }

    private var shortBreakdown: String {
        "\(state.periodText) · Input \(TokenFormat.compact(summary.period.inputTokens)) · Output \(TokenFormat.compact(summary.period.outputTokens))"
    }

    private var statusLine: String {
        "\(state.statusText) · \(state.updatedText)"
    }
}

public struct AIUsageLargeWidgetContentView: View {
    private let state: WidgetSummaryState
    private let summary: MobileSummary

    public init(state: WidgetSummaryState, summary: MobileSummary) {
        self.state = state
        self.summary = summary
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 7) {
                AIUsageBrandMark(size: 22)
                Text("AI Usage")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                Text(state.updatedText)
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            HStack(alignment: .lastTextBaseline, spacing: 8) {
                Text(state.primaryText)
                    .font(.system(size: 38, weight: .bold))
                    .monospacedDigit()
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                Text(state.statusText)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(statusColor)
                    .lineLimit(1)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(statusColor.opacity(0.12), in: RoundedRectangle(cornerRadius: 5, style: .continuous))
            }

            Text(state.secondaryText)
                .font(.system(size: 10.5))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .minimumScaleFactor(0.72)

            WidgetMiniBarChart(points: summary.trend.points, height: 44)
                .frame(height: 58)

            WidgetQuotaRings(windows: summary.limits.windows)
                .frame(height: 102)

            Divider()
            VStack(spacing: 5) {
                ForEach(summary.breakdown.byMachine.prefix(2)) { source in
                    HStack {
                        VStack(alignment: .leading, spacing: 1) {
                            Text(source.label)
                                .font(.system(size: 11))
                                .lineLimit(1)
                            Text(sourceSubtitle(for: source))
                                .font(.system(size: 10))
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text(TokenFormat.compact(source.tokens))
                            .font(.system(size: 13, weight: .bold))
                            .monospacedDigit()
                    }
                }
            }
        }
        .padding(14)
    }

    private func sourceSubtitle(for source: MobileBreakdownRow) -> String {
        let label = source.label.lowercased()
        let platform: String
        if label.contains("win") {
            platform = "Windows"
        } else if label.contains("linux") || label.contains("ubuntu") {
            platform = "Linux"
        } else if label.contains("mac") || label.contains("mba") || label.contains("mbp") {
            platform = "macOS"
        } else {
            platform = "Source"
        }
        return "\(platform) · live"
    }

    private var statusColor: Color {
        switch state.status {
        case .ok:
            return .green
        case .stale:
            return .orange
        case .issue:
            return .red
        }
    }
}

private struct WidgetMiniBarChart: View {
    let points: [MobileTrendPoint]
    let height: CGFloat

    var body: some View {
        VStack(spacing: 4) {
            ZStack(alignment: .top) {
                Rectangle()
                    .stroke(style: StrokeStyle(lineWidth: 0.6, dash: [3, 3]))
                    .foregroundStyle(Color.secondary.opacity(0.18))
                    .frame(height: 1)
                HStack(alignment: .bottom, spacing: 2) {
                    ForEach(displayPoints) { point in
                        RoundedRectangle(cornerRadius: 2, style: .continuous)
                            .fill(LinearGradient(colors: [Color(red: 74 / 255, green: 158 / 255, blue: 1), Color(red: 0 / 255, green: 122 / 255, blue: 1)], startPoint: .top, endPoint: .bottom))
                            .frame(height: max(2, height * ratio(for: point)))
                            .frame(maxWidth: .infinity, alignment: .bottom)
                    }
                }
                .frame(height: height, alignment: .bottom)
            }
            HStack {
                Text("00")
                Spacer()
                Text("12")
                Spacer()
                Text("23")
            }
            .font(.system(size: 8))
            .foregroundStyle(.secondary)
        }
    }

    private var displayPoints: [MobileTrendPoint] {
        if points.isEmpty {
            return [MobileTrendPoint(bucket: "empty", label: "", tokens: 0, inputTokens: 0, outputTokens: 0, cacheTokens: 0, cacheRatio: 0)]
        }
        return Array(points.suffix(24))
    }

    private var maxTokens: Int {
        max(displayPoints.map(\.tokens).max() ?? 0, 1)
    }

    private func ratio(for point: MobileTrendPoint) -> CGFloat {
        CGFloat(point.tokens) / CGFloat(maxTokens)
    }
}

private struct WidgetQuotaRings: View {
    let windows: [MobileLimitWindow]

    var body: some View {
        HStack(spacing: 0) {
            WidgetQuotaRingItem(
                title: "Claude",
                outer: best(provider: "claude", window: "session"),
                inner: best(provider: "claude", window: "week"),
                outerColor: Color(red: 218 / 255, green: 119 / 255, blue: 86 / 255),
                innerColor: Color(red: 234 / 255, green: 168 / 255, blue: 130 / 255)
            )
            Divider()
            WidgetQuotaRingItem(
                title: "OpenAI",
                outer: best(provider: "codex", window: "session"),
                inner: best(provider: "codex", window: "week"),
                outerColor: Color(red: 10 / 255, green: 132 / 255, blue: 1),
                innerColor: Color(red: 90 / 255, green: 200 / 255, blue: 250 / 255)
            )
        }
    }

    private func best(provider: String, window: String) -> MobileLimitWindow? {
        windows
            .filter { $0.provider.lowercased().contains(provider) || (provider == "codex" && $0.provider.lowercased().contains("openai")) }
            .filter { window == "session" ? $0.window == "session" : $0.window == "week" || $0.window == "weekly" }
            .filter(\.isOfficialObserved)
            .sorted { $0.remainingPercent < $1.remainingPercent }
            .first
    }
}

private struct WidgetQuotaRingItem: View {
    let title: String
    let outer: MobileLimitWindow?
    let inner: MobileLimitWindow?
    let outerColor: Color
    let innerColor: Color

    var body: some View {
        VStack(spacing: 3) {
            ZStack {
                Circle()
                    .stroke(Color.primary.opacity(0.08), lineWidth: 10)
                    .frame(width: 78, height: 78)
                Circle()
                    .trim(from: 0, to: CGFloat((outer?.usedPercent ?? 0) / 100))
                    .stroke(outerColor, style: StrokeStyle(lineWidth: 10, lineCap: .round))
                    .frame(width: 78, height: 78)
                    .rotationEffect(.degrees(-90))
                Circle()
                    .stroke(Color.primary.opacity(0.08), lineWidth: 8)
                    .frame(width: 52, height: 52)
                Circle()
                    .trim(from: 0, to: CGFloat((inner?.usedPercent ?? 0) / 100))
                    .stroke(innerColor, style: StrokeStyle(lineWidth: 8, lineCap: .round))
                    .frame(width: 52, height: 52)
                    .rotationEffect(.degrees(-90))
                Text(title)
                    .font(.system(size: 10, weight: .bold))
            }
            Text("\(percent(outer)) · \(percent(inner))")
                .font(.system(size: 9.5))
                .foregroundStyle(outerColor)
                .monospacedDigit()
        }
        .frame(maxWidth: .infinity)
    }

    private func percent(_ window: MobileLimitWindow?) -> String {
        window.map { "\(Int($0.usedPercent.rounded()))%" } ?? "--"
    }
}
