import AIUsageMobileCore
import Foundation
import Security
import SwiftUI
import WatchConnectivity

@main
struct AIUsageMobileApp: App {
    private let initialTabID = ProcessInfo.processInfo.environment["AI_USAGE_INITIAL_TAB"] ?? "home"

    init() {
        WatchSummaryBridge.shared.activate()
    }

    var body: some Scene {
        WindowGroup {
            LiveSummaryContainerView(initialTabID: initialTabID)
        }
    }
}

struct LiveSummaryContainerView: View {
    let initialTabID: String
    // Widget runtime config sharing requires explicit App Group + Keychain access group design and is intentionally deferred.
    private let tokenStore = KeychainTokenStore()
    @State private var summary: MobileSummary
    @State private var loadState: LoadState
    @State private var latestRequestID = UUID()
    @State private var cachedSummaries: [String: MobileSummary] = [:]
    @State private var isShowingSettings = false

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
                Task { await loadLiveSummary(period: period) }
            },
            onRefresh: { period in
                Task { await refreshLiveSummary(period: period) }
            },
            onRefreshAsync: { period in
                await refreshLiveSummary(period: period)
                // Pull-to-refresh failures are silent — don't leave the error banner on screen
                if case .failed = loadState { loadState = .live }
            },
            onSettingsTapped: {
                isShowingSettings = true
            }
        )
            .overlay(alignment: .top) {
                if let message = loadState.message {
                    ProductionConnectionStatusView(message: message)
                        .padding(.top, 8)
                        .padding(.horizontal, 14)
                }
            }
            .sheet(isPresented: $isShowingSettings) {
                MobileServerSettingsView(
                    tokenStore: tokenStore,
                    period: summary.period.id
                ) {
                    Task { await refreshLiveSummary(period: summary.period.id) }
                }
            }
            .task {
                let initialPeriod = MobileSummaryRuntimeConfig.initialPeriod()
                await loadLiveSummary(period: initialPeriod)
                await ensureTodayCompanionSummary(visiblePeriod: initialPeriod)
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
        guard let config = MobileSummaryRuntimeConfig.makeAPIConfig(period: period, tokenStore: tokenStore) else {
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
            shareWithCompanionIfNeeded(loadedSummary)
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
        guard let config = MobileSummaryRuntimeConfig.makeAPIConfig(period: period, tokenStore: tokenStore) else {
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
            shareWithCompanionIfNeeded(loadedSummary)
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

    private func shareWithCompanionIfNeeded(_ loadedSummary: MobileSummary) {
        guard MobileSummaryCache.isCompanionEligible(loadedSummary) else {
            return
        }
        try? MobileSummaryCache.writeToAppGroup(loadedSummary)
        WatchSummaryBridge.shared.push(loadedSummary)
    }

    private func ensureTodayCompanionSummary(visiblePeriod: String) async {
        guard visiblePeriod != MobileSummaryCache.companionPeriodID else {
            return
        }
        guard let config = MobileSummaryRuntimeConfig.makeAPIConfig(
            period: MobileSummaryCache.companionPeriodID,
            tokenStore: tokenStore
        ) else {
            return
        }
        guard let loadedSummary = try? await MobileSummaryAPIClient(config: config).load() else {
            return
        }
        shareWithCompanionIfNeeded(loadedSummary)
        cachedSummaries[loadedSummary.period.id] = loadedSummary
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
            return "请在设置里填写服务地址和 token"
        case .failed:
            return "连接失败，请检查服务地址或 token"
        case .loading, .live:
            return nil
        }
    }
}

final class WatchSummaryBridge: NSObject, WCSessionDelegate, @unchecked Sendable {
    static let shared = WatchSummaryBridge()
    private var session: WCSession?

    func activate() {
        guard WCSession.isSupported() else {
            return
        }
        let session = WCSession.default
        self.session = session
        session.delegate = self
        session.activate()
    }

    func push(_ summary: MobileSummary) {
        guard let session, session.activationState == .activated else {
            return
        }
        guard let data = try? JSONEncoder().encode(summary) else {
            return
        }
        let context = ["mobileSummary": data]
        try? session.updateApplicationContext(context)
        session.transferCurrentComplicationUserInfo(context)
    }

    func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {}

    func sessionDidBecomeInactive(_ session: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
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

struct MobileServerSettingsView: View {
    let tokenStore: MobileTokenStore
    let period: String
    let onSaved: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var baseURLString: String
    @State private var token: String
    @State private var status: SettingsStatus?
    @State private var isTesting = false

    init(tokenStore: MobileTokenStore, period: String, onSaved: @escaping () -> Void) {
        self.tokenStore = tokenStore
        self.period = period
        self.onSaved = onSaved
        let form = MobileSummaryRuntimeConfig.settingsForm(tokenStore: tokenStore)
        self._baseURLString = State(initialValue: form.baseURLString)
        self._token = State(initialValue: form.token)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("服务") {
                    TextField("Server URL", text: $baseURLString)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField("Token", text: $token)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }

                Section {
                    Button {
                        save()
                    } label: {
                        Label("保存", systemImage: "tray.and.arrow.down")
                    }

                    Button {
                        Task {
                            await testConnection()
                        }
                    } label: {
                        if isTesting {
                            Label("测试中", systemImage: "arrow.triangle.2.circlepath")
                        } else {
                            Label("测试连接", systemImage: "network")
                        }
                    }
                    .disabled(isTesting)
                }

                if let status {
                    Section {
                        Label(status.message, systemImage: status.systemImage)
                            .foregroundStyle(status.color)
                    }
                }
            }
            .navigationTitle("服务设置")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("关闭") {
                        dismiss()
                    }
                }
            }
        }
    }

    private func save() {
        do {
            _ = try saveCurrentSettings()
            status = .success("已保存，正在刷新数据")
            onSaved()
        } catch MobileRuntimeConfigurationError.invalidBaseURL {
            status = .failure("服务地址格式不正确")
        } catch MobileRuntimeConfigurationError.missingToken {
            status = .failure("请填写 token")
        } catch MobileRuntimeConfigurationError.nonProductionServer {
            status = .failure("当前服务地址不受信任。请使用 HTTPS 域名；HTTP、localhost、内网 IP 和裸 IP 仅限开发调试。")
        } catch {
            status = .failure("保存失败，请重试")
        }
    }

    private func testConnection() async {
        isTesting = true
        defer { isTesting = false }
        do {
            let config = try saveCurrentSettings()
            _ = try await MobileSummaryAPIClient(config: config).load()
            status = .success("连接成功")
            onSaved()
        } catch MobileRuntimeConfigurationError.invalidBaseURL {
            status = .failure("服务地址格式不正确")
        } catch MobileRuntimeConfigurationError.missingToken {
            status = .failure("请填写 token")
        } catch MobileRuntimeConfigurationError.nonProductionServer {
            status = .failure("当前服务地址不受信任。请使用 HTTPS 域名；HTTP、localhost、内网 IP 和裸 IP 仅限开发调试。")
        } catch {
            status = .failure("连接失败，请检查服务地址或 token")
        }
    }

    private func saveCurrentSettings() throws -> MobileSummaryAPIConfig {
        try MobileSummaryRuntimeConfig.saveSettings(
            baseURLString: baseURLString,
            token: token,
            period: period.isEmpty ? MobileSummaryRuntimeConfig.initialPeriod() : period,
            tokenStore: tokenStore
        )
    }
}

private struct SettingsStatus: Equatable {
    let message: String
    let isSuccess: Bool

    static func success(_ message: String) -> SettingsStatus {
        SettingsStatus(message: message, isSuccess: true)
    }

    static func failure(_ message: String) -> SettingsStatus {
        SettingsStatus(message: message, isSuccess: false)
    }

    var systemImage: String {
        isSuccess ? "checkmark.circle.fill" : "exclamationmark.triangle.fill"
    }

    var color: Color {
        isSuccess ? .green : .orange
    }
}

private enum KeychainTokenStoreError: LocalizedError {
    case unhandledStatus(OSStatus)

    var errorDescription: String? {
        switch self {
        case .unhandledStatus(let status):
            return "Token 保存失败（\(status)）"
        }
    }
}

final class KeychainTokenStore: MobileTokenStore, @unchecked Sendable {
    private let service = "com.wangzhipeng.aiusage.mobile"
    private let account = "api-token"

    func readToken() -> String? {
        var query = baseQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        guard status == errSecSuccess,
              let data = item as? Data
        else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    func saveToken(_ token: String?) throws {
        let normalizedToken = token?.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let normalizedToken, !normalizedToken.isEmpty else {
            SecItemDelete(baseQuery() as CFDictionary)
            return
        }

        let data = Data(normalizedToken.utf8)
        let status = SecItemUpdate(
            baseQuery() as CFDictionary,
            [kSecValueData as String: data] as CFDictionary
        )
        if status == errSecSuccess {
            return
        }
        if status == errSecItemNotFound {
            var item = baseQuery()
            item[kSecValueData as String] = data
            let addStatus = SecItemAdd(item as CFDictionary, nil)
            guard addStatus == errSecSuccess else {
                throw KeychainTokenStoreError.unhandledStatus(addStatus)
            }
            return
        }
        throw KeychainTokenStoreError.unhandledStatus(status)
    }

    private func baseQuery() -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account
        ]
    }
}
