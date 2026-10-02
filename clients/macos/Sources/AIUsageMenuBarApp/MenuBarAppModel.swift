import AIUsageMenuBarCore
import Foundation

typealias MenuBarSummaryLoader = @Sendable (MobileSummaryClientConfig) async throws -> MobileSummary
typealias MenuBarRuntimeConfigProvider = @MainActor (RuntimePaths) -> MenuBarRuntimeConfig?
typealias MenuBarNowProvider = @MainActor () -> Date
/// #186 P1 修复（PR #197 Codex 审查）：不能是存一次就不变的 TimeZone 值——用户运行中在系统
/// 设置里切换时区后，界面必须不重启就能反映新时区，所以每次 rebuildState() 都要重新调用它，
/// 而不是缓存 init 时第一次读到的结果。
typealias MenuBarTimeZoneProvider = @MainActor () -> TimeZone

@MainActor
final class MenuBarAppModel: ObservableObject {
    @Published private(set) var summary: MobileSummary
    @Published var selectedPeriodID: String
    @Published private(set) var selectedOffset = 0
    @Published private(set) var todaySummary: MobileSummary?
    @Published private(set) var isLoading = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var config: MenuBarRuntimeConfig?

    /// #177 性能：`state`/`statusState` 曾是计算属性，视图 body 每读一次就重新跑一遍
    /// MenuBarViewModel.build（单帧最多被读 ~18 次）。改成存储属性，只在输入真正变化时
    /// （summary/selectedPeriodID/selectedOffset/todaySummary/config/cachedSummaries）重建一次。
    @Published private(set) var state: MenuBarState
    @Published private(set) var statusState: MenuBarState
    /// 仅供测试观测 rebuildState() 被调用的次数，不参与任何展示逻辑。
    internal private(set) var stateBuildCount = 0

    let paths: RuntimePaths
    private let loadSummary: MenuBarSummaryLoader
    private let loadRuntimeConfig: MenuBarRuntimeConfigProvider
    private let now: MenuBarNowProvider
    /// #186：本机时区提供者——默认 `{ .autoupdatingCurrent }`（每次调用都读当前系统时区，不是
    /// init 时读一次就存住的快照），测试注入固定时区。传给 MenuBarViewModel.build 的「时刻类」
    /// 显示（悬停重置时刻、标题栏/Server 更新时间），不影响仍走 summary.timezone 的「日界类」逻辑。
    private let deviceTimeZoneProvider: MenuBarTimeZoneProvider
    /// #186 P1 修复：系统时区变化的通知 token——运行中用户切换时区会发 NSSystemTimeZoneDidChange，
    /// 必须主动 rebuildState() 一次，否则界面停留在上次读到的时区，直到下一次别的原因触发重建。
    /// `nonisolated(unsafe)`：deinit 是 nonisolated，只在对象销毁、没有并发访问时读这个值，
    /// 安全等价于其他仅在 init/deinit 单点访问一次的资源清理（NSObjectProtocol 本身不是 Sendable）。
    private nonisolated(unsafe) var timeZoneChangeObserver: NSObjectProtocol?
    private let cacheFreshnessInterval: TimeInterval
    private var refreshSequence = 0
    @Published private(set) var hasLoadedUsableSummary: Bool
    private var todayRefreshSequence = 0
    private var cachedSummaries: [String: CachedMenuSummary]
    private var cacheReferenceDate: Date

    init(
        paths: RuntimePaths,
        config: MenuBarRuntimeConfig?,
        cachedSummary: MobileSummary? = nil,
        cachedSummaries: [String: CachedMenuSummary] = [:],
        cacheFreshnessInterval: TimeInterval = 300,
        now: @escaping MenuBarNowProvider = { Date() },
        deviceTimeZoneProvider: @escaping MenuBarTimeZoneProvider = { .autoupdatingCurrent },
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
        self.cacheReferenceDate = now()
        self.deviceTimeZoneProvider = deviceTimeZoneProvider
        self.cacheFreshnessInterval = max(cacheFreshnessInterval, 0)
        var periodSummaries = cachedSummaries.filter { Self.isUsableCache($0.value, key: $0.key, now: now()) }
        if let cachedSummary, periodSummaries[cachedSummary.period.id] == nil {
            periodSummaries[cachedSummary.period.id] = CachedMenuSummary(summary: cachedSummary, fetchedAt: Date.distantPast)
        }
        self.cachedSummaries = periodSummaries
        let initialPeriodID = MenuPeriodSelection(periodID: config?.defaultPeriod ?? "today").periodID
        self.selectedPeriodID = initialPeriodID
        self.summary = periodSummaries[initialPeriodID]?.summary ?? MobileSummary.empty(periodID: initialPeriodID)
        self.todaySummary = periodSummaries["today"]?.summary
        self.hasLoadedUsableSummary = periodSummaries[initialPeriodID] != nil
        // Swift 两阶段初始化：state/statusState 必须先有值才能调用 self 的方法（rebuildState()
        // 内部要读 self.summary 等）。这里给一个占位空状态，随即在下面用 rebuildState() 覆盖成真值。
        let placeholder = MenuBarViewModel.build(from: .empty(), selectedPeriodID: "today")
        self.state = placeholder
        self.statusState = placeholder
        rebuildState()

        // #186 P1 修复：系统时区变化不会自己让已经算好的 state 重新渲染——必须主动订阅
        // NSSystemTimeZoneDidChange 并触发一次 rebuildState()，否则用户切换时区后菜单栏
        // 停留在旧时区，直到下一次因为别的原因（如定时器刷新数据）恰好重建。
        self.timeZoneChangeObserver = NotificationCenter.default.addObserver(
            forName: .NSSystemTimeZoneDidChange, object: nil, queue: .main
        ) { [weak self] _ in
            Task { @MainActor in
                self?.rebuildState()
            }
        }
    }

    deinit {
        if let timeZoneChangeObserver {
            NotificationCenter.default.removeObserver(timeZoneChangeObserver)
        }
    }

    /// #177 性能：唯一负责重算 state/statusState 的入口——只在 summary / selectedPeriodID /
    /// selectedOffset / todaySummary / config / cachedSummaries 真正变化后调用一次，
    /// 不再让每次视图 body 读 model.state 都触发一次 MenuBarViewModel.build。
    private func rebuildState() {
        stateBuildCount += 1
        // #186 P1 修复：每次重建都重新调用 provider，而不是读一个 init 时缓存的属性——
        // 否则用户运行中切换系统时区，provider 早就会返回新值，但这里如果还是读旧的存储属性，
        // 界面依然不会变。
        let deviceTimeZone = deviceTimeZoneProvider()
        state = MenuBarViewModel.build(
            from: summary,
            selectedPeriodID: selectedPeriodID,
            selectedOffset: selectedOffset,
            now: now(),
            machineAliases: config?.machineAliases,
            quotaSlots: latestQuotaProviderSlots(),
            additionalSources: otherKnownSources(),
            deviceTimeZone: deviceTimeZone
        )
        statusState = MenuBarViewModel.build(
            from: todaySummary ?? .empty(),
            selectedPeriodID: "today",
            machineAliases: config?.machineAliases,
            deviceTimeZone: deviceTimeZone
        )
    }

    /// 额度圆环必须来自当前所有已知 summary 快照中 generatedAt 最新的一份，
    /// 不能随所选历史周期（selectedPeriodID/offset）而回退到那份快照缓存的旧额度。
    private func latestQuotaProviderSlots() -> [MobileProviderSlot] {
        var candidates: [(Date, [MobileProviderSlot])] = []
        if let generatedAt = Self.parseGeneratedAt(summary.generatedAt) {
            candidates.append((generatedAt, summary.providerSlots))
        }
        if let today = todaySummary, let generatedAt = Self.parseGeneratedAt(today.generatedAt) {
            candidates.append((generatedAt, today.providerSlots))
        }
        for key in cachedSummaries.keys.sorted() {
            guard let cached = cachedSummaries[key],
                  let generatedAt = Self.parseGeneratedAt(cached.summary.generatedAt) else { continue }
            candidates.append((generatedAt, cached.summary.providerSlots))
        }
        guard let latest = candidates.max(by: { $0.0 < $1.0 }) else {
            return summary.providerSlots
        }
        return latest.1
    }

    /// #177 真机反馈：标题栏「HH:mm 更新」不能只看所选 summary 自己的 sources——
    /// 切到历史周期后必须仍反映设备实际最新一次同步（可能体现在 todaySummary 或其他缓存里），
    /// 与 latestQuotaProviderSlots 同一思路，但这里要「所有」sources 而不是只挑最新一份。
    private func otherKnownSources() -> [MobileSource] {
        var sources = todaySummary?.sources ?? []
        for cached in cachedSummaries.values {
            sources.append(contentsOf: cached.summary.sources)
        }
        return sources
    }

    // 与 MenuBarViewModel 同样的理由：ISO8601DateFormatter 构造本身有实测开销，
    // 每次 latestQuotaProviderSlots() 会对 summary/todaySummary/所有 cachedSummaries 各解析一次，
    // 缓存复用而不是每次 new。调用全部发生在 @MainActor 同步路径内。
    nonisolated(unsafe) private static let generatedAtFormatterFractional: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()
    nonisolated(unsafe) private static let generatedAtFormatterBasic: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private static func parseGeneratedAt(_ iso: String?) -> Date? {
        guard let iso else { return nil }
        if let date = generatedAtFormatterFractional.date(from: iso) {
            return date
        }
        return generatedAtFormatterBasic.date(from: iso)
    }

    var hasConfig: Bool {
        config != nil
    }

    var selection: MenuPeriodSelection { MenuPeriodSelection(periodID: selectedPeriodID, offset: selectedOffset) }

    /// #176：期间菜单展开数据——只读已有缓存（内存优先，磁盘退路），绝不调用 loadSummary / 发网络请求。
    func periodMenuRows(for periodID: String) -> [PeriodMenuRow] {
        PeriodMenuBuilder.rows(
            periodID: periodID,
            now: now(),
            timezone: summary.timezone ?? todaySummary?.timezone,
            selectedOffset: periodID == selectedPeriodID ? selectedOffset : 0,
            cached: { [cachedSummaries, paths] selection in
                if let cached = cachedSummaries[selection.cacheKey] {
                    return cached.summary
                }
                return SummaryCache.loadCachedSummary(
                    from: paths.cacheURL(forPeriod: selection.periodID, offset: selection.offset)
                )?.summary
            }
        )
    }

    func refresh(periodID: String? = nil, offset: Int? = nil, force: Bool = false) {
        reindexCachesAfterServiceDayChanges()
        let selected = MenuPeriodSelection(
            periodID: periodID ?? selectedPeriodID,
            offset: offset ?? (periodID == nil ? selectedOffset : 0)
        )
        selectedPeriodID = selected.periodID
        selectedOffset = selected.offset
        // Invalidate before every cache fast path as well as network requests.
        refreshSequence += 1
        let sequence = refreshSequence
        if selected == MenuPeriodSelection(periodID: "today") { todayRefreshSequence += 1 }
        let cached = cachedSummaries[selected.cacheKey] ?? SummaryCache.loadCachedSummary(
            from: paths.cacheURL(forPeriod: selected.periodID, offset: selected.offset)
        )
        if let cached, Self.isUsableCache(cached, key: selected.cacheKey, now: now()) {
            summary = cached.summary
            hasLoadedUsableSummary = true
            if !force && isFresh(cached) {
                isLoading = false
                errorMessage = nil
                rebuildState()
                return
            }
        } else {
            summary = .empty(periodID: selected.periodID)
            hasLoadedUsableSummary = false
            if selected == MenuPeriodSelection(periodID: "today") { todaySummary = nil }
        }
        let runtimeConfig = loadRuntimeConfig(paths) ?? config
        config = runtimeConfig
        rebuildState()
        guard let runtimeConfig, let baseURL = URL(string: runtimeConfig.serverURL) else {
            isLoading = false
            errorMessage = "需要配置服务地址"
            return
        }
        isLoading = true
        errorMessage = nil
        let loader = loadSummary
        let requestedAt = now()
        let requestTimezone = summary.timezone ?? todaySummary?.timezone
        Task {
            do {
                let loaded = try await loader(MobileSummaryClientConfig(
                    baseURL: baseURL, bearerToken: runtimeConfig.token,
                    period: selected.periodID, offset: selected.offset
                ))
                guard sequence == self.refreshSequence, selected == self.selection else { return }
                guard loaded.period.id == selected.periodID else { throw MobileSummaryClientError.invalidResponse }
                guard Self.sameServiceDay(requestedAt, self.now(), timezone: loaded.timezone) else {
                    self.refresh(force: true)
                    return
                }
                let displayed = Self.summaryKeepingLastSuccessfulQuota(
                    loaded, fallback: self.cachedSummaries[selected.cacheKey]?.summary
                )
                self.summary = displayed
                self.hasLoadedUsableSummary = true
                self.errorMessage = nil
                self.store(displayed, for: selected)
            } catch {
                guard sequence == self.refreshSequence, selected == self.selection else { return }
                if !Self.sameServiceDay(requestedAt, self.now(), timezone: requestTimezone) {
                    self.expireRelativeCachesAfterMidnight()
                }
                let prefix = self.hasLoadedUsableSummary ? "刷新失败，正在显示缓存" : "读取失败"
                self.errorMessage = "\(prefix)：\(Self.shortError(error))"
            }
            if sequence == self.refreshSequence { self.isLoading = false }
        }
    }

    /// 用户手动「立即同步」：标题栏按钮与 ⋯ 菜单共用。行为不变——无条件强刷当前选中期。
    /// 选中今天时 refreshToday 本身会强制刷新当前期，不能再额外 refresh，避免重复请求。
    func syncNow() {
        if selection != MenuPeriodSelection(periodID: "today") { refresh(force: true) }
        refreshToday()
    }

    /// #191（PR #191 Codex 审查 P1）：定时器专用入口，取代原来 startRefreshTimer 里直接调用
    /// syncNow() + prefetchCommonPeriods()。syncNow() 对非 today 的当前选中期是无条件
    /// force refresh，如果面板停在 week/month（offset 0）不动，每轮定时器仍会绕过 #190 加的
    /// 预取节流重新扫描——syncNow 的 refresh(force:true) 和 prefetchCommonPeriods 用的是同一个
    /// cachedSummaries["week"/"month"] 缓存位，但 syncNow 完全不查询它就强制发请求。
    /// timerTick 把「当前选中的非 today 期」也纳入同一套 prefetchMinimumInterval 节流：
    /// - 选中期恰好是 week/month 且 offset 为 0（即 prefetchCommonPeriods 本来就会覆盖的那份
    ///   缓存）：不重复处理，交给下面的 prefetchCommonPeriods 统一节流，避免同一 tick 内对
    ///   同一 cacheKey 发两次请求。
    /// - 其余情况（历史 offset、或非 week/month 期间）：按 isPrefetchFresh 同样的新鲜度规则
    ///   判断是否需要 force refresh。
    /// 手动「立即同步」按钮/菜单继续调用 syncNow()，行为不变（无条件强刷）。
    func timerTick() {
        refreshToday()
        let selected = selection
        if selected != MenuPeriodSelection(periodID: "today") {
            let coveredByPrefetch = selected.offset == 0
                && (selected.periodID == "week" || selected.periodID == "month")
            if !coveredByPrefetch {
                let cached = cachedSummaries[selected.cacheKey]
                if cached == nil || !isPrefetchFresh(cached!) {
                    refresh(force: true)
                }
            }
        }
        prefetchCommonPeriods()
    }

    // The menu bar continues to show today's value while the popover browses history.
    func refreshToday() {
        reindexCachesAfterServiceDayChanges()
        if selection == MenuPeriodSelection(periodID: "today") {
            refresh(force: true)
            return
        }
        guard let runtimeConfig = loadRuntimeConfig(paths) ?? config,
              let baseURL = URL(string: runtimeConfig.serverURL) else { return }
        if let cached = cachedSummaries["today"], !Self.isSameCacheDay(cached, now: now()) {
            todaySummary = nil
            rebuildState()
        }
        todayRefreshSequence += 1
        let sequence = todayRefreshSequence
        let loader = loadSummary
        let requestedAt = now()
        let requestTimezone = summary.timezone ?? todaySummary?.timezone
        Task {
            do {
                let loaded = try await loader(MobileSummaryClientConfig(
                    baseURL: baseURL, bearerToken: runtimeConfig.token, period: "today", offset: 0
                ))
                guard sequence == self.todayRefreshSequence else { return }
                guard loaded.period.id == "today" else { throw MobileSummaryClientError.invalidResponse }
                guard Self.sameServiceDay(requestedAt, self.now(), timezone: loaded.timezone) else {
                    self.refreshToday()
                    return
                }
                self.store(loaded, for: MenuPeriodSelection(periodID: "today"))
            } catch {
                guard sequence == self.todayRefreshSequence else { return }
                if !Self.sameServiceDay(requestedAt, self.now(), timezone: requestTimezone) {
                    self.expireRelativeCachesAfterMidnight()
                }
            }
        }
    }

    /// #190：week/month 后台预取的最小重拉间隔，独立于 cacheFreshnessInterval（用户手动切换/
    /// 打开面板时的展示新鲜度）。定时器刷新间隔通常是 600s，若预取新鲜度复用 300s 的
    /// cacheFreshnessInterval，会导致每轮定时器都重新拉取本周/本月（各自扫数千行事实表），
    /// 把 D1 免费额度的日读取推高到 82.5%。预取只是为了让面板打开时命中缓存，不必跟随
    /// 定时器频率，1 小时刷新一次即可。
    private static let prefetchMinimumInterval: TimeInterval = 3600

    private func isPrefetchFresh(_ cached: CachedMenuSummary) -> Bool {
        let age = now().timeIntervalSince(cached.fetchedAt)
        return age >= 0 && age < Self.prefetchMinimumInterval && Self.isSameCacheDay(cached, now: now())
    }

    /// 后台预取常用历史周期（本周、本月），确保呈现时 100% 瞬时读取本地库。
    /// 低频：仅当缓存不存在、缓存已超过 prefetchMinimumInterval，或跨了服务日时才请求。
    func prefetchCommonPeriods() {
        guard let runtimeConfig = loadRuntimeConfig(paths) ?? config,
              let baseURL = URL(string: runtimeConfig.serverURL) else { return }
        let periods = ["week", "month"]
        let loader = loadSummary
        for period in periods {
            if let cached = cachedSummaries[period], isPrefetchFresh(cached) {
                continue
            }
            let requestedAt = now()
            Task {
                do {
                    let loaded = try await loader(MobileSummaryClientConfig(
                        baseURL: baseURL, bearerToken: runtimeConfig.token, period: period, offset: 0
                    ))
                    guard loaded.period.id == period else { return }
                    // #191（PR #191 Codex 审查 P2）：与 refresh()/refreshToday() 同样的道理——
                    // 请求发起和响应落地之间如果跨了服务日（上海时区午夜），这份响应描述的是
                    // 「跨日前」的本周/本月，写进缓存会让新的一天里继续展示过期统计，且因为
                    // fetchedAt 是刚写入的「新」时间戳，还会被 isPrefetchFresh 误判成新鲜、
                    // 挡住下一轮本该立即重新请求的预取。直接丢弃，不 store，让下一次
                    // prefetchCommonPeriods 因为缓存缺失/跨日而重新请求。
                    guard Self.sameServiceDay(requestedAt, self.now(), timezone: loaded.timezone) else { return }
                    let selected = MenuPeriodSelection(periodID: period)
                    // reviewer 在 #191 收口前发现：store() 只写 cachedSummaries，不会更新
                    // self.summary（rebuildState() 读的是 self.summary）。timerTick() 把
                    // 「当前选中的 week/month（offset 0）」完全交给这里节流后，如果面板正停
                    // 在该期间上，必须像 refresh() 成功回调一样同步刷新 self.summary，
                    // 否则面板会一直显示旧数字，直到关闭重开才重新读到缓存。
                    if self.selection == selected {
                        let displayed = Self.summaryKeepingLastSuccessfulQuota(
                            loaded, fallback: self.cachedSummaries[selected.cacheKey]?.summary
                        )
                        self.summary = displayed
                        self.hasLoadedUsableSummary = true
                        self.errorMessage = nil
                        self.store(displayed, for: selected)
                    } else {
                        self.store(loaded, for: selected)
                    }
                } catch {
                    // 后台静默预取失败不打扰用户
                }
            }
        }
    }

    private func reindexCachesAfterServiceDayChanges() {
        guard !Self.sameServiceDay(cacheReferenceDate, now(), timezone: summary.timezone ?? todaySummary?.timezone) else { return }
        expireRelativeCachesAfterMidnight()
    }

    private func expireRelativeCachesAfterMidnight() {
        let currentTime = now()
        cacheReferenceDate = currentTime
        var dated = SummaryCache.loadSummaries(paths: paths, now: currentTime)
        for (key, cached) in cachedSummaries where Self.isSameCacheDay(cached, now: currentTime) {
            dated[key] = cached
        }
        for cached in cachedSummaries.values {
            guard cached.dateIndexed, let selected = SummaryCache.selection(for: cached.summary, now: currentTime), selected.offset < 0 else { continue }
            if let previous = dated[selected.cacheKey], previous.fetchedAt >= cached.fetchedAt { continue }
            dated[selected.cacheKey] = cached
        }
        cachedSummaries = dated
        todaySummary = cachedSummaries["today"]?.summary
        if let current = cachedSummaries[selection.cacheKey] {
            summary = current.summary
            hasLoadedUsableSummary = true
        } else {
            summary = .empty(periodID: selectedPeriodID)
            hasLoadedUsableSummary = false
        }
        rebuildState()
    }

    private func store(_ summary: MobileSummary, for selected: MenuPeriodSelection) {
        cachedSummaries[selected.cacheKey] = CachedMenuSummary(summary: summary, fetchedAt: now(), dateIndexed: true)
        if selected == MenuPeriodSelection(periodID: "today") { todaySummary = summary }
        try? SummaryCache.save(summary, paths: paths, offset: selected.offset)
        rebuildState()
    }

    private static func isUsableCache(_ cached: CachedMenuSummary, key: String, now: Date) -> Bool {
        if isSameCacheDay(cached, now: now) { return true }
        let parts = key.split(separator: ":")
        guard cached.dateIndexed, parts.count == 2, let offset = Int(parts[1]), offset < 0 else { return false }
        return PeriodMenuBuilder.matches(cached.summary, selection: MenuPeriodSelection(periodID: String(parts[0]), offset: offset), now: now)
    }

    private static func isSameCacheDay(_ cached: CachedMenuSummary, now: Date) -> Bool {
        // Relative offsets change meaning at midnight in the service's timezone.
        cached.fetchedAt == .distantPast || sameServiceDay(cached.fetchedAt, now, timezone: cached.summary.timezone)
    }

    private static func sameServiceDay(_ first: Date, _ second: Date, timezone: String?) -> Bool {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: timezone ?? "Asia/Shanghai") ?? TimeZone(secondsFromGMT: 8 * 3600)!
        return calendar.isDate(first, inSameDayAs: second)
    }

    private func isFresh(_ cached: CachedMenuSummary) -> Bool {
        let age = now().timeIntervalSince(cached.fetchedAt)
        let interval = selection.offset < 0 ? Self.prefetchMinimumInterval : cacheFreshnessInterval
        return age >= 0 && age < interval && Self.isUsableCache(cached, key: selection.cacheKey, now: now())
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
        return SafeNetworkErrorMessage.message(error)
    }
}
