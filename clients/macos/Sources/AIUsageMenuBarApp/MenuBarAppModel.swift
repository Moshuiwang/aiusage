import AIUsageMenuBarCore
import Foundation

typealias MenuBarSummaryLoader = @Sendable (MobileSummaryClientConfig) async throws -> MobileSummary
typealias MenuBarRuntimeConfigProvider = @MainActor (RuntimePaths) -> MenuBarRuntimeConfig?

@MainActor
final class MenuBarAppModel: ObservableObject {
    @Published private(set) var summary: MobileSummary
    @Published var selectedPeriodID: String
    @Published private(set) var isLoading = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var config: MenuBarRuntimeConfig?

    let paths: RuntimePaths
    private let loadSummary: MenuBarSummaryLoader
    private let loadRuntimeConfig: MenuBarRuntimeConfigProvider
    private var refreshSequence = 0
    private var hasLoadedUsableSummary: Bool

    init(
        paths: RuntimePaths,
        config: MenuBarRuntimeConfig?,
        cachedSummary: MobileSummary?,
        loadSummary: @escaping MenuBarSummaryLoader = { config in
            try await MobileSummaryClient(config: config).load()
        },
        loadRuntimeConfig: @escaping MenuBarRuntimeConfigProvider = { paths in
            MenuBarRuntimeConfigLoader.load(paths: paths)
        }
    ) {
        self.paths = paths
        self.config = config
        self.loadSummary = loadSummary
        self.loadRuntimeConfig = loadRuntimeConfig
        let initialPeriodID = config?.defaultPeriod ?? cachedSummary?.period.id ?? "today"
        self.selectedPeriodID = initialPeriodID
        self.summary = cachedSummary ?? MobileSummary.empty(periodID: initialPeriodID)
        self.hasLoadedUsableSummary = cachedSummary != nil
    }

    var state: MenuBarState {
        MenuBarViewModel.build(from: summary, selectedPeriodID: selectedPeriodID)
    }

    var hasConfig: Bool {
        config != nil
    }

    var dashboardURL: URL? {
        guard let value = config?.dashboardURL ?? config?.serverURL else {
            return nil
        }
        return URL(string: value)
    }

    func refresh(periodID: String? = nil) {
        if let periodID {
            selectedPeriodID = periodID
        }
        let runtimeConfig = loadRuntimeConfig(paths) ?? config
        config = runtimeConfig
        guard let runtimeConfig, let baseURL = URL(string: runtimeConfig.serverURL) else {
            errorMessage = "需要配置服务地址"
            return
        }

        refreshSequence += 1
        let sequence = refreshSequence
        isLoading = true
        errorMessage = nil
        let selected = selectedPeriodID
        let paths = paths
        let token = runtimeConfig.token
        let loader = loadSummary
        Task {
            do {
                let loaded = try await loader(
                    MobileSummaryClientConfig(
                        baseURL: baseURL,
                        bearerToken: token,
                        period: selected
                    )
                )
                guard sequence == self.refreshSequence, selected == self.selectedPeriodID else {
                    return
                }
                self.summary = loaded
                self.hasLoadedUsableSummary = true
                self.errorMessage = nil
                try? SummaryCache.save(loaded, to: paths.cacheURL)
            } catch {
                guard sequence == self.refreshSequence else {
                    return
                }
                let prefix = self.hasLoadedUsableSummary ? "刷新失败，正在显示缓存" : "读取失败"
                self.errorMessage = "\(prefix)：\(Self.shortError(error))"
            }
            if sequence == self.refreshSequence {
                self.isLoading = false
            }
        }
    }

    private static func shortError(_ error: Error) -> String {
        if let clientError = error as? MobileSummaryClientError {
            switch clientError {
            case .invalidURL:
                return "地址无效"
            case .invalidResponse:
                return "响应无效"
            case .statusCode(let code):
                return "HTTP \(code)"
            }
        }
        return String(describing: error)
    }
}
