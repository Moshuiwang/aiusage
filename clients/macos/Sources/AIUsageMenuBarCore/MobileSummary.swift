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
    public let providerSlots: [MobileProviderSlot]
    public let providerUsageCoverage: MobileProviderUsageCoverage

    public init(
        schemaVersion: Int,
        client: String,
        generatedAt: String?,
        timezone: String?,
        period: MobilePeriod,
        trend: MobileTrend,
        sources: [MobileSource],
        breakdown: MobileBreakdown,
        limits: MobileLimits,
        providerSlots: [MobileProviderSlot] = [],
        providerUsageCoverage: MobileProviderUsageCoverage = .unknown
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
        self.providerSlots = providerSlots
        self.providerUsageCoverage = providerUsageCoverage
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = try container.decode(Int.self, forKey: .schemaVersion)
        client = try container.decode(String.self, forKey: .client)
        generatedAt = try container.decodeIfPresent(String.self, forKey: .generatedAt)
        timezone = try container.decodeIfPresent(String.self, forKey: .timezone)
        period = try container.decode(MobilePeriod.self, forKey: .period)
        trend = try container.decode(MobileTrend.self, forKey: .trend)
        sources = try container.decode([MobileSource].self, forKey: .sources)
        breakdown = try container.decode(MobileBreakdown.self, forKey: .breakdown)
        limits = try container.decode(MobileLimits.self, forKey: .limits)
        providerSlots = try container.decodeIfPresent([MobileProviderSlot].self, forKey: .providerSlots) ?? []
        providerUsageCoverage = try container.decodeIfPresent(
            MobileProviderUsageCoverage.self,
            forKey: .providerUsageCoverage
        ) ?? .unknown
    }

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
        case providerSlots = "provider_slots"
        case providerUsageCoverage = "provider_usage_coverage"
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
            limits: MobileLimits(observedCount: 0, totalCount: 0, windows: []),
            providerSlots: [],
            providerUsageCoverage: .unknown
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
    public let claudeTokens: Int
    public let codexTokens: Int
    public let unknownTokens: Int

    enum CodingKeys: String, CodingKey {
        case bucket
        case label
        case tokens
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
        case cacheTokens = "cache_tokens"
        case cacheRatio = "cache_ratio"
        case claudeTokens = "claude_tokens"
        case codexTokens = "codex_tokens"
        case unknownTokens = "unknown_tokens"
    }

    public init(
        bucket: String,
        label: String,
        tokens: Int,
        inputTokens: Int,
        outputTokens: Int,
        cacheTokens: Int,
        cacheRatio: Int,
        claudeTokens: Int = 0,
        codexTokens: Int = 0,
        unknownTokens: Int? = nil
    ) {
        self.bucket = bucket
        self.label = label
        self.tokens = tokens
        self.inputTokens = inputTokens
        self.outputTokens = outputTokens
        self.cacheTokens = cacheTokens
        self.cacheRatio = cacheRatio
        self.claudeTokens = max(claudeTokens, 0)
        self.codexTokens = max(codexTokens, 0)
        self.unknownTokens = max(unknownTokens ?? (tokens - claudeTokens - codexTokens), 0)
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let bucket = try values.decode(String.self, forKey: .bucket)
        let label = try values.decode(String.self, forKey: .label)
        let tokens = try values.decode(Int.self, forKey: .tokens)
        self.init(
            bucket: bucket,
            label: label,
            tokens: tokens,
            inputTokens: try values.decode(Int.self, forKey: .inputTokens),
            outputTokens: try values.decode(Int.self, forKey: .outputTokens),
            cacheTokens: try values.decode(Int.self, forKey: .cacheTokens),
            cacheRatio: try values.decode(Int.self, forKey: .cacheRatio),
            claudeTokens: try values.decodeIfPresent(Int.self, forKey: .claudeTokens) ?? 0,
            codexTokens: try values.decodeIfPresent(Int.self, forKey: .codexTokens) ?? 0,
            unknownTokens: try values.decodeIfPresent(Int.self, forKey: .unknownTokens)
        )
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
    public let bySource: [MobileBreakdownRow]?

    public init(byMachine: [MobileBreakdownRow], byOSUser: [MobileBreakdownRow], byAgent: [MobileBreakdownRow], byModel: [MobileBreakdownRow], byDate: [MobileBreakdownRow], bySource: [MobileBreakdownRow]? = nil) {
        self.byMachine = byMachine; self.byOSUser = byOSUser; self.byAgent = byAgent
        self.byModel = byModel; self.byDate = byDate; self.bySource = bySource
    }

    enum CodingKeys: String, CodingKey {
        case byMachine = "by_machine"
        case byOSUser = "by_os_user"
        case byAgent = "by_agent"
        case byModel = "by_model"
        case byDate = "by_date"
        case bySource = "by_source"
    }
}

public struct MobileBreakdownRow: Codable, Equatable, Sendable, Identifiable {
    public let id: String
    public let label: String
    public let tokens: Int
    public let sourceIDs: [String]?
    public let contributions: [MobileBreakdownContribution]?
    public let machine: String?
    public let osUser: String?
    public let agents: [MobileSourceAgent]?

    public init(id: String, label: String, tokens: Int, sourceIDs: [String]? = nil, contributions: [MobileBreakdownContribution]? = nil, machine: String? = nil, osUser: String? = nil, agents: [MobileSourceAgent]? = nil) {
        self.id = id; self.label = label; self.tokens = tokens
        self.sourceIDs = sourceIDs; self.contributions = contributions
        self.machine = machine; self.osUser = osUser; self.agents = agents
    }

    enum CodingKeys: String, CodingKey {
        case id
        case label
        case tokens
        case sourceIDs = "source_ids"
        case contributions
        case machine
        case osUser = "os_user"
        case agents
    }
}

public struct MobileSourceAgent: Codable, Equatable, Sendable, Identifiable {
    public let id: String
    public let label: String
    public let tokens: Int
    public let status: String
    public let models: [MobileSourceModel]

    public var valueText: String { status == "available" ? TokenFormat.compact(tokens) : "数据缺失" }
}

public struct MobileSourceModel: Codable, Equatable, Sendable, Identifiable {
    public let id: String
    public let label: String
    public let tokens: Int
    public let status: String

    public var title: String { status == "missing" ? "模型未知" : label }
    public var valueText: String { TokenFormat.compact(tokens) }
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

public struct MobileProviderSlot: Codable, Equatable, Sendable, Identifiable {
    public var id: String { provider }

    public let provider: String
    public let usage: MobileProviderUsage
    public let quota: MobileProviderQuota

    public init(provider: String, usage: MobileProviderUsage, quota: MobileProviderQuota) {
        self.provider = provider
        self.usage = usage
        self.quota = quota
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        provider = try container.decode(String.self, forKey: .provider)
        usage = try container.decodeIfPresent(MobileProviderUsage.self, forKey: .usage) ?? .missing
        quota = try container.decodeIfPresent(MobileProviderQuota.self, forKey: .quota) ?? .missing()
    }

    enum CodingKeys: String, CodingKey {
        case provider
        case usage
        case quota
    }
}

public struct MobileProviderUsage: Codable, Equatable, Sendable {
    public let status: String
    public let totalTokens: Int
    public let inputTokens: Int
    public let outputTokens: Int
    public let cacheTokens: Int

    public static let missing = MobileProviderUsage(
        status: "missing",
        totalTokens: 0,
        inputTokens: 0,
        outputTokens: 0,
        cacheTokens: 0
    )

    public init(
        status: String,
        totalTokens: Int,
        inputTokens: Int,
        outputTokens: Int,
        cacheTokens: Int
    ) {
        self.status = status
        self.totalTokens = totalTokens
        self.inputTokens = inputTokens
        self.outputTokens = outputTokens
        self.cacheTokens = cacheTokens
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        status = try container.decodeIfPresent(String.self, forKey: .status) ?? "missing"
        totalTokens = try container.decodeIfPresent(Int.self, forKey: .totalTokens) ?? 0
        inputTokens = try container.decodeIfPresent(Int.self, forKey: .inputTokens) ?? 0
        outputTokens = try container.decodeIfPresent(Int.self, forKey: .outputTokens) ?? 0
        cacheTokens = try container.decodeIfPresent(Int.self, forKey: .cacheTokens) ?? 0
    }

    enum CodingKeys: String, CodingKey {
        case status
        case totalTokens = "total_tokens"
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
        case cacheTokens = "cache_tokens"
    }
}

public struct MobileProviderQuota: Codable, Equatable, Sendable {
    public let status: String
    public let reason: String?
    public let lastVerifiedAt: String?
    public let sourceID: String?
    public let sourceType: String?
    public let windows: [MobileLimitWindow]

    public init(
        status: String,
        reason: String?,
        lastVerifiedAt: String?,
        sourceID: String?,
        sourceType: String?,
        windows: [MobileLimitWindow]
    ) {
        self.status = status
        self.reason = reason
        self.lastVerifiedAt = lastVerifiedAt
        self.sourceID = sourceID
        self.sourceType = sourceType
        self.windows = windows
    }

    public static func missing(reason: String? = "no_data") -> MobileProviderQuota {
        MobileProviderQuota(
            status: "missing",
            reason: reason,
            lastVerifiedAt: nil,
            sourceID: nil,
            sourceType: nil,
            windows: []
        )
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        status = try container.decodeIfPresent(String.self, forKey: .status) ?? "missing"
        reason = try container.decodeIfPresent(String.self, forKey: .reason)
        lastVerifiedAt = try container.decodeIfPresent(String.self, forKey: .lastVerifiedAt)
        sourceID = try container.decodeIfPresent(String.self, forKey: .sourceID)
        sourceType = try container.decodeIfPresent(String.self, forKey: .sourceType)
        windows = try container.decodeIfPresent([MobileLimitWindow].self, forKey: .windows) ?? []
    }

    enum CodingKeys: String, CodingKey {
        case status
        case reason
        case lastVerifiedAt = "last_verified_at"
        case sourceID = "source_id"
        case sourceType = "source_type"
        case windows
    }
}

public struct MobileProviderUsageCoverage: Codable, Equatable, Sendable {
    public let status: String
    public let totalTokens: Int
    public let attributedTokens: Int
    public let otherProviderTokens: Int
    public let unattributedTokens: Int
    private let hasCompleteStatistics: Bool

    public static let unknown = MobileProviderUsageCoverage(
        status: "unknown",
        totalTokens: 0,
        attributedTokens: 0,
        otherProviderTokens: 0,
        unattributedTokens: 0
    )

    public var isComplete: Bool {
        hasCompleteStatistics &&
            status == "complete" &&
            attributedTokens == totalTokens &&
            otherProviderTokens == 0 &&
            unattributedTokens == 0
    }

    public init(
        status: String,
        totalTokens: Int,
        attributedTokens: Int,
        otherProviderTokens: Int,
        unattributedTokens: Int
    ) {
        self.status = status
        self.totalTokens = totalTokens
        self.attributedTokens = attributedTokens
        self.otherProviderTokens = otherProviderTokens
        self.unattributedTokens = unattributedTokens
        self.hasCompleteStatistics = true
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        status = try container.decodeIfPresent(String.self, forKey: .status) ?? "unknown"
        let decodedTotalTokens = try container.decodeIfPresent(Int.self, forKey: .totalTokens)
        let decodedAttributedTokens = try container.decodeIfPresent(Int.self, forKey: .attributedTokens)
        let decodedOtherProviderTokens = try container.decodeIfPresent(Int.self, forKey: .otherProviderTokens)
        let decodedUnattributedTokens = try container.decodeIfPresent(Int.self, forKey: .unattributedTokens)
        totalTokens = decodedTotalTokens ?? 0
        attributedTokens = decodedAttributedTokens ?? 0
        otherProviderTokens = decodedOtherProviderTokens ?? 0
        unattributedTokens = decodedUnattributedTokens ?? 0
        hasCompleteStatistics = decodedTotalTokens != nil &&
            decodedAttributedTokens != nil &&
            decodedOtherProviderTokens != nil &&
            decodedUnattributedTokens != nil
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(status, forKey: .status)
        try container.encode(totalTokens, forKey: .totalTokens)
        try container.encode(attributedTokens, forKey: .attributedTokens)
        try container.encode(otherProviderTokens, forKey: .otherProviderTokens)
        try container.encode(unattributedTokens, forKey: .unattributedTokens)
    }

    enum CodingKeys: String, CodingKey {
        case status
        case totalTokens = "total_tokens"
        case attributedTokens = "attributed_tokens"
        case otherProviderTokens = "other_provider_tokens"
        case unattributedTokens = "unattributed_tokens"
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
        official: Bool
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
