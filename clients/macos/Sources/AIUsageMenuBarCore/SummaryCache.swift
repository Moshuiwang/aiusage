import Foundation

public struct CachedMenuSummary: Equatable, Sendable {
    public let summary: MobileSummary
    public let fetchedAt: Date
    public let dateIndexed: Bool

    public init(summary: MobileSummary, fetchedAt: Date, dateIndexed: Bool = false) {
        self.summary = summary
        self.fetchedAt = fetchedAt
        self.dateIndexed = dateIndexed
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

    public static func loadSummaries(paths: RuntimePaths, periods: [String] = MenuPeriodSelection.periodIDs, now: Date = Date()) -> [String: CachedMenuSummary] {
        let files = (try? FileManager.default.contentsOfDirectory(at: paths.periodCacheDirectoryURL, includingPropertiesForKeys: nil)) ?? []
        var summaries: [String: CachedMenuSummary] = [:]
        for file in files where file.pathExtension == "json" {
            guard let cached = loadCachedSummary(from: file), periods.contains(cached.summary.period.id),
                  let selected = selection(for: cached.summary, now: now) else { continue }
            if let previous = summaries[selected.cacheKey], previous.fetchedAt >= cached.fetchedAt { continue }
            summaries[selected.cacheKey] = CachedMenuSummary(summary: cached.summary, fetchedAt: cached.fetchedAt, dateIndexed: true)
        }
        return summaries
    }

    public static func selection(for summary: MobileSummary, now: Date) -> MenuPeriodSelection? {
        let dateString = summary.period.id == "today" ? (summary.period.date ?? summary.period.startDate) : summary.period.startDate
        guard let dateString else { return nil }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = summary.timezone.flatMap(TimeZone.init(identifier:)) ?? TimeZone(identifier: "Asia/Shanghai")!
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.isLenient = false
        guard let date = formatter.date(from: dateString), formatter.string(from: date) == dateString else { return nil }
        let selected = MenuPeriodSelection(periodID: summary.period.id, offset: PeriodMenuBuilder.offset(forDate: date, periodID: summary.period.id, now: now, timezone: summary.timezone))
        return PeriodMenuBuilder.matches(summary, selection: selected, now: now) ? selected : nil
    }

    public static func save(_ summary: MobileSummary, paths: RuntimePaths, offset: Int = 0) throws {
        try save(summary, to: paths.cacheURL(forPeriod: summary.period.id, offset: offset))
        // 按实际日期保留快照，避免「今天」的位置在第二天覆盖昨天的数据。
        let date = summary.period.id == "today" ? (summary.period.date ?? summary.period.startDate) : summary.period.startDate
        if let date, date.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil {
            try save(summary, to: paths.cacheURL(forPeriod: "\(summary.period.id)-\(date)"))
        }
    }
}
