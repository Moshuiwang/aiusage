import Foundation

public enum MobileSummaryCache {
    public static let appGroupID = "group.com.wangzhipeng.aiusage"
    public static let fileName = "last-mobile-summary.json"
    public static let appGroupDirectoryPath = "Library/Caches"
    public static let companionPeriodID = "today"
    public static let companionFreshnessInterval: TimeInterval = 2 * 60 * 60

    public static func readFromAppGroup(
        groupID: String = appGroupID,
        fileManager: FileManager = .default
    ) -> MobileSummary? {
        guard let url = appGroupURL(groupID: groupID, fileManager: fileManager) else {
            return nil
        }
        return readCompanionSummary(from: url)
    }

    public static func writeToAppGroup(
        _ summary: MobileSummary,
        groupID: String = appGroupID,
        fileManager: FileManager = .default
    ) -> MobileSummaryCacheWriteResult {
        guard isCompanionEligible(summary) else {
            return MobileSummaryCacheWriteResult(
                status: "not_attempted",
                writtenAt: nil,
                summaryGeneratedAt: summary.generatedAt,
                safeError: "not_today_summary"
            )
        }
        guard let url = appGroupURL(groupID: groupID, fileManager: fileManager) else {
            return MobileSummaryCacheWriteResult(
                status: "failed",
                writtenAt: nil,
                summaryGeneratedAt: summary.generatedAt,
                safeError: "app_group_container_unavailable"
            )
        }
        do {
            try write(summary, to: url, fileManager: fileManager)
            return MobileSummaryCacheWriteResult(
                status: "ok",
                writtenAt: currentTimestamp(),
                summaryGeneratedAt: summary.generatedAt,
                safeError: nil
            )
        } catch {
            return MobileSummaryCacheWriteResult(
                status: "failed",
                writtenAt: nil,
                summaryGeneratedAt: summary.generatedAt,
                safeError: safeCacheError(from: error)
            )
        }
    }

    public static func readCompanionSummary(from url: URL) -> MobileSummary? {
        guard let summary = read(from: url), isCompanionEligible(summary) else {
            return nil
        }
        return summary
    }

    public static func isCompanionEligible(_ summary: MobileSummary) -> Bool {
        guard summary.period.id == companionPeriodID,
              let date = summary.period.date,
              let generatedAt = summary.generatedAt,
              let generated = parseGeneratedAt(generatedAt) else { return false }
        return date == shanghaiDate(generated)
    }

    public static func isStale(
        _ summary: MobileSummary,
        now: Date = Date(),
        maxAge: TimeInterval = companionFreshnessInterval
    ) -> Bool {
        guard let generatedAt = summary.generatedAt,
              let generatedDate = parseGeneratedAt(generatedAt)
        else {
            return true
        }
        return summary.period.date != shanghaiDate(now) || now.timeIntervalSince(generatedDate) > maxAge
    }

    static func shanghaiDate(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "Asia/Shanghai")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }

    public static func formattedGeneratedAt(_ value: String?) -> String {
        guard let value,
              let date = parseGeneratedAt(value)
        else {
            return "--"
        }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = encodedTimeZone(in: value) ?? TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "MM/dd HH:mm"
        return formatter.string(from: date)
    }

    private static func encodedTimeZone(in value: String) -> TimeZone? {
        if value.hasSuffix("Z") {
            return TimeZone(secondsFromGMT: 0)
        }
        guard value.count >= 6 else {
            return nil
        }
        let suffix = value.suffix(6)
        guard (suffix.first == "+" || suffix.first == "-"), suffix[suffix.index(suffix.startIndex, offsetBy: 3)] == ":" else {
            return nil
        }
        let hourStart = suffix.index(after: suffix.startIndex)
        let hourEnd = suffix.index(hourStart, offsetBy: 2)
        let minuteStart = suffix.index(after: suffix.index(suffix.startIndex, offsetBy: 3))
        guard let hours = Int(suffix[hourStart..<hourEnd]),
              let minutes = Int(suffix[minuteStart...]),
              hours <= 23,
              minutes <= 59
        else {
            return nil
        }
        let sign = suffix.first == "-" ? -1 : 1
        return TimeZone(secondsFromGMT: sign * ((hours * 60 + minutes) * 60))
    }

    public static func read(from url: URL) -> MobileSummary? {
        guard let data = try? Data(contentsOf: url) else {
            return nil
        }
        return try? JSONDecoder().decode(MobileSummary.self, from: data)
    }

    public static func write(
        _ summary: MobileSummary,
        to url: URL,
        fileManager: FileManager = .default
    ) throws {
        try fileManager.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let data = try JSONEncoder.mobileSummaryCache.encode(summary)
        try data.write(to: url, options: [.atomic])
    }

    private static func appGroupURL(groupID: String, fileManager: FileManager) -> URL? {
        fileManager
            .containerURL(forSecurityApplicationGroupIdentifier: groupID)?
            .appendingPathComponent(appGroupDirectoryPath, isDirectory: true)
            .appendingPathComponent(fileName)
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

    private static func parseGeneratedAt(_ value: String) -> Date? {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        if let date = formatter.date(from: value) {
            return date
        }
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: value)
    }
}

public struct MobileSummaryCacheWriteResult: Equatable, Sendable {
    public let status: String
    public let writtenAt: String?
    public let summaryGeneratedAt: String?
    public let safeError: String?

    public init(status: String, writtenAt: String?, summaryGeneratedAt: String?, safeError: String?) {
        self.status = status
        self.writtenAt = writtenAt
        self.summaryGeneratedAt = summaryGeneratedAt
        self.safeError = safeError
    }
}

private extension JSONEncoder {
    static var mobileSummaryCache: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }
}
