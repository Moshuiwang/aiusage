import Foundation
import SwiftUI

public struct WidgetSummaryState: Equatable, Sendable {
    public let primaryText: String
    public let secondaryText: String
    public let statusText: String
    public let status: WidgetStatus
    public let usesObservedLimit: Bool
}

public enum WidgetStatus: String, Equatable, Sendable {
    case ok
    case stale
    case issue
}

public enum WidgetSummaryBuilder {
    public static func build(from summary: MobileSummary) -> WidgetSummaryState {
        let observedLimit = summary.limits.windows
            .filter { $0.confidence == "observed" && $0.official }
            .sorted {
                if $0.remainingPercent == $1.remainingPercent {
                    return $0.id.localizedStandardCompare($1.id) == .orderedAscending
                }
                return $0.remainingPercent < $1.remainingPercent
            }
            .first
        let failedSources = summary.sources.filter { $0.status != "ok" && $0.status != "disabled" }
        let staleSources = summary.sources.filter { $0.status == "stale" }

        let status: WidgetStatus
        let statusText: String
        if !failedSources.isEmpty {
            status = .issue
            statusText = "\(failedSources.count) source issue"
        } else if !staleSources.isEmpty {
            status = .stale
            statusText = "\(staleSources.count) stale source"
        } else {
            status = .ok
            statusText = "\(summary.sources.filter { $0.status == "ok" }.count)/\(summary.sources.count) sources"
        }

        if let observedLimit {
            return WidgetSummaryState(
                primaryText: "\(Int(observedLimit.remainingPercent.rounded()))%",
                secondaryText: "\(observedLimit.provider) \(observedLimit.window) left",
                statusText: statusText,
                status: status,
                usesObservedLimit: true
            )
        }

        return WidgetSummaryState(
            primaryText: TokenFormat.compact(summary.period.totalTokens),
            secondaryText: "\(summary.period.id) tokens",
            statusText: statusText,
            status: status,
            usesObservedLimit: false
        )
    }
}

public struct AIUsageSmallWidgetContentView: View {
    private let state: WidgetSummaryState

    public init(state: WidgetSummaryState) {
        self.state = state
    }

    public var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("AI Usage")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            Spacer(minLength: 0)
            Text(state.primaryText)
                .font(.system(size: 36, weight: .semibold, design: .rounded))
                .monospacedDigit()
                .minimumScaleFactor(0.7)
            Text(state.secondaryText)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            statusLabel
        }
        .padding()
    }

    private var statusLabel: some View {
        Label(state.statusText, systemImage: systemImage)
            .font(.caption2)
            .foregroundStyle(statusColor)
            .lineLimit(1)
    }

    private var systemImage: String {
        switch state.status {
        case .ok:
            return "checkmark.circle.fill"
        case .stale:
            return "clock.badge.exclamationmark"
        case .issue:
            return "exclamationmark.triangle.fill"
        }
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
    private let topSources: [MobileBreakdownRow]

    public init(state: WidgetSummaryState, topSources: [MobileBreakdownRow]) {
        self.state = state
        self.topSources = topSources
    }

    public var body: some View {
        HStack(alignment: .top, spacing: 18) {
            AIUsageSmallWidgetContentView(state: state)
                .padding(.trailing, 4)
            VStack(alignment: .leading, spacing: 8) {
                Text("Top Sources")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                ForEach(topSources.prefix(3)) { source in
                    HStack {
                        Text(source.label)
                            .font(.caption)
                            .lineLimit(1)
                        Spacer()
                        Text(TokenFormat.compact(source.tokens))
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.vertical)
            .padding(.trailing)
        }
    }
}
