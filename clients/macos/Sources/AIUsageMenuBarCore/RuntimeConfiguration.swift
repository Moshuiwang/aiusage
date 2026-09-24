import Foundation

public struct MenuBarRuntimeConfig: Codable, Equatable, Sendable {
    public let serverURL: String
    public let token: String?
    public let dashboardURL: String?
    public let refreshIntervalSeconds: TimeInterval
    public let defaultPeriod: String
    public let machineAliases: [String: String]?

    enum CodingKeys: String, CodingKey {
        case serverURL = "server_url"
        case token
        case dashboardURL = "dashboard_url"
        case refreshIntervalSeconds = "refresh_interval_seconds"
        case defaultPeriod = "default_period"
        case machineAliases = "machine_aliases"
    }

    public init(
        serverURL: String,
        token: String?,
        dashboardURL: String?,
        refreshIntervalSeconds: TimeInterval = 300,
        defaultPeriod: String = "today",
        machineAliases: [String: String]? = nil
    ) {
        self.serverURL = serverURL
        self.token = token
        self.dashboardURL = dashboardURL
        self.refreshIntervalSeconds = max(refreshIntervalSeconds, 300)
        self.defaultPeriod = defaultPeriod
        self.machineAliases = machineAliases
    }
}

public enum MenuBarRuntimeConfigLoader {
    public static func load(
        paths: RuntimePaths,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> MenuBarRuntimeConfig? {
        let fileConfig = loadFile(paths.configURL)
        let envServer = environment["AI_USAGE_API_BASE_URL"]
        let envToken = environment["AI_USAGE_API_TOKEN"] ?? environment["AI_USAGE_INGEST_TOKEN"]
        let serverURL = envServer ?? fileConfig?.serverURL

        guard let serverURL, !serverURL.isEmpty else {
            return nil
        }

        return MenuBarRuntimeConfig(
            serverURL: serverURL,
            token: envToken ?? fileConfig?.token,
            dashboardURL: environment["AI_USAGE_DASHBOARD_URL"] ?? fileConfig?.dashboardURL ?? serverURL,
            refreshIntervalSeconds: Double(environment["AI_USAGE_REFRESH_SECONDS"] ?? "") ?? fileConfig?.refreshIntervalSeconds ?? 300,
            defaultPeriod: environment["AI_USAGE_PERIOD"] ?? fileConfig?.defaultPeriod ?? "today",
            machineAliases: fileConfig?.machineAliases
        )
    }

    private static func loadFile(_ url: URL) -> MenuBarRuntimeConfig? {
        guard let data = try? Data(contentsOf: url) else {
            return nil
        }
        return try? JSONDecoder().decode(MenuBarRuntimeConfig.self, from: data)
    }
}
