import Foundation

/// #176：期间菜单里的一行（日/周/月的一个历史期）。
public struct PeriodMenuRow: Equatable, Sendable, Identifiable {
    public var id: String { selection.cacheKey }

    public let selection: MenuPeriodSelection
    public let title: String
    public let subtitle: String
    /// 缓存命中 = 该期 totalTokens 的紧凑文本；未命中 = "—"。
    public let totalText: String
    /// 按 Agent 汇总的迷你堆叠条分段；未命中时为空。
    public let segments: [MenuTrendSegment]
    public let isSelected: Bool

    public init(
        selection: MenuPeriodSelection,
        title: String,
        subtitle: String,
        totalText: String,
        segments: [MenuTrendSegment],
        isSelected: Bool
    ) {
        self.selection = selection
        self.title = title
        self.subtitle = subtitle
        self.totalText = totalText
        self.segments = segments
        self.isSelected = isSelected
    }
}

/// #176：期间菜单只读已有缓存，展开菜单本身不发任何网络请求。
public enum PeriodMenuBuilder {
    public static func rows(
        periodID: String,
        now: Date,
        timezone: String?,
        selectedOffset: Int = 0,
        cached: (MenuPeriodSelection) -> MobileSummary?
    ) -> [PeriodMenuRow] {
        let tz = timezone.flatMap(TimeZone.init(identifier:)) ?? TimeZone(identifier: "Asia/Shanghai")!
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = tz
        let today = calendar.startOfDay(for: now)

        let count = periodID == "today" ? 7 : 6
        return (0..<count).map { index in
            let offset = -index
            let selection = MenuPeriodSelection(periodID: periodID, offset: offset)
            let bounds = periodBounds(periodID: periodID, offset: offset, today: today, calendar: calendar)
            let title = titleText(periodID: periodID, offset: offset, bounds: bounds, calendar: calendar)
            let subtitle = subtitleText(periodID: periodID, bounds: bounds, calendar: calendar)
            let expectedStartDate = dayString(bounds.start, calendar: calendar)

            let cachedSummary = cached(selection)
            let valid = cachedSummary.flatMap { summary in
                isCacheValid(summary, periodID: periodID, expectedStartDate: expectedStartDate) ? summary : nil
            }

            return PeriodMenuRow(
                selection: selection,
                title: title,
                subtitle: subtitle,
                totalText: valid.map { TokenFormat.compact($0.period.totalTokens) } ?? "—",
                segments: valid.map { MenuBarViewModel.aggregatedSegments($0.trend.points) } ?? [],
                isSelected: offset == selectedOffset
            )
        }
    }

    private struct Bounds {
        let start: Date
        let end: Date
    }

    /// 与 cloudflare/native-worker/src/read-model/shared.ts `periodBounds` 的 offset 分支保持一致：
    /// 周从周一开始；offset==0 时 end 是「现在」而不是周日/月末，历史 offset 的 end 才是完整周期末尾。
    private static func periodBounds(periodID: String, offset: Int, today: Date, calendar: Calendar) -> Bounds {
        switch periodID {
        case "week":
            let weekday = calendar.component(.weekday, from: today) // 1=周日...7=周六
            let daysSinceMonday = (weekday + 5) % 7
            let monday = calendar.date(byAdding: .day, value: -daysSinceMonday, to: today) ?? today
            let start = calendar.date(byAdding: .day, value: offset * 7, to: monday) ?? monday
            let end = offset == 0 ? today : (calendar.date(byAdding: .day, value: 6, to: start) ?? start)
            return Bounds(start: start, end: end)
        case "month":
            let comps = calendar.dateComponents([.year, .month], from: today)
            let firstOfMonth = calendar.date(from: comps) ?? today
            let start = calendar.date(byAdding: .month, value: offset, to: firstOfMonth) ?? firstOfMonth
            let end: Date
            if offset == 0 {
                end = today
            } else {
                let nextMonth = calendar.date(byAdding: .month, value: 1, to: start) ?? start
                end = calendar.date(byAdding: .day, value: -1, to: nextMonth) ?? start
            }
            return Bounds(start: start, end: end)
        default: // "today"
            let day = calendar.date(byAdding: .day, value: offset, to: today) ?? today
            return Bounds(start: day, end: day)
        }
    }

    private static func titleText(periodID: String, offset: Int, bounds: Bounds, calendar: Calendar) -> String {
        switch periodID {
        case "week":
            switch offset {
            case 0: return "本周"
            case -1: return "上周"
            default: return rangeShortText(bounds.start, bounds.end, calendar: calendar)
            }
        case "month":
            switch offset {
            case 0: return "本月"
            case -1: return "上月"
            default: return monthText(bounds.start, calendar: calendar)
            }
        default: // "today"
            switch offset {
            case 0: return "今天"
            case -1: return "昨天"
            case -2: return "前天"
            default: return dateText(bounds.start, calendar: calendar)
            }
        }
    }

    private static func subtitleText(periodID: String, bounds: Bounds, calendar: Calendar) -> String {
        if periodID == "today" {
            return dateText(bounds.start, calendar: calendar)
        }
        return rangeShortText(bounds.start, bounds.end, calendar: calendar)
    }

    private static func dateText(_ date: Date, calendar: Calendar) -> String {
        let c = calendar.dateComponents([.month, .day], from: date)
        return "\(c.month ?? 0)月\(c.day ?? 0)日"
    }

    private static func monthText(_ date: Date, calendar: Calendar) -> String {
        let c = calendar.dateComponents([.year, .month], from: date)
        return "\(c.year ?? 0)年\(c.month ?? 0)月"
    }

    private static func rangeShortText(_ start: Date, _ end: Date, calendar: Calendar) -> String {
        let sc = calendar.dateComponents([.year, .month, .day], from: start)
        let ec = calendar.dateComponents([.year, .month, .day], from: end)
        if sc.year == ec.year, sc.month == ec.month {
            return "\(sc.month ?? 0)月\(sc.day ?? 0)日–\(ec.day ?? 0)日"
        }
        if sc.year == ec.year {
            return "\(sc.month ?? 0)月\(sc.day ?? 0)日–\(ec.month ?? 0)月\(ec.day ?? 0)日"
        }
        return "\(sc.year ?? 0)年\(sc.month ?? 0)月\(sc.day ?? 0)日–\(ec.year ?? 0)年\(ec.month ?? 0)月\(ec.day ?? 0)日"
    }

    private static func dayString(_ date: Date, calendar: Calendar) -> String {
        let formatter = DateFormatter()
        formatter.calendar = calendar
        formatter.timeZone = calendar.timeZone
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter.string(from: date)
    }

    /// 缓存有效性按「实际起始日期」校验，不按 offset 字面：跨天后同一个 offset 的日历含义会漂移，
    /// 昨天存的 "today:-1" 到了今天可能已经不再指向期望的日期，必须判未命中而不是显示过期数字。
    private static func isCacheValid(_ summary: MobileSummary, periodID: String, expectedStartDate: String) -> Bool {
        guard summary.period.id == periodID else { return false }
        let actualStartDate = periodID == "today"
            ? (summary.period.date ?? summary.period.startDate)
            : summary.period.startDate
        return actualStartDate == expectedStartDate
    }
}
