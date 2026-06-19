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
    ) throws {
        guard isCompanionEligible(summary) else {
            return
        }
        guard let url = appGroupURL(groupID: groupID, fileManager: fileManager) else {
            return
        }
        try write(summary, to: url, fileManager: fileManager)
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

private extension JSONEncoder {
    static var mobileSummaryCache: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }
}
