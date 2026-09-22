import Foundation

public struct MobileHistorySelection: Hashable, Sendable {
    public let period: String
    public let offset: Int

    public init(period: String = "today", offset: Int = 0) {
        self.period = ["today", "week", "month"].contains(period) ? period : "today"
        self.offset = min(0, self.period == "today" ? max(-6, offset) : offset)
    }

    public var cacheKey: String { "\(period):\(offset)" }
    public var canGoEarlier: Bool { period != "today" || offset > -6 }
    public var canGoLater: Bool { offset < 0 }
    public var isCurrentDay: Bool { period == "today" && offset == 0 }
    public var earlier: Self { Self(period: period, offset: offset - 1) }
    public var later: Self { Self(period: period, offset: offset + 1) }
}

public struct MobileHistoryState: Sendable {
    public private(set) var selection: MobileHistorySelection
    public private(set) var summary: MobileSummary
    public private(set) var requestID = UUID()
    private var cached: [String: MobileSummary] = [:]
    private var cacheDay: String?

    public init(selection: MobileHistorySelection = MobileHistorySelection(), summary: MobileSummary? = nil) {
        self.selection = selection
        self.summary = summary ?? .empty(periodID: selection.period)
    }

    @discardableResult
    public mutating func begin(_ selection: MobileHistorySelection, now: Date = Date()) -> UUID {
        expireCachedDayIfNeeded(now: now)
        self.selection = selection
        requestID = UUID()
        summary = cached[selection.cacheKey] ?? .empty(periodID: selection.period)
        return requestID
    }

    @discardableResult
    public mutating func fail(requestID: UUID, now: Date = Date()) -> Bool {
        guard requestID == self.requestID else { return false }
        expireCachedDayIfNeeded(now: now)
        return true
    }

    @discardableResult
    public mutating func expireCachedDayIfNeeded(now: Date = Date()) -> Bool {
        let day = MobileSummaryCache.shanghaiDate(now)
        guard cacheDay != day else { return false }
        cached.removeAll()
        cacheDay = day
        summary = .empty(periodID: selection.period)
        // Any request issued against yesterday's relative offsets is obsolete.
        requestID = UUID()
        return true
    }

    @discardableResult
    public mutating func accept(_ summary: MobileSummary, requestID: UUID, now: Date = Date()) -> Bool {
        guard requestID == self.requestID else { return false }
        guard !expireCachedDayIfNeeded(now: now), summary.period.id == selection.period else { return false }
        self.summary = summary
        cached[selection.cacheKey] = summary
        return true
    }
}

public enum MobilePeriodTitle {
    public static func title(_ period: MobilePeriod, selection: MobileHistorySelection) -> String {
        switch selection.period {
        case "today":
            guard let date = period.date else { return "日期加载中" }
            return selection.offset == 0 ? "今天 · \(date)" : date
        case "week":
            return selection.offset == 0 ? "本周" : "历史周"
        case "month":
            guard let start = period.startDate, start.count >= 7 else { return "月份加载中" }
            return String(start.prefix(7)).replacingOccurrences(of: "-", with: "年") + "月"
        default: return "日期加载中"
        }
    }
}
