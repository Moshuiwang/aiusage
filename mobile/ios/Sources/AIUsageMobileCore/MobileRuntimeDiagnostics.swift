import Foundation

public enum MobileRefreshSource: String, Codable, Sendable {
    case foregroundInitialLoad = "foreground_initial_load"
    case pullToRefresh = "pull_to_refresh"
    case companionTodayEnsure = "companion_today_ensure"
    case backgroundAppRefresh = "background_app_refresh"
    case settingsTriggeredRefresh = "settings_triggered_refresh"
    case unknown
}

public struct MobileAppBuildMetadata: Equatable, Sendable {
    public let appVersion: String
    public let buildNumber: String

    public static var current: MobileAppBuildMetadata {
        let info = Bundle.main.infoDictionary ?? [:]
        return MobileAppBuildMetadata(
            appVersion: info["CFBundleShortVersionString"] as? String ?? "unknown",
            buildNumber: info["CFBundleVersion"] as? String ?? "unknown"
        )
    }
}

public struct MobileRuntimeDiagnostic: Codable, Equatable, Sendable {
    public let status: String
    public let requestURL: String?
    public let period: String
    public let totalTokens: Int?
    public let generatedAt: String?
    public let error: String?
    public let recordedAt: String
    public let refreshSource: String
    public let appVersion: String
    public let buildNumber: String
    public let cacheWriteStatus: String?
    public let cacheWrittenAt: String?
    public let cacheSummaryGeneratedAt: String?
    public let watchPushStatus: String?
    public let watchPushReason: String?
    public let safeCacheError: String?

    public init(
        status: String,
        requestURL: String?,
        period: String,
        totalTokens: Int?,
        generatedAt: String?,
        error: String?,
        recordedAt: String,
        refreshSource: String = MobileRefreshSource.unknown.rawValue,
        appVersion: String = MobileAppBuildMetadata.current.appVersion,
        buildNumber: String = MobileAppBuildMetadata.current.buildNumber,
        cacheWriteStatus: String? = nil,
        cacheWrittenAt: String? = nil,
        cacheSummaryGeneratedAt: String? = nil,
        watchPushStatus: String? = nil,
        watchPushReason: String? = nil,
        safeCacheError: String? = nil
    ) {
        self.status = status
        self.requestURL = requestURL
        self.period = period
        self.totalTokens = totalTokens
        self.generatedAt = generatedAt
        self.error = error
        self.recordedAt = recordedAt
        self.refreshSource = refreshSource
        self.appVersion = appVersion
        self.buildNumber = buildNumber
        self.cacheWriteStatus = cacheWriteStatus
        self.cacheWrittenAt = cacheWrittenAt
        self.cacheSummaryGeneratedAt = cacheSummaryGeneratedAt
        self.watchPushStatus = watchPushStatus
        self.watchPushReason = watchPushReason
        self.safeCacheError = safeCacheError
    }
}

public enum MobileRuntimeDiagnostics {
    public static let fileName = "last-mobile-runtime-diagnostic.json"

    public static func success(
        config: MobileSummaryAPIConfig,
        summary: MobileSummary,
        refreshSource: MobileRefreshSource = .unknown,
        cacheWriteResult: MobileSummaryCacheWriteResult? = nil,
        watchPushStatus: String? = nil,
        watchPushReason: String? = nil
    ) {
        let metadata = MobileAppBuildMetadata.current
        write(
            MobileRuntimeDiagnostic(
                status: "success",
                requestURL: requestURLString(config: config),
                period: summary.period.id,
                totalTokens: summary.period.totalTokens,
                generatedAt: summary.generatedAt,
                error: nil,
                recordedAt: currentTimestamp(),
                refreshSource: refreshSource.rawValue,
                appVersion: metadata.appVersion,
                buildNumber: metadata.buildNumber,
                cacheWriteStatus: cacheWriteResult?.status,
                cacheWrittenAt: cacheWriteResult?.writtenAt,
                cacheSummaryGeneratedAt: cacheWriteResult?.summaryGeneratedAt,
                watchPushStatus: watchPushStatus,
                watchPushReason: watchPushReason,
                safeCacheError: cacheWriteResult?.safeError
            )
        )
    }

    public static func failure(
        period: String,
        config: MobileSummaryAPIConfig?,
        error: Error,
        refreshSource: MobileRefreshSource = .unknown
    ) {
        let metadata = MobileAppBuildMetadata.current
        write(
            MobileRuntimeDiagnostic(
                status: "failure",
                requestURL: config.map(requestURLString),
                period: config?.period ?? period,
                totalTokens: nil,
                generatedAt: nil,
                error: String(describing: error),
                recordedAt: currentTimestamp(),
                refreshSource: refreshSource.rawValue,
                appVersion: metadata.appVersion,
                buildNumber: metadata.buildNumber
            )
        )
    }

    public static func configurationRequired(
        period: String,
        refreshSource: MobileRefreshSource = .unknown
    ) {
        let metadata = MobileAppBuildMetadata.current
        write(
            MobileRuntimeDiagnostic(
                status: "configurationRequired",
                requestURL: nil,
                period: period,
                totalTokens: nil,
                generatedAt: nil,
                error: "missing runtime configuration",
                recordedAt: currentTimestamp(),
                refreshSource: refreshSource.rawValue,
                appVersion: metadata.appVersion,
                buildNumber: metadata.buildNumber
            )
        )
    }

    public static func read(from url: URL) -> MobileRuntimeDiagnostic? {
        guard let data = try? Data(contentsOf: url) else {
            return nil
        }
        return try? JSONDecoder().decode(MobileRuntimeDiagnostic.self, from: data)
    }

    public static func write(
        _ diagnostic: MobileRuntimeDiagnostic,
        groupID: String = MobileSummaryCache.appGroupID,
        fileManager: FileManager = .default
    ) {
        if let directory = fileManager.containerURL(forSecurityApplicationGroupIdentifier: groupID) {
            let url = directory.appendingPathComponent(fileName)
            try? write(diagnostic, to: url, fileManager: fileManager)
        }

        if let directory = fileManager.urls(for: .cachesDirectory, in: .userDomainMask).first {
            let url = directory.appendingPathComponent(fileName)
            try? write(diagnostic, to: url, fileManager: fileManager)
        }
    }

    public static func write(
        _ diagnostic: MobileRuntimeDiagnostic,
        to url: URL,
        fileManager: FileManager = .default
    ) throws {
        try fileManager.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .prettyPrinted]
        try encoder.encode(diagnostic).write(to: url, options: [.atomic])
    }

    private static func requestURLString(config: MobileSummaryAPIConfig) -> String {
        let endpoint = config.baseURL.appendingPathComponent("api/mobile/summary")
        guard var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false) else {
            return endpoint.absoluteString
        }
        components.queryItems = [
            URLQueryItem(name: "period", value: config.period)
        ]
        return components.url?.absoluteString ?? endpoint.absoluteString
    }

    private static func currentTimestamp() -> String {
        ISO8601DateFormatter().string(from: Date())
    }
}
