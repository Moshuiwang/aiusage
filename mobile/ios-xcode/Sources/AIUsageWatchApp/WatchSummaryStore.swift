#if os(watchOS)
import Foundation

enum WatchSummaryStore {
    static let appGroupIdentifier = "group.com.wangzhipeng.aiusage.watch"
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
        guard summary.period.id == "today" else {
            return
        }
        let target = url(fileManager: fileManager)
        try? fileManager.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
        guard let data = try? JSONEncoder.watchSummaryCache.encode(summary) else {
            return
        }
        try? data.write(to: target, options: [.atomic])
    }

    private static func url(fileManager: FileManager) -> URL {
        if let directory = fileManager.containerURL(forSecurityApplicationGroupIdentifier: appGroupIdentifier) {
            return directory.appendingPathComponent(fileName)
        }
        return fileManager.temporaryDirectory.appendingPathComponent(fileName)
    }
}

struct WatchMobileSummary: Codable, Equatable {
    let generatedAt: String?
    let timezone: String?
    let period: WatchPeriod
    let trend: WatchTrend
    let breakdown: WatchBreakdown
    let limits: WatchLimits
    let sources: [WatchSource]

    enum CodingKeys: String, CodingKey {
        case generatedAt = "generated_at"
        case timezone
        case period
        case trend
        case breakdown
        case limits
        case sources
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.generatedAt = try container.decodeIfPresent(String.self, forKey: .generatedAt)
        self.timezone = try container.decodeIfPresent(String.self, forKey: .timezone)
        self.period = try container.decode(WatchPeriod.self, forKey: .period)
        self.trend = try container.decodeIfPresent(WatchTrend.self, forKey: .trend) ?? WatchTrend(points: [])
        self.breakdown = try container.decode(WatchBreakdown.self, forKey: .breakdown)
        self.limits = try container.decode(WatchLimits.self, forKey: .limits)
        self.sources = try container.decode([WatchSource].self, forKey: .sources)
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

struct WatchTrend: Codable, Equatable {
    let points: [WatchTrendPoint]
}

struct WatchTrendPoint: Codable, Equatable, Identifiable {
    var id: String { bucket }

    let bucket: String
    let label: String
    let tokens: Int
}

struct WatchLimits: Codable, Equatable {
    let windows: [WatchLimitWindow]
}

struct WatchLimitWindow: Codable, Equatable {
    let sourceID: String?
    let provider: String
    let window: String
    let usedPercentValue: Double?
    let remainingPercent: Double
    let windowDurationMinutes: Int?
    let confidence: String
    let status: String
    let official: Bool
    let resetAt: String?
    let accountLabel: String?
    let accountPlanLabel: String?

    enum CodingKeys: String, CodingKey {
        case sourceID = "source_id"
        case provider
        case window
        case usedPercentValue = "used_percent"
        case remainingPercent = "remaining_percent"
        case windowDurationMinutes = "window_duration_minutes"
        case confidence
        case status
        case official
        case resetAt = "reset_at"
        case accountLabel = "account_label"
        case accountPlanLabel = "account_plan_label"
    }

    var isOfficialObserved: Bool {
        official && confidence == "observed" && status == "ok"
    }

    var usedPercent: Int {
        let value = usedPercentValue ?? (100 - remainingPercent)
        return max(0, min(100, Int(value.rounded())))
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
        return shortDateTime(date)
    }

    static func resetText(_ value: String?) -> String {
        guard let value,
              let date = parse(value)
        else {
            return "reset --"
        }
        return "reset \(shortTime(date))"
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

    private static func shortDateTime(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MM/dd HH:mm"
        return formatter.string(from: date)
    }

    private static func shortTime(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm"
        return formatter.string(from: date)
    }
}

enum WatchSummaryDisplay {
    static func preferredCodexWindow(from summary: WatchMobileSummary) -> WatchLimitWindow? {
        summary.limits.windows
            .filter { $0.provider == "codex" && $0.isOfficialObserved }
            .sorted { $0.usedPercent > $1.usedPercent }
            .first
    }

    static func quotaText(from summary: WatchMobileSummary?) -> String {
        guard let summary else {
            return "--"
        }
        guard let window = preferredCodexWindow(from: summary) else {
            return "\(TokenFormat.compact(summary.period.totalTokens)) today"
        }
        return "\(window.usedPercent)% Codex"
    }

    static func resetText(from summary: WatchMobileSummary?) -> String {
        guard let summary else {
            return "reset --"
        }
        guard let window = preferredCodexWindow(from: summary) else {
            return "updated \(WatchSummaryFreshness.updatedText(summary))"
        }
        return WatchSummaryFreshness.resetText(window.resetAt)
    }

    static func circularText(from summary: WatchMobileSummary?) -> String {
        guard let summary,
              preferredCodexWindow(from: summary) != nil,
              !WatchSummaryFreshness.isStale(summary)
        else {
            return "--"
        }
        return "\(preferredCodexWindow(from: summary)?.usedPercent ?? 0)"
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

private extension JSONEncoder {
    static var watchSummaryCache: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }
}
#endif
