#if os(watchOS)
import Foundation

enum WatchSummaryStore {
    static let appGroupIdentifier = "group.com.wangzhipeng.aiusage.watch"
    static let fileName = "last-watch-summary.json"
    static let receiptFileName = "last-watch-cache-receipt.json"
    static let appGroupDirectoryPath = "Library/Caches"

    static func read(fileManager: FileManager = .default) -> WatchMobileSummary? {
        guard let summaryURL = url(fileName: fileName, fileManager: fileManager),
              let data = try? Data(contentsOf: summaryURL)
        else {
            return nil
        }
        guard let summary = try? JSONDecoder().decode(WatchMobileSummary.self, from: data),
              summary.period.id == "today"
        else {
            return nil
        }
        return summary
    }

    static func readReceipt(fileManager: FileManager = .default) -> WatchSummaryCacheReceipt? {
        guard let receiptURL = url(fileName: receiptFileName, fileManager: fileManager),
              let data = try? Data(contentsOf: receiptURL)
        else {
            return nil
        }
        return try? JSONDecoder().decode(WatchSummaryCacheReceipt.self, from: data)
    }

    static func write(
        _ summary: WatchMobileSummary,
        delivery: String,
        fileManager: FileManager = .default
    ) -> WatchSummaryCacheReceipt {
        let metadata = WatchAppBuildMetadata.current
        guard summary.period.id == "today" else {
            let receipt = WatchSummaryCacheReceipt(
                period: summary.period.id,
                summaryGeneratedAt: summary.generatedAt,
                receivedAt: currentTimestamp(),
                appVersion: metadata.appVersion,
                buildNumber: metadata.buildNumber,
                cacheWrittenAt: nil,
                cacheFile: cacheFilePath(fileName),
                cacheWriteStatus: "not_attempted",
                delivery: delivery,
                safeError: "not_today_summary"
            )
            writeReceipt(receipt, fileManager: fileManager)
            return receipt
        }
        guard let target = url(fileName: fileName, fileManager: fileManager) else {
            return WatchSummaryCacheReceipt(
                period: summary.period.id,
                summaryGeneratedAt: summary.generatedAt,
                receivedAt: currentTimestamp(),
                appVersion: metadata.appVersion,
                buildNumber: metadata.buildNumber,
                cacheWrittenAt: nil,
                cacheFile: cacheFilePath(fileName),
                cacheWriteStatus: "failed",
                delivery: delivery,
                safeError: "app_group_container_unavailable"
            )
        }
        let receivedAt = currentTimestamp()
        do {
            try fileManager.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
            let data = try JSONEncoder.watchSummaryCache.encode(summary)
            try data.write(to: target, options: [.atomic])
            let receipt = WatchSummaryCacheReceipt(
                period: summary.period.id,
                summaryGeneratedAt: summary.generatedAt,
                receivedAt: receivedAt,
                appVersion: metadata.appVersion,
                buildNumber: metadata.buildNumber,
                cacheWrittenAt: currentTimestamp(),
                cacheFile: cacheFilePath(fileName),
                cacheWriteStatus: "ok",
                delivery: delivery,
                safeError: nil
            )
            writeReceipt(receipt, fileManager: fileManager)
            return receipt
        } catch {
            let receipt = WatchSummaryCacheReceipt(
                period: summary.period.id,
                summaryGeneratedAt: summary.generatedAt,
                receivedAt: receivedAt,
                appVersion: metadata.appVersion,
                buildNumber: metadata.buildNumber,
                cacheWrittenAt: nil,
                cacheFile: cacheFilePath(fileName),
                cacheWriteStatus: "failed",
                delivery: delivery,
                safeError: safeCacheError(from: error)
            )
            writeReceipt(receipt, fileManager: fileManager)
            return receipt
        }
    }

    private static func writeReceipt(_ receipt: WatchSummaryCacheReceipt, fileManager: FileManager) {
        guard let receiptURL = url(fileName: receiptFileName, fileManager: fileManager) else {
            return
        }
        do {
            try fileManager.createDirectory(at: receiptURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            let data = try JSONEncoder.watchSummaryCache.encode(receipt)
            try data.write(to: receiptURL, options: [.atomic])
        } catch {
            return
        }
    }

    private static func url(fileName: String, fileManager: FileManager) -> URL? {
        if let directory = fileManager.containerURL(forSecurityApplicationGroupIdentifier: appGroupIdentifier) {
            return directory
                .appendingPathComponent(appGroupDirectoryPath, isDirectory: true)
                .appendingPathComponent(fileName)
        }
        return nil
    }

    private static func cacheFilePath(_ fileName: String) -> String {
        "\(appGroupDirectoryPath)/\(fileName)"
    }

    private static func currentTimestamp() -> String {
        ISO8601DateFormatter().string(from: Date())
    }

    private static func safeCacheError(from error: Error) -> String {
        switch error {
        case EncodingError.invalidValue:
            return "encode_failed"
        default:
            return "write_failed"
        }
    }
}

struct WatchAppBuildMetadata: Equatable {
    let appVersion: String
    let buildNumber: String

    static var current: WatchAppBuildMetadata {
        let info = Bundle.main.infoDictionary ?? [:]
        return WatchAppBuildMetadata(
            appVersion: info["CFBundleShortVersionString"] as? String ?? "unknown",
            buildNumber: info["CFBundleVersion"] as? String ?? "unknown"
        )
    }
}

struct WatchSummaryCacheReceipt: Codable, Equatable {
    let schemaVersion: Int
    let period: String
    let summaryGeneratedAt: String?
    let receivedAt: String
    let appVersion: String
    let buildNumber: String
    let cacheWrittenAt: String?
    let cacheFile: String
    let cacheWriteStatus: String
    let delivery: String
    let safeError: String?

    enum CodingKeys: String, CodingKey {
        case schemaVersion
        case period
        case summaryGeneratedAt
        case receivedAt
        case appVersion
        case buildNumber
        case cacheWrittenAt
        case cacheFile
        case cacheWriteStatus
        case delivery
        case safeError
    }

    init(
        schemaVersion: Int = 1,
        period: String,
        summaryGeneratedAt: String?,
        receivedAt: String,
        appVersion: String = WatchAppBuildMetadata.current.appVersion,
        buildNumber: String = WatchAppBuildMetadata.current.buildNumber,
        cacheWrittenAt: String?,
        cacheFile: String,
        cacheWriteStatus: String,
        delivery: String,
        safeError: String?
    ) {
        self.schemaVersion = schemaVersion
        self.period = period
        self.summaryGeneratedAt = summaryGeneratedAt
        self.receivedAt = receivedAt
        self.appVersion = appVersion
        self.buildNumber = buildNumber
        self.cacheWrittenAt = cacheWrittenAt
        self.cacheFile = cacheFile
        self.cacheWriteStatus = cacheWriteStatus
        self.delivery = delivery
        self.safeError = safeError
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.schemaVersion = try container.decodeIfPresent(Int.self, forKey: .schemaVersion) ?? 1
        self.period = try container.decode(String.self, forKey: .period)
        self.summaryGeneratedAt = try container.decodeIfPresent(String.self, forKey: .summaryGeneratedAt)
        self.receivedAt = try container.decode(String.self, forKey: .receivedAt)
        self.appVersion = try container.decodeIfPresent(String.self, forKey: .appVersion) ?? "unknown"
        self.buildNumber = try container.decodeIfPresent(String.self, forKey: .buildNumber) ?? "unknown"
        self.cacheWrittenAt = try container.decodeIfPresent(String.self, forKey: .cacheWrittenAt)
        self.cacheFile = try container.decode(String.self, forKey: .cacheFile)
        self.cacheWriteStatus = try container.decode(String.self, forKey: .cacheWriteStatus)
        self.delivery = try container.decode(String.self, forKey: .delivery)
        self.safeError = try container.decodeIfPresent(String.self, forKey: .safeError)
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

enum WatchQuotaProvider {
    case codex
    case claude
}

enum WatchSummaryDisplay {
    static func preferredCodexWindow(from summary: WatchMobileSummary) -> WatchLimitWindow? {
        preferredWindow(from: summary, provider: .codex)
    }

    static func preferredWindow(from summary: WatchMobileSummary, provider: WatchQuotaProvider) -> WatchLimitWindow? {
        summary.limits.windows
            .filter { providerMatches($0.provider, provider: provider) && $0.isOfficialObserved }
            .sorted { lhs, rhs in
                if isShortWindow(lhs) != isShortWindow(rhs) {
                    return isShortWindow(lhs)
                }
                return lhs.usedPercent > rhs.usedPercent
            }
            .first
    }

    static func quotaText(from summary: WatchMobileSummary?) -> String {
        quotaText(from: summary, provider: .codex)
    }

    static func quotaText(from summary: WatchMobileSummary?, provider: WatchQuotaProvider) -> String {
        guard let summary else {
            return "--"
        }
        guard let window = preferredWindow(from: summary, provider: provider) else {
            return "\(TokenFormat.compact(summary.period.totalTokens)) today"
        }
        return "\(window.usedPercent)% \(shortWindowLabel(window))"
    }

    static func resetText(from summary: WatchMobileSummary?) -> String {
        resetText(from: summary, provider: .codex)
    }

    static func resetText(from summary: WatchMobileSummary?, provider: WatchQuotaProvider) -> String {
        guard let summary else {
            return "reset --"
        }
        guard let window = preferredWindow(from: summary, provider: provider) else {
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

    private static func isShortWindow(_ window: WatchLimitWindow) -> Bool {
        let value = window.window.lowercased()
        return value == "session"
            || value.contains("5h")
            || ((window.windowDurationMinutes ?? 0) > 0 && (window.windowDurationMinutes ?? 0) <= 360)
    }

    private static func shortWindowLabel(_ window: WatchLimitWindow) -> String {
        isShortWindow(window) ? "5h" : "7d"
    }

    private static func providerMatches(_ provider: String, provider target: WatchQuotaProvider) -> Bool {
        let value = provider.lowercased()
        switch target {
        case .codex:
            return value.contains("codex") || value.contains("openai")
        case .claude:
            return value.contains("claude") || value.contains("anthropic")
        }
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
