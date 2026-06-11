import AIUsageMobileCore
import Foundation
import SwiftUI

@main
struct AIUsageMobileApp: App {
    private let initialTabID = ProcessInfo.processInfo.environment["AI_USAGE_INITIAL_TAB"] ?? "home"

    var body: some Scene {
        WindowGroup {
            LiveSummaryContainerView(initialTabID: initialTabID)
        }
    }
}

struct LiveSummaryContainerView: View {
    let initialTabID: String
    @State private var summary: MobileSummary
    @State private var loadState: LoadState
    @State private var latestRequestID = UUID()
    @State private var cachedSummaries: [String: MobileSummary] = [:]

    init(initialTabID: String) {
        self.initialTabID = initialTabID
        let initialPeriod = MobileSummaryRuntimeConfig.initialPeriod()
        self._summary = State(initialValue: .empty(periodID: initialPeriod))
        self._loadState = State(initialValue: .loading(period: initialPeriod))
    }

    var body: some View {
        AIUsageMobileRootView(
            summary: summary,
            initialTabID: initialTabID,
            refreshingPeriodID: loadState.refreshingPeriodID,
            onPeriodSelected: { period in
                Task {
                    await loadLiveSummary(period: period)
                }
            },
            onRefresh: { period in
                Task {
                    await refreshLiveSummary(period: period)
                }
            }
        )
            .overlay(alignment: .topTrailing) {
                if case .loading = loadState {
                    ProgressView()
                        .controlSize(.small)
                        .padding(12)
                }
            }
            .overlay(alignment: .top) {
                if let message = loadState.message {
                    ProductionConnectionStatusView(message: message)
                        .padding(.top, 8)
                        .padding(.horizontal, 14)
                }
            }
            .task {
                await loadLiveSummary(period: MobileSummaryRuntimeConfig.initialPeriod())
            }
    }

    private func loadLiveSummary(period: String) async {
        switch MobilePeriodSelection.decision(
            selectedPeriodID: period,
            visibleSummary: summary,
            cachedSummaries: cachedSummaries,
            isLoadingSelectedPeriod: loadState.refreshingPeriodID == period
        ) {
        case .ignore:
            return
        case .showCached(let cachedSummary):
            withAnimation(.snappy(duration: 0.18)) {
                summary = cachedSummary
            }
        case .keepVisibleSummary:
            break
        }

        let requestID = UUID()
        latestRequestID = requestID
        guard let config = MobileSummaryRuntimeConfig.makeAPIConfig(period: period) else {
            loadState = .configurationRequired
            return
        }
        withAnimation(.easeInOut(duration: 0.16)) {
            loadState = .loading(period: period)
        }
        do {
            let loadedSummary = try await MobileSummaryAPIClient(config: config).load()
            guard latestRequestID == requestID else {
                return
            }
            cachedSummaries[loadedSummary.period.id] = loadedSummary
            withAnimation(.snappy(duration: 0.45)) {
                summary = loadedSummary
                loadState = .live
            }
        } catch {
            guard latestRequestID == requestID else {
                return
            }
            loadState = .failed
        }
    }

    private func refreshLiveSummary(period: String) async {
        let requestID = UUID()
        latestRequestID = requestID
        guard let config = MobileSummaryRuntimeConfig.makeAPIConfig(period: period) else {
            loadState = .configurationRequired
            return
        }
        withAnimation(.easeInOut(duration: 0.16)) {
            loadState = .loading(period: period)
        }
        do {
            let loadedSummary = try await MobileSummaryAPIClient(config: config).load()
            guard latestRequestID == requestID else {
                return
            }
            cachedSummaries[loadedSummary.period.id] = loadedSummary
            withAnimation(.snappy(duration: 0.45)) {
                summary = loadedSummary
                loadState = .live
            }
        } catch {
            guard latestRequestID == requestID else {
                return
            }
            loadState = .failed
        }
    }
}

enum LoadState: Equatable {
    case loading(period: String)
    case live
    case configurationRequired
    case failed

    var refreshingPeriodID: String? {
        switch self {
        case .loading(let period):
            return period
        case .live, .configurationRequired, .failed:
            return nil
        }
    }

    var message: String? {
        switch self {
        case .configurationRequired:
            return "需要生产服务配置"
        case .failed:
            return "刷新失败，已保留当前数据"
        case .loading, .live:
            return nil
        }
    }
}

struct ProductionConnectionStatusView: View {
    let message: String

    var body: some View {
        Label(message, systemImage: "exclamationmark.triangle.fill")
            .font(.footnote.weight(.semibold))
            .foregroundStyle(.orange)
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(Color.orange.opacity(0.24), lineWidth: 1)
            }
            .shadow(color: .black.opacity(0.08), radius: 8, y: 3)
    }
}

enum MobileSummaryRuntimeConfig {
    private static let productionBaseURL = "https://vpn2.chunbai.com:8443"

    static func initialPeriod(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        defaults: UserDefaults = .standard
    ) -> String {
        environment["AI_USAGE_PERIOD"] ?? defaults.string(forKey: "AIUsagePeriod") ?? "week"
    }

    static func makeAPIConfig(
        period: String,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        defaults: UserDefaults = .standard,
        bundle: Bundle = .main
    ) -> MobileSummaryAPIConfig? {
        let rawBaseURL = runtimeValue(
            environmentKey: "AI_USAGE_API_BASE_URL",
            defaultsKey: "AIUsageAPIBaseURL",
            bundleKey: "AIUsageAPIBaseURL",
            fallback: productionBaseURL,
            environment: environment,
            defaults: defaults,
            bundle: bundle
        )
        guard let rawBaseURL, let baseURL = URL(string: rawBaseURL) else {
            return nil
        }
        guard isProductionServer(baseURL) || environment["AI_USAGE_ALLOW_NON_PROD_SERVER"] == "1" else {
            return nil
        }

        return MobileSummaryAPIConfig(
            baseURL: baseURL,
            bearerToken: runtimeValue(
                environmentKey: "AI_USAGE_API_TOKEN",
                defaultsKey: "AIUsageAPIToken",
                bundleKey: "AIUsageAPIToken",
                fallback: nil,
                environment: environment,
                defaults: defaults,
                bundle: bundle
            ),
            period: period
        )
    }

    static func isProductionServer(_ url: URL) -> Bool {
        url.scheme == "https"
            && url.host?.lowercased() == "vpn2.chunbai.com"
            && url.port == 8443
    }

    private static func runtimeValue(
        environmentKey: String,
        defaultsKey: String,
        bundleKey: String,
        fallback: String?,
        environment: [String: String],
        defaults: UserDefaults,
        bundle: Bundle
    ) -> String? {
        for candidate in [
            environment[environmentKey],
            defaults.string(forKey: defaultsKey),
            bundle.object(forInfoDictionaryKey: bundleKey) as? String,
            fallback
        ] {
            if let value = normalizedRuntimeValue(candidate) {
                return value
            }
        }
        return nil
    }

    private static func normalizedRuntimeValue(_ value: String?) -> String? {
        guard let value else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty || trimmed.hasPrefix("$(") {
            return nil
        }
        return trimmed
    }
}
