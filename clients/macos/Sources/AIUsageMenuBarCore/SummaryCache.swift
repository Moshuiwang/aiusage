import Foundation

public struct CachedMenuSummary: Equatable, Sendable {
    public let summary: MobileSummary
    public let fetchedAt: Date
    public let dateIndexed: Bool
    public let localToday: Bool

    public init(summary: MobileSummary, fetchedAt: Date, dateIndexed: Bool = false, localToday: Bool = false) {
        self.summary = summary
        self.fetchedAt = fetchedAt
        self.dateIndexed = dateIndexed
        self.localToday = localToday
    }
}

public enum SummaryCache {
    private static let localTodayPrefix = "client-today-"

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
        return CachedMenuSummary(
            summary: summary, fetchedAt: fetchedAt, localToday: url.lastPathComponent.hasPrefix(localTodayPrefix)
        )
    }

    public static func save(_ summary: MobileSummary, to url: URL) throws {
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let data = try JSONEncoder().encode(summary)
        try data.write(to: url, options: Data.WritingOptions.atomic)
    }

    public static func loadSummaries(
        paths: RuntimePaths, periods: [String] = MenuPeriodSelection.periodIDs,
        now: Date = Date(), localTimezone: String = TimeZone.autoupdatingCurrent.identifier
    ) -> [String: CachedMenuSummary] {
        let files = (try? FileManager.default.contentsOfDirectory(at: paths.periodCacheDirectoryURL, includingPropertiesForKeys: nil)) ?? []
        var summaries: [String: CachedMenuSummary] = [:]
        for file in files where file.pathExtension == "json" {
            guard let cached = loadCachedSummary(from: file), periods.contains(cached.summary.period.id),
                  let selected = selection(for: cached, now: now, localTimezone: localTimezone) else { continue }
            if let previous = summaries[selected.cacheKey] {
                if previous.localToday && !cached.localToday { continue }
                if previous.localToday == cached.localToday && previous.fetchedAt >= cached.fetchedAt { continue }
            }
            summaries[selected.cacheKey] = CachedMenuSummary(
                summary: cached.summary, fetchedAt: cached.fetchedAt, dateIndexed: true, localToday: cached.localToday
            )
        }
        return summaries
    }

    public static func selection(for cached: CachedMenuSummary, now: Date, localTimezone: String) -> MenuPeriodSelection? {
        if cached.localToday {
            let today = MenuPeriodSelection(periodID: "today")
            return cached.summary.serviceTimezone != nil && cached.summary.timezone == localTimezone
                && PeriodMenuBuilder.matches(cached.summary, selection: today, now: now) ? today : nil
        }
        let selected = selection(for: cached.summary, now: now)
        // 新服务端的 today offset < 0 才会从旧口径的历史目录读取。
        return selected?.isCurrentToday == true && cached.summary.serviceTimezone != nil ? nil : selected
    }

    public static func loadRelativeSummary(
        paths: RuntimePaths, for selected: MenuPeriodSelection, now: Date, localTimezone: String
    ) -> CachedMenuSummary? {
        if selected.isCurrentToday,
           let cached = loadCachedSummary(from: localTodayCacheURL(paths: paths, timezone: localTimezone)),
           selection(for: cached, now: now, localTimezone: localTimezone) == selected {
            return cached
        }
        return loadCachedSummary(from: paths.cacheURL(forPeriod: selected.periodID, offset: selected.offset))
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
        if summary.period.id == "today", offset == 0, summary.serviceTimezone != nil, let timezone = summary.timezone {
            // 本机「今天」只保留本机日窗口。跨午夜后不能成为服务时区的历史日期。
            try save(summary, to: localTodayCacheURL(paths: paths, timezone: timezone))
            return
        }
        try save(summary, to: paths.cacheURL(forPeriod: summary.period.id, offset: offset))
        // 按实际日期保留快照，避免「今天」的位置在第二天覆盖昨天的数据。
        let date = summary.period.id == "today" ? (summary.period.date ?? summary.period.startDate) : summary.period.startDate
        if let date, date.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil {
            try save(summary, to: paths.cacheURL(forPeriod: "\(summary.period.id)-\(date)"))
        }
    }

    private static func localTodayCacheURL(paths: RuntimePaths, timezone: String) -> URL {
        paths.cacheURL(forPeriod: localTodayPrefix + timezone)
    }
}
