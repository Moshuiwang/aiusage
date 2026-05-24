import Foundation

public struct GroupTotal: Identifiable, Equatable, Sendable {
    public var id: String { name }

    public let name: String
    public let totalTokens: Int

    public init(name: String, totalTokens: Int) {
        self.name = name
        self.totalTokens = totalTokens
    }
}

public struct UsageSummary: Equatable, Sendable {
    public let today: String
    public let generatedAt: String?
    public let totalTokens: Int
    public let machineTotals: [GroupTotal]
    public let accountTotals: [GroupTotal]
    public let agentTotals: [GroupTotal]
    public let failedSources: [SourceStatus]
    public let okSourceCount: Int
    public let totalSourceCount: Int
    public let hasGeneratedAt: Bool

    public var hasTodayData: Bool {
        totalTokens > 0
    }
}

public enum UsageSummaryBuilder {
    public static func build(
        from snapshot: LatestSnapshot,
        now: Date = Date(),
        calendar inputCalendar: Calendar = .current
    ) -> UsageSummary {
        var calendar = inputCalendar
        calendar.timeZone = .current

        let formatter = DateFormatter()
        formatter.calendar = calendar
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = calendar.timeZone
        formatter.dateFormat = "yyyy-MM-dd"
        let today = formatter.string(from: now)

        let todaysItems = snapshot.items.filter { $0.date == today }
        let total = todaysItems.reduce(0) { $0 + $1.totalTokens }

        return UsageSummary(
            today: today,
            generatedAt: snapshot.generatedAt,
            totalTokens: total,
            machineTotals: group(todaysItems, by: \.machine),
            accountTotals: group(todaysItems, by: \.account),
            agentTotals: group(todaysItems, by: \.agent),
            failedSources: snapshot.sourceStatus.filter { $0.status != "ok" && $0.status != "disabled" },
            okSourceCount: snapshot.sourceStatus.filter { $0.status == "ok" }.count,
            totalSourceCount: snapshot.sourceStatus.filter { $0.status != "disabled" }.count,
            hasGeneratedAt: snapshot.generatedAt?.isEmpty == false
        )
    }

    private static func group(_ items: [UsageItem], by keyPath: KeyPath<UsageItem, String>) -> [GroupTotal] {
        let totals = Dictionary(grouping: items, by: { $0[keyPath: keyPath] })
            .mapValues { rows in rows.reduce(0) { $0 + $1.totalTokens } }

        return totals
            .map { GroupTotal(name: $0.key, totalTokens: $0.value) }
            .sorted {
                if $0.totalTokens == $1.totalTokens {
                    return $0.name.localizedStandardCompare($1.name) == .orderedAscending
                }
                return $0.totalTokens > $1.totalTokens
            }
    }
}

public enum TokenFormat {
    public static func compact(_ value: Int) -> String {
        let number = Double(value)
        if abs(value) >= 1_000_000 {
            return String(format: "%.1fM", number / 1_000_000)
        }
        if abs(value) >= 1_000 {
            return String(format: "%.1fK", number / 1_000)
        }
        return String(value)
    }

    public static func full(_ value: Int) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        return formatter.string(from: NSNumber(value: value)) ?? String(value)
    }
}
