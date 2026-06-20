import Foundation

public struct MobileSummary: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let client: String
    public let generatedAt: String?
    public let timezone: String?
    public let period: MobilePeriod
    public let trend: MobileTrend
    public let sources: [MobileSource]
    public let breakdown: MobileBreakdown
    public let limits: MobileLimits

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case client
        case generatedAt = "generated_at"
        case timezone
        case period
        case trend
        case sources
        case breakdown
        case limits
    }

    public init(
        schemaVersion: Int,
        client: String,
        generatedAt: String?,
        timezone: String?,
        period: MobilePeriod,
        trend: MobileTrend,
        sources: [MobileSource],
        breakdown: MobileBreakdown,
        limits: MobileLimits
    ) {
        self.schemaVersion = schemaVersion
        self.client = client
        self.generatedAt = generatedAt
        self.timezone = timezone
        self.period = period
        self.trend = trend
        self.sources = sources
        self.breakdown = breakdown
        self.limits = limits
    }
}

public extension MobileSummary {
    static func empty(
        periodID: String,
        timezone: String? = "Asia/Shanghai",
        generatedAt: String? = nil
    ) -> MobileSummary {
        let trendGranularity = periodID == "today" ? "hour" : "day"
        return MobileSummary(
            schemaVersion: 1,
            client: "ios",
            generatedAt: generatedAt,
            timezone: timezone,
            period: MobilePeriod(
                id: periodID,
                date: nil,
                startDate: nil,
                endDate: nil,
                totalTokens: 0,
                inputTokens: 0,
                outputTokens: 0,
                cacheTokens: 0,
                cacheRatio: 0,
                machine: nil,
                account: nil
            ),
            trend: MobileTrend(
                period: periodID,
                granularity: trendGranularity,
                startDate: nil,
                endDate: nil,
                points: []
            ),
            sources: [],
            breakdown: MobileBreakdown(
                byMachine: [],
                byOSUser: [],
                byAgent: [],
                byModel: [],
                byDate: []
            ),
            limits: MobileLimits(
                observedCount: 0,
                totalCount: 0,
                windows: []
            )
        )
    }
}

public struct MobilePeriod: Codable, Equatable, Sendable {
    public let id: String
    public let date: String?
    public let startDate: String?
    public let endDate: String?
    public let totalTokens: Int
    public let inputTokens: Int
    public let outputTokens: Int
    public let cacheTokens: Int
    public let cacheRatio: Int
    public let machine: String?
    public let account: String?

    enum CodingKeys: String, CodingKey {
        case id
        case date
        case startDate = "start_date"
        case endDate = "end_date"
        case totalTokens = "total_tokens"
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
        case cacheTokens = "cache_tokens"
        case cacheRatio = "cache_ratio"
        case machine
        case account
    }

    public init(
        id: String,
        date: String?,
        startDate: String?,
        endDate: String?,
        totalTokens: Int,
        inputTokens: Int,
        outputTokens: Int,
        cacheTokens: Int,
        cacheRatio: Int,
        machine: String?,
        account: String?
    ) {
        self.id = id
        self.date = date
        self.startDate = startDate
        self.endDate = endDate
        self.totalTokens = totalTokens
        self.inputTokens = inputTokens
        self.outputTokens = outputTokens
        self.cacheTokens = cacheTokens
        self.cacheRatio = cacheRatio
        self.machine = machine
        self.account = account
    }
}

public struct MobileTrend: Codable, Equatable, Sendable {
    public let period: String?
    public let granularity: String?
    public let startDate: String?
    public let endDate: String?
    public let points: [MobileTrendPoint]

    enum CodingKeys: String, CodingKey {
        case period
        case granularity
        case startDate = "start_date"
        case endDate = "end_date"
        case points
    }

    public init(
        period: String?,
        granularity: String?,
        startDate: String?,
        endDate: String?,
        points: [MobileTrendPoint]
    ) {
        self.period = period
        self.granularity = granularity
        self.startDate = startDate
        self.endDate = endDate
        self.points = points
    }
}

public struct MobileTrendPoint: Codable, Equatable, Sendable, Identifiable {
    public var id: String { bucket }

    public let bucket: String
    public let label: String
    public let tokens: Int
    public let inputTokens: Int
    public let outputTokens: Int
    public let cacheTokens: Int
    public let cacheRatio: Int

    enum CodingKeys: String, CodingKey {
        case bucket
        case label
        case tokens
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
        case cacheTokens = "cache_tokens"
        case cacheRatio = "cache_ratio"
    }
}

public struct MobileSource: Codable, Equatable, Sendable, Identifiable {
    public var id: String { sourceID }

    public let sourceID: String
    public let machine: String?
    public let osUser: String?
    public let platform: String?
    public let displayName: String?
    public let status: String
    public let lastObservedAt: String?
    public let lastPushedAt: String?
    public let errorMessage: String?

    enum CodingKeys: String, CodingKey {
        case sourceID = "source_id"
        case machine
        case osUser = "os_user"
        case platform
        case displayName = "display_name"
        case status
        case lastObservedAt = "last_observed_at"
        case lastPushedAt = "last_pushed_at"
        case errorMessage = "error_message"
    }
}

public struct MobileBreakdown: Codable, Equatable, Sendable {
    public let byMachine: [MobileBreakdownRow]
    public let byOSUser: [MobileBreakdownRow]
    public let byAgent: [MobileBreakdownRow]
    public let byModel: [MobileBreakdownRow]
    public let byDate: [MobileBreakdownRow]

    enum CodingKeys: String, CodingKey {
        case byMachine = "by_machine"
        case byOSUser = "by_os_user"
        case byAgent = "by_agent"
        case byModel = "by_model"
        case byDate = "by_date"
    }

    public init(
        byMachine: [MobileBreakdownRow],
        byOSUser: [MobileBreakdownRow],
        byAgent: [MobileBreakdownRow],
        byModel: [MobileBreakdownRow],
        byDate: [MobileBreakdownRow]
    ) {
        self.byMachine = byMachine
        self.byOSUser = byOSUser
        self.byAgent = byAgent
        self.byModel = byModel
        self.byDate = byDate
    }
}

public struct MobileBreakdownRow: Codable, Equatable, Sendable, Identifiable {
    public let id: String
    public let label: String
    public let tokens: Int
    public let sourceIDs: [String]?
    public let contributions: [MobileBreakdownContribution]?

    enum CodingKeys: String, CodingKey {
        case id
        case label
        case tokens
        case sourceIDs = "source_ids"
        case contributions
    }

    public init(
        id: String,
        label: String,
        tokens: Int,
        sourceIDs: [String]?,
        contributions: [MobileBreakdownContribution]?
    ) {
        self.id = id
        self.label = label
        self.tokens = tokens
        self.sourceIDs = sourceIDs
        self.contributions = contributions
    }
}

public struct MobileBreakdownContribution: Codable, Equatable, Sendable {
    public let sourceID: String
    public let tokens: Int

    enum CodingKeys: String, CodingKey {
        case sourceID = "source_id"
        case tokens
    }
}

public struct MobileLimits: Codable, Equatable, Sendable {
    public let observedCount: Int
    public let totalCount: Int
    public let windows: [MobileLimitWindow]

    enum CodingKeys: String, CodingKey {
        case observedCount = "observed_count"
        case totalCount = "total_count"
        case windows
    }

    public init(observedCount: Int, totalCount: Int, windows: [MobileLimitWindow]) {
        self.observedCount = observedCount
        self.totalCount = totalCount
        self.windows = windows
    }
}

public struct MobileLimitWindow: Codable, Equatable, Sendable, Identifiable {
    public var id: String { [sourceID, provider, window].joined(separator: "|") }

    public let sourceID: String
    public let provider: String
    public let window: String
    public let usedPercent: Double
    public let remainingPercent: Double
    public let resetAt: String?
    public let windowDurationMinutes: Int
    public let observedAt: String?
    public let sourceType: String?
    public let confidence: String
    public let status: String
    public let official: Bool
    public let accountLabel: String?
    public let accountPlanLabel: String?

    public var isOfficialObserved: Bool {
        official && confidence == "observed" && status == "ok"
    }

    public init(
        sourceID: String,
        provider: String,
        window: String,
        usedPercent: Double,
        remainingPercent: Double,
        resetAt: String?,
        windowDurationMinutes: Int,
        observedAt: String?,
        sourceType: String?,
        confidence: String,
        status: String,
        official: Bool,
        accountLabel: String? = nil,
        accountPlanLabel: String? = nil
    ) {
        self.sourceID = sourceID
        self.provider = provider
        self.window = window
        self.usedPercent = usedPercent
        self.remainingPercent = remainingPercent
        self.resetAt = resetAt
        self.windowDurationMinutes = windowDurationMinutes
        self.observedAt = observedAt
        self.sourceType = sourceType
        self.confidence = confidence
        self.status = status
        self.official = official
        self.accountLabel = accountLabel
        self.accountPlanLabel = accountPlanLabel
    }

    enum CodingKeys: String, CodingKey {
        case sourceID = "source_id"
        case provider
        case window
        case usedPercent = "used_percent"
        case remainingPercent = "remaining_percent"
        case resetAt = "reset_at"
        case windowDurationMinutes = "window_duration_minutes"
        case observedAt = "observed_at"
        case sourceType = "source_type"
        case confidence
        case status
        case official
        case accountLabel = "account_label"
        case accountPlanLabel = "account_plan_label"
    }
}
