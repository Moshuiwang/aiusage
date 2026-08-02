import AIUsageMenuBarCore
import Foundation

typealias MenuBarSummaryLoader = @Sendable (MobileSummaryClientConfig) async throws -> MobileSummary
typealias MenuBarRuntimeConfigProvider = @MainActor (RuntimePaths) -> MenuBarRuntimeConfig?
typealias MenuBarNowProvider = @MainActor () -> Date

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
    private let now: MenuBarNowProvider
    private let cacheFreshnessInterval: TimeInterval
    private var refreshSequence = 0
    private var hasLoadedUsableSummary: Bool
    private var cachedSummaries: [String: CachedMenuSummary]

    init(
        paths: RuntimePaths,
        config: MenuBarRuntimeConfig?,
        cachedSummary: MobileSummary? = nil,
        cachedSummaries: [String: CachedMenuSummary] = [:],
        cacheFreshnessInterval: TimeInterval = 300,
        now: @escaping MenuBarNowProvider = { Date() },
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
        self.now = now
        self.cacheFreshnessInterval = max(cacheFreshnessInterval, 0)
        var periodSummaries = cachedSummaries
        if let cachedSummary, periodSummaries[cachedSummary.period.id] == nil {
            periodSummaries[cachedSummary.period.id] = CachedMenuSummary(summary: cachedSummary, fetchedAt: Date.distantPast)
        }
        self.cachedSummaries = periodSummaries
        let initialPeriodID = config?.defaultPeriod ?? cachedSummary?.period.id ?? "today"
        self.selectedPeriodID = initialPeriodID
        self.summary = periodSummaries[initialPeriodID]?.summary ?? cachedSummary ?? MobileSummary.empty(periodID: initialPeriodID)
        self.hasLoadedUsableSummary = periodSummaries[initialPeriodID] != nil || cachedSummary != nil
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

    func refresh(periodID: String? = nil, force: Bool = false) {
        if let periodID {
            selectedPeriodID = periodID
        }
        let selected = selectedPeriodID
        if let cached = cachedSummaries[selected] {
            summary = cached.summary
            hasLoadedUsableSummary = true
            if !force && isFresh(cached) {
                isLoading = false
                errorMessage = nil
                return
            }
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
                let displayed = Self.summaryKeepingLastSuccessfulQuota(
                    loaded,
                    fallback: self.cachedSummaries[loaded.period.id]?.summary
                )
                self.summary = displayed
                self.hasLoadedUsableSummary = true
                self.errorMessage = nil
                self.cachedSummaries[displayed.period.id] = CachedMenuSummary(summary: displayed, fetchedAt: self.now())
                try? SummaryCache.save(displayed, paths: paths)
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

    private func isFresh(_ cached: CachedMenuSummary) -> Bool {
        now().timeIntervalSince(cached.fetchedAt) < cacheFreshnessInterval
    }

    private static func summaryKeepingLastSuccessfulQuota(
        _ loaded: MobileSummary,
        fallback: MobileSummary?
    ) -> MobileSummary {
        guard let fallback else { return loaded }

        let fallbackByProvider = Dictionary(uniqueKeysWithValues: fallback.providerSlots.map { ($0.provider, $0) })
        var seenProviders = Set<String>()
        var slots = loaded.providerSlots.map { slot -> MobileProviderSlot in
            seenProviders.insert(slot.provider)
            guard slot.quota.windows.isEmpty,
                  let previous = fallbackByProvider[slot.provider],
                  !previous.quota.windows.isEmpty
            else {
                return slot
            }
            return MobileProviderSlot(
                provider: slot.provider,
                usage: slot.usage,
                quota: MobileProviderQuota(
                    status: slot.quota.status,
                    reason: slot.quota.reason,
                    lastVerifiedAt: slot.quota.lastVerifiedAt ?? previous.quota.lastVerifiedAt,
                    sourceID: slot.quota.sourceID ?? previous.quota.sourceID,
                    sourceType: slot.quota.sourceType ?? previous.quota.sourceType,
                    windows: previous.quota.windows
                )
            )
        }

        for previous in fallback.providerSlots where !seenProviders.contains(previous.provider) {
            slots.append(
                MobileProviderSlot(
                    provider: previous.provider,
                    usage: .missing,
                    quota: previous.quota
                )
            )
        }

        return MobileSummary(
            schemaVersion: loaded.schemaVersion,
            client: loaded.client,
            generatedAt: loaded.generatedAt,
            timezone: loaded.timezone,
            period: loaded.period,
            trend: loaded.trend,
            sources: loaded.sources,
            breakdown: loaded.breakdown,
            limits: loaded.limits,
            providerSlots: slots,
            providerUsageCoverage: loaded.providerUsageCoverage
        )
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
