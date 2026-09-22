import Foundation

public struct CachedMenuSummary: Equatable, Sendable {
    public let summary: MobileSummary
    public let fetchedAt: Date

    public init(summary: MobileSummary, fetchedAt: Date) {
        self.summary = summary
        self.fetchedAt = fetchedAt
    }
}

public enum SummaryCache {
    public static func load(from url: URL) -> MobileSummary? {
        loadCachedSummary(from: url)?.summary
    }

    public static func loadCachedSummary(from url: URL) -> CachedMenuSummary? {
        guard let data = try? Data(contentsOf: url) else {
            return nil
        }
        guard let summary = try? JSONDecoder().decode(MobileSummary.self, from: data) else {
            return nil
        }
        let fetchedAt = (try? FileManager.default.attributesOfItem(atPath: url.path)[.modificationDate] as? Date) ?? Date.distantPast
        return CachedMenuSummary(summary: summary, fetchedAt: fetchedAt)
    }

    public static func save(_ summary: MobileSummary, to url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let data = try JSONEncoder().encode(summary)
        try data.write(to: url, options: Data.WritingOptions.atomic)
    }

    public static func loadSummaries(paths: RuntimePaths, periods: [String] = MenuPeriodSelection.periodIDs) -> [String: CachedMenuSummary] {
        var summaries: [String: CachedMenuSummary] = [:]
        for period in periods {
            if let cached = loadCachedSummary(from: paths.cacheURL(forPeriod: period)) {
                summaries[period] = cached
            }
        }
        return summaries
    }

    public static func save(_ summary: MobileSummary, paths: RuntimePaths, offset: Int = 0) throws {
        try save(summary, to: paths.cacheURL(forPeriod: summary.period.id, offset: offset))
    }
}
