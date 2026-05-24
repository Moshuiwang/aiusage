import Foundation

public struct LatestSnapshot: Decodable, Equatable, Sendable {
    public let generatedAt: String?
    public let timezone: String?
    public let items: [UsageItem]
    public let sourceStatus: [SourceStatus]

    enum CodingKeys: String, CodingKey {
        case generatedAt = "generated_at"
        case timezone
        case items
        case sourceStatus = "source_status"
    }

    public init(
        generatedAt: String?,
        timezone: String?,
        items: [UsageItem],
        sourceStatus: [SourceStatus]
    ) {
        self.generatedAt = generatedAt
        self.timezone = timezone
        self.items = items
        self.sourceStatus = sourceStatus
    }
}

public struct UsageItem: Decodable, Equatable, Sendable, Identifiable {
    public var id: String {
        [machine, account, agent, date].joined(separator: "|")
    }

    public let machine: String
    public let account: String
    public let agent: String
    public let date: String
    public let inputTokens: Int
    public let outputTokens: Int
    public let cacheCreationTokens: Int
    public let cacheReadTokens: Int
    public let totalTokens: Int

    enum CodingKeys: String, CodingKey {
        case machine
        case account
        case agent
        case date
        case inputTokens = "input_tokens"
        case outputTokens = "output_tokens"
        case cacheCreationTokens = "cache_creation_tokens"
        case cacheReadTokens = "cache_read_tokens"
        case totalTokens = "total_tokens"
    }

    public init(
        machine: String,
        account: String,
        agent: String,
        date: String,
        inputTokens: Int,
        outputTokens: Int,
        cacheCreationTokens: Int,
        cacheReadTokens: Int,
        totalTokens: Int
    ) {
        self.machine = machine
        self.account = account
        self.agent = agent
        self.date = date
        self.inputTokens = inputTokens
        self.outputTokens = outputTokens
        self.cacheCreationTokens = cacheCreationTokens
        self.cacheReadTokens = cacheReadTokens
        self.totalTokens = totalTokens
    }
}

public struct SourceStatus: Decodable, Equatable, Sendable, Identifiable {
    public var id: String { sourceID }

    public let sourceID: String
    public let status: String
    public let errorType: String?
    public let message: String?

    enum CodingKeys: String, CodingKey {
        case sourceID = "source_id"
        case status
        case errorType = "error_type"
        case message
    }

    public init(sourceID: String, status: String, errorType: String?, message: String?) {
        self.sourceID = sourceID
        self.status = status
        self.errorType = errorType
        self.message = message
    }
}
