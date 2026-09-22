import AIUsageMobileCore
import BackgroundTasks
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
        .backgroundTask(.appRefresh(WatchSummaryBackgroundRefresh.taskIdentifier)) {
            await WatchSummaryBackgroundRefresh.run(tokenStore: KeychainTokenStore())
        }
    }
}

enum WatchSummaryBackgroundRefresh {
    static let taskIdentifier = "com.wangzhipeng.aiusage.mobile.watch-refresh"
    private static let refreshInterval: TimeInterval = 30 * 60

    static func schedule() {
        let request = BGAppRefreshTaskRequest(identifier: taskIdentifier)
        request.earliestBeginDate = Date(timeIntervalSinceNow: refreshInterval)
        try? BGTaskScheduler.shared.submit(request)
    }

    static func run(tokenStore: MobileTokenStore) async {
        defer { schedule() }
        guard let config = MobileSummaryRuntimeConfig.makeAPIConfig(
            period: MobileSummaryCache.companionPeriodID,
            tokenStore: tokenStore
        ) else {
            MobileRuntimeDiagnostics.configurationRequired(
                period: MobileSummaryCache.companionPeriodID,
                refreshSource: .backgroundAppRefresh
            )
            return
        }
        let loadedSummary: MobileSummary
        do {
            loadedSummary = try await MobileSummaryAPIClient(config: config).load()
        } catch {
            MobileRuntimeDiagnostics.failure(
                period: MobileSummaryCache.companionPeriodID,
                config: config,
                error: error,
                refreshSource: .backgroundAppRefresh
            )
            return
        }
        guard MobileSummaryCache.isCompanionEligible(loadedSummary) else {
            return
        }
        let cacheWriteResult = MobileSummaryCache.writeToAppGroup(loadedSummary)
        let watchPushResult = WatchSummaryBridge.shared.push(loadedSummary)
        MobileRuntimeDiagnostics.success(
            config: config,
            summary: loadedSummary,
            refreshSource: .backgroundAppRefresh,
            cacheWriteResult: cacheWriteResult,
            watchPushStatus: watchPushResult.status.rawValue,
            watchPushReason: watchPushResult.reason.rawValue
        )
    }
}

struct LiveSummaryContainerView: View {
    let initialTabID: String
    private let usesDeterministicFixture: Bool
    @Environment(\.scenePhase) private var scenePhase
    private let tokenStore = KeychainTokenStore()
    @State private var history: MobileHistoryState
    @State private var loadState: LoadState
    @State private var isShowingSettings = false
    @State private var hasCompletedInitialLoad = false
    private var summary: MobileSummary { history.summary }

    init(initialTabID: String) {
        let initialPeriod = ["today", "week", "month"].contains(initialTabID)
            ? initialTabID : MobileSummaryRuntimeConfig.initialPeriod()
        self.initialTabID = initialPeriod
        #if DEBUG
        let fixtureEnabled = ProcessInfo.processInfo.environment["AI_USAGE_DETERMINISTIC_FIXTURE"] == "1"
        #else
        let fixtureEnabled = false
        #endif
        self.usesDeterministicFixture = fixtureEnabled
        self._history = State(initialValue: MobileHistoryState(
            selection: MobileHistorySelection(period: initialPeriod),
            summary: fixtureEnabled ? MobileSummary.deterministicTrendFixture(periodID: initialPeriod) : nil
        ))
        self._loadState = State(initialValue: fixtureEnabled ? .live : .loading(period: initialPeriod))
    }

    var body: some View {
        AIUsageMobileRootView(
            summary: summary,
            initialTabID: initialTabID,
            refreshingPeriodID: loadState.refreshingPeriodID,
            selectedOffset: history.selection.offset,
            onOffsetSelected: { offset in
                select(MobileHistorySelection(period: history.selection.period, offset: offset))
            },
            onPeriodSelected: { period in
                select(MobileHistorySelection(period: period))
            },
            onRefreshAsync: { _ in
                guard !usesDeterministicFixture else { return }
                await refreshLiveSummary(refreshSource: .pullToRefresh)
            },
            onSettingsTapped: { isShowingSettings = true }
        )
        .overlay(alignment: .top) {
            if let message = loadState.message {
                ProductionConnectionStatusView(message: message)
                    .padding(.top, 8).padding(.horizontal, 14)
            }
        }
        .sheet(isPresented: $isShowingSettings) {
            MobileServerSettingsView(tokenStore: tokenStore, period: history.selection.period) {
                Task { await refreshLiveSummary(refreshSource: .settingsTriggeredRefresh) }
            }
        }
        .task {
            guard !usesDeterministicFixture else {
                hasCompletedInitialLoad = true
                return
            }
            WatchSummaryBackgroundRefresh.schedule()
            await refreshLiveSummary(refreshSource: .foregroundInitialLoad)
            await ensureTodayCompanionSummary()
            hasCompletedInitialLoad = true
        }
        .onChange(of: scenePhase) { _, phase in
            guard !usesDeterministicFixture, phase == .active, hasCompletedInitialLoad else { return }
            Task {
                await refreshLiveSummary(refreshSource: .foregroundInitialLoad)
                await ensureTodayCompanionSummary()
            }
        }
    }

    private func select(_ selection: MobileHistorySelection) {
        let requestID = history.begin(selection)
        if usesDeterministicFixture {
            history.accept(MobileSummary.deterministicTrendFixture(periodID: selection.period), requestID: requestID)
            return
        }
        loadState = .loading(period: selection.period)
        Task { await loadLiveSummary(selection: selection, requestID: requestID, refreshSource: .foregroundInitialLoad) }
    }

    private func refreshLiveSummary(refreshSource: MobileRefreshSource) async {
        let selection = history.selection
        let requestID = history.begin(selection)
        loadState = .loading(period: selection.period)
        await loadLiveSummary(selection: selection, requestID: requestID, refreshSource: refreshSource)
    }

    private func loadLiveSummary(selection: MobileHistorySelection, requestID: UUID, refreshSource: MobileRefreshSource) async {
        let period = selection.period
        guard let config = MobileSummaryRuntimeConfig.makeAPIConfig(
            period: period, offset: selection.offset, tokenStore: tokenStore
        ) else {
            guard history.requestID == requestID else { return }
            MobileRuntimeDiagnostics.configurationRequired(period: period, refreshSource: refreshSource)
            loadState = .configurationRequired
            return
        }
        do {
            let loadedSummary = try await MobileSummaryAPIClient(config: config).load()
            guard history.requestID == requestID else { return }
            guard loadedSummary.period.id == period else { throw MobileSummaryAPIError.invalidResponse }
            guard history.accept(loadedSummary, requestID: requestID) else {
                // The service's relative dates changed while this request was in flight.
                await refreshLiveSummary(refreshSource: refreshSource)
                return
            }
            let companionEvidence = selection.isCurrentDay
                ? shareWithCompanionIfNeeded(loadedSummary)
                : CompanionShareEvidence(cacheWriteResult: nil, watchPushResult: nil)
            MobileRuntimeDiagnostics.success(
                config: config, summary: loadedSummary, refreshSource: refreshSource,
                cacheWriteResult: companionEvidence.cacheWriteResult,
                watchPushStatus: companionEvidence.watchPushResult?.status.rawValue,
                watchPushReason: companionEvidence.watchPushResult?.reason.rawValue
            )
            withAnimation(.snappy(duration: 0.25)) { loadState = .live }
        } catch {
            guard history.fail(requestID: requestID) else { return }
            MobileRuntimeDiagnostics.failure(period: period, config: config, error: error, refreshSource: refreshSource)
            loadState = .failed
        }
    }

    private func shareWithCompanionIfNeeded(_ loadedSummary: MobileSummary) -> CompanionShareEvidence {
        guard MobileSummaryCache.isCompanionEligible(loadedSummary) else {
            return CompanionShareEvidence(cacheWriteResult: nil, watchPushResult: nil)
        }
        let cacheWriteResult = MobileSummaryCache.writeToAppGroup(loadedSummary)
        let watchPushResult = WatchSummaryBridge.shared.push(loadedSummary)
        WatchSummaryBackgroundRefresh.schedule()
        return CompanionShareEvidence(cacheWriteResult: cacheWriteResult, watchPushResult: watchPushResult)
    }

    private func ensureTodayCompanionSummary() async {
        guard !history.selection.isCurrentDay else { return }
        guard let config = MobileSummaryRuntimeConfig.makeAPIConfig(
            period: MobileSummaryCache.companionPeriodID, offset: 0, tokenStore: tokenStore
        ) else { return }
        do {
            let loadedSummary = try await MobileSummaryAPIClient(config: config).load()
            let companionEvidence = shareWithCompanionIfNeeded(loadedSummary)
            MobileRuntimeDiagnostics.success(
                config: config, summary: loadedSummary, refreshSource: .companionTodayEnsure,
                cacheWriteResult: companionEvidence.cacheWriteResult,
                watchPushStatus: companionEvidence.watchPushResult?.status.rawValue,
                watchPushReason: companionEvidence.watchPushResult?.reason.rawValue
            )
        } catch {
            MobileRuntimeDiagnostics.failure(
                period: MobileSummaryCache.companionPeriodID, config: config,
                error: error, refreshSource: .companionTodayEnsure
            )
        }
    }
}

private struct CompanionShareEvidence {
    let cacheWriteResult: MobileSummaryCacheWriteResult?
    let watchPushResult: WatchPushResult?
}

struct WatchPushResult: Equatable {
    let status: WatchPushStatus
    let reason: WatchPushReason
}

enum WatchPushStatus: String {
    case queued
    case failed
}

enum WatchPushReason: String {
    case updateApplicationContextQueued = "update_application_context_queued"
    case unsupported
    case sessionUnavailable = "session_unavailable"
    case inactiveActivationState = "inactive_activation_state"
    case encodeFailed = "encode_failed"
    case updateApplicationContextFailed = "update_application_context_failed"
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

    func push(_ summary: MobileSummary) -> WatchPushResult {
        guard WCSession.isSupported() else {
            return WatchPushResult(status: .failed, reason: .unsupported)
        }
        guard let session else {
            return WatchPushResult(status: .failed, reason: .sessionUnavailable)
        }
        guard session.activationState == .activated else {
            return WatchPushResult(status: .failed, reason: .inactiveActivationState)
        }
        let data: Data
        do {
            data = try JSONEncoder().encode(summary)
        } catch {
            return WatchPushResult(status: .failed, reason: .encodeFailed)
        }
        let context = ["mobileSummary": data]
        do {
            try session.updateApplicationContext(context)
        } catch {
            return WatchPushResult(status: .failed, reason: .updateApplicationContextFailed)
        }
        session.transferCurrentComplicationUserInfo(context)
        return WatchPushResult(status: .queued, reason: .updateApplicationContextQueued)
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
