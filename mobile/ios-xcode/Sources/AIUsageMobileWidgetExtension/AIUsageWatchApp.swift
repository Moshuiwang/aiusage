#if os(watchOS)
import Foundation
import SwiftUI
import WatchConnectivity

@main
struct AIUsageWatchApp: App {
    @StateObject private var model = WatchSummaryModel()

    var body: some Scene {
        WindowGroup {
            AIUsageWatchSummaryView(summary: model.summary)
        }
    }
}

final class WatchSummaryModel: NSObject, ObservableObject, WCSessionDelegate, @unchecked Sendable {
    @Published var summary: WatchMobileSummary?

    override init() {
        self.summary = WatchSummaryStore.read()
        super.init()
        activateSession()
    }

    private func activateSession() {
        guard WCSession.isSupported() else {
            return
        }
        let session = WCSession.default
        session.delegate = self
        session.activate()
        apply(applicationContext: session.receivedApplicationContext)
    }

    func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        apply(applicationContext: session.receivedApplicationContext)
    }

    func session(
        _ session: WCSession,
        didReceiveApplicationContext applicationContext: [String: Any]
    ) {
        apply(applicationContext: applicationContext)
    }

    private func apply(applicationContext: [String: Any]) {
        guard let data = applicationContext["mobileSummary"] as? Data,
              let decoded = try? JSONDecoder().decode(WatchMobileSummary.self, from: data)
        else {
            return
        }
        guard decoded.period.id == "today" else {
            return
        }
        WatchSummaryStore.write(decoded)
        DispatchQueue.main.async {
            self.summary = decoded
        }
    }
}

enum WatchSummaryStore {
    static let fileName = "last-watch-summary.json"

    static func read(fileManager: FileManager = .default) -> WatchMobileSummary? {
        guard let data = try? Data(contentsOf: url(fileManager: fileManager)) else {
            return nil
        }
        guard let summary = try? JSONDecoder().decode(WatchMobileSummary.self, from: data),
              summary.period.id == "today"
        else {
            return nil
        }
        return summary
    }

    static func write(_ summary: WatchMobileSummary, fileManager: FileManager = .default) {
        let target = url(fileManager: fileManager)
        try? fileManager.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        guard let data = try? JSONEncoder().encode(summary) else {
            return
        }
        try? data.write(to: target, options: [.atomic])
    }

    private static func url(fileManager: FileManager) -> URL {
        let directory = (try? fileManager.url(for: .cachesDirectory, in: .userDomainMask, appropriateFor: nil, create: true))
            ?? fileManager.temporaryDirectory
        return directory.appendingPathComponent(fileName)
    }
}

struct WatchMobileSummary: Codable, Equatable {
    let generatedAt: String?
    let timezone: String?
    let period: WatchPeriod
    let breakdown: WatchBreakdown
    let limits: WatchLimits
    let sources: [WatchSource]

    enum CodingKeys: String, CodingKey {
        case generatedAt = "generated_at"
        case timezone
        case period
        case breakdown
        case limits
        case sources
    }
}

struct WatchPeriod: Codable, Equatable {
    let id: String
    let totalTokens: Int
    let inputTokens: Int
    let outputTokens: Int
    let cacheTokens: Int
    let cacheRatio: Int

    enum CodingKeys: String, CodingKey {
        case id
        case totalTokens = "total_tokens"
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
        case cacheTokens = "cache_tokens"
        case cacheRatio = "cache_ratio"
    }
}

struct WatchBreakdown: Codable, Equatable {
    let byMachine: [WatchBreakdownRow]

    enum CodingKeys: String, CodingKey {
        case byMachine = "by_machine"
    }
}

struct WatchBreakdownRow: Codable, Equatable, Identifiable {
    let id: String
    let label: String
    let tokens: Int
}

struct WatchLimits: Codable, Equatable {
    let windows: [WatchLimitWindow]
}

struct WatchLimitWindow: Codable, Equatable {
    let provider: String
    let window: String
    let remainingPercent: Double
    let confidence: String
    let status: String
    let official: Bool

    enum CodingKeys: String, CodingKey {
        case provider
        case window
        case remainingPercent = "remaining_percent"
        case confidence
        case status
        case official
    }

    var isOfficialObserved: Bool {
        official && confidence == "observed" && status == "ok"
    }
}

struct WatchSource: Codable, Equatable {
    let status: String
}

enum WatchSummaryFreshness {
    static let maxAge: TimeInterval = 2 * 60 * 60

    static func isStale(_ summary: WatchMobileSummary, now: Date = Date()) -> Bool {
        guard let generatedAt = summary.generatedAt,
              let date = parse(generatedAt)
        else {
            return true
        }
        return now.timeIntervalSince(date) > maxAge
    }

    static func updatedText(_ summary: WatchMobileSummary) -> String {
        guard let generatedAt = summary.generatedAt,
              let date = parse(generatedAt)
        else {
            return "--"
        }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MM/dd HH:mm"
        return formatter.string(from: date)
    }

    private static func parse(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        if let date = formatter.date(from: value) {
            return date
        }
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: value)
    }
}

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

                if let limitText {
                    WatchMetricPill(title: "Quota", value: limitText)
                }

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

    private var limitText: String? {
        summary?.limits.windows
            .filter(\.isOfficialObserved)
            .sorted { $0.remainingPercent < $1.remainingPercent }
            .first
            .map { "\(Int($0.remainingPercent.rounded()))% \(providerLabel($0.provider))" }
    }

    private var sourceRows: [WatchBreakdownRow] {
        Array((summary?.breakdown.byMachine ?? []).prefix(4))
    }

    private func providerLabel(_ value: String) -> String {
        value.prefix(1).uppercased() + value.dropFirst()
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

enum TokenFormat {
    static func compact(_ value: Int) -> String {
        let double = Double(value)
        if value >= 1_000_000_000 {
            return String(format: "%.1fB", double / 1_000_000_000)
        }
        if value >= 1_000_000 {
            return String(format: "%.1fM", double / 1_000_000)
        }
        if value >= 1_000 {
            return String(format: "%.1fK", double / 1_000)
        }
        return "\(value)"
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
