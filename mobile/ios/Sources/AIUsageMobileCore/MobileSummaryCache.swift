import Foundation

public enum MobileSummaryCache {
    public static let appGroupID = "group.com.wangzhipeng.aiusage"
    public static let fileName = "last-mobile-summary.json"
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
        summary.period.id == companionPeriodID
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
        return now.timeIntervalSince(generatedDate) > maxAge
    }

    public static func formattedGeneratedAt(_ value: String?) -> String {
        guard let value,
              let date = parseGeneratedAt(value)
        else {
            return "--"
        }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "MM/dd HH:mm"
        return formatter.string(from: date)
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
