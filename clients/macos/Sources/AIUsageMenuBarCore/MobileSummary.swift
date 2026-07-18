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
}

public extension MobileSummary {
    static func empty(periodID: String = "today") -> MobileSummary {
        MobileSummary(
            schemaVersion: 1,
            client: "macos",
            generatedAt: nil,
            timezone: nil,
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
                granularity: periodID == "today" ? "hour" : "day",
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
            limits: MobileLimits(observedCount: 0, totalCount: 0, windows: [])
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
    public let providers: [MobileLimitProviderStatus]

    public init(
        observedCount: Int,
        totalCount: Int,
        windows: [MobileLimitWindow],
        providers: [MobileLimitProviderStatus] = []
    ) {
        self.observedCount = observedCount
        self.totalCount = totalCount
        self.windows = windows
        self.providers = providers
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        observedCount = try container.decode(Int.self, forKey: .observedCount)
        totalCount = try container.decode(Int.self, forKey: .totalCount)
        windows = try container.decode([MobileLimitWindow].self, forKey: .windows)
        providers = try container.decodeIfPresent([MobileLimitProviderStatus].self, forKey: .providers) ?? []
    }

    enum CodingKeys: String, CodingKey {
        case observedCount = "observed_count"
        case totalCount = "total_count"
        case windows
        case providers
    }
}

public struct MobileLimitProviderStatus: Codable, Equatable, Sendable {
    public let provider: String
    public let sourceID: String
    public let observedAt: String?
    public let sourceType: String?
    public let status: String

    public init(provider: String, sourceID: String, observedAt: String?, sourceType: String?, status: String) {
        self.provider = provider
        self.sourceID = sourceID
        self.observedAt = observedAt
        self.sourceType = sourceType
        self.status = status
    }

    enum CodingKeys: String, CodingKey {
        case provider
        case sourceID = "source_id"
        case observedAt = "observed_at"
        case sourceType = "source_type"
        case status
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

    public var isOfficialObserved: Bool {
        official && confidence == "observed" && status == "ok"
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
    }
}
