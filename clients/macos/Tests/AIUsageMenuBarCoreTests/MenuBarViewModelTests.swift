import XCTest
@testable import AIUsageMenuBarCore

final class MenuBarViewModelTests: XCTestCase {
    func testBuildsCompactStatusAndPopoverSections() throws {
        let summary = try loadFixture()

        let state = MenuBarViewModel.build(
            from: summary,
            selectedPeriodID: "week",
            now: try date("2026-06-02T11:00:00+08:00")
        )

        XCTAssertEqual(state.statusTitle, "5.0K")
        XCTAssertEqual(state.periodLabel, "本周")
        XCTAssertEqual(state.dateRangeText, "2026-05-27 ～ 2026-06-02")
        XCTAssertEqual(state.heroTotalText, "5.0K")
        XCTAssertEqual(state.tokenBreakdownText, "输入 2.8K · 输出 1.4K · Cache 800")
        XCTAssertEqual(state.healthText, "2/2 正常")
        XCTAssertEqual(state.primaryLimitText, "暂无可信额度")
        XCTAssertTrue(state.lastUpdatedText.hasSuffix("前"), "Expected relative time, got: \(state.lastUpdatedText)")
        XCTAssertEqual(state.sources.map(\.title), ["linux-dev", "macbook-pro"])
        XCTAssertEqual(state.sources.first?.subtitle, "来源明细缺失")
        XCTAssertTrue(state.limitRows.isEmpty)
        XCTAssertEqual(state.quotaRings.map(\.id), ["claude", "codex"])
        XCTAssertTrue(state.quotaRings.allSatisfy { ring in
            ring.outerPctText == "--" && ring.innerPctText == "--" &&
                ring.outerTimeText == "--" && ring.innerTimeText == "--"
        })
        XCTAssertTrue(state.providerUsageCoverageText?.contains("未知") == true)
        XCTAssertEqual(state.breakdownSections.map(\.title), ["机器", "账户", "Agent", "模型", "日期"])
        XCTAssertEqual(state.breakdownSections.first?.rows.map(\.title), ["linux-dev", "macbook-pro"])
        XCTAssertEqual(state.breakdownSections.first?.rows.first?.subtitle, "1 个来源")
        XCTAssertEqual(state.trendBars.map(\.label), ["06-01", "06-02"])
        XCTAssertEqual(state.trendBars.last?.ratio, 1.0)
    }

    func testLegacySharedMachineKeepsServerAggregateWithoutSplittingContributions() throws {
        let summary = try loadFixture()
        let sharedSources = [
            MobileSource(
                sourceID: "linux-biai-wang",
                machine: "ip-10-50-128-30.eu-west-1.compute.internal",
                osUser: "wang",
                platform: "linux",
                displayName: nil,
                status: "ok",
                lastObservedAt: "2026-06-02T10:40:00+08:00",
                lastPushedAt: "2026-06-02T10:40:00+08:00",
                errorMessage: nil
            ),
            MobileSource(
                sourceID: "linux-biai-wangDS",
                machine: "ip-10-50-128-30.eu-west-1.compute.internal",
                osUser: "wangDS",
                platform: "linux",
                displayName: nil,
                status: "ok",
                lastObservedAt: "2026-06-02T10:40:00+08:00",
                lastPushedAt: "2026-06-02T10:40:00+08:00",
                errorMessage: nil
            ),
            MobileSource(
                sourceID: "linux-biai-wangANT",
                machine: "ip-10-50-128-30.eu-west-1.compute.internal",
                osUser: "wangANT",
                platform: "linux",
                displayName: nil,
                status: "ok",
                lastObservedAt: "2026-06-02T10:40:00+08:00",
                lastPushedAt: "2026-06-02T10:40:00+08:00",
                errorMessage: nil
            ),
        ]
        let sharedBreakdown = MobileBreakdown(
            byMachine: [
                MobileBreakdownRow(
                    id: "ip-10-50-128-30.eu-west-1.compute.internal",
                    label: "ip-10-50-128-30.eu-west-1.compute.internal",
                    tokens: 800_000,
                    sourceIDs: ["linux-biai-wang", "linux-biai-wangDS", "linux-biai-wangANT"],
                    contributions: [
                        MobileBreakdownContribution(sourceID: "linux-biai-wang", tokens: 500_000),
                        MobileBreakdownContribution(sourceID: "linux-biai-wangDS", tokens: 300_000),
                        MobileBreakdownContribution(sourceID: "linux-biai-wangANT", tokens: 0),
                    ]
                )
            ],
            byOSUser: summary.breakdown.byOSUser,
            byAgent: summary.breakdown.byAgent,
            byModel: summary.breakdown.byModel,
            byDate: summary.breakdown.byDate
        )
        let sharedMachineSummary = MobileSummary(
            schemaVersion: summary.schemaVersion,
            client: summary.client,
            generatedAt: summary.generatedAt,
            timezone: summary.timezone,
            period: summary.period,
            trend: summary.trend,
            sources: sharedSources,
            breakdown: sharedBreakdown,
            limits: summary.limits
        )

        let state = MenuBarViewModel.build(
            from: sharedMachineSummary,
            selectedPeriodID: "today",
            now: try date("2026-06-02T11:00:00+08:00")
        )

        XCTAssertEqual(state.sources.count, 1)
        XCTAssertEqual(state.sources.map(\.title), ["ip-10-50-128-30.eu-west-1.compute.internal"])
        XCTAssertEqual(state.sources.map(\.value), ["800.0K"])
        XCTAssertNil(state.sources.first?.agents)
        XCTAssertEqual(state.sources.first?.subtitle, "来源明细缺失")
    }

    func testTrendAxisUsesSparseFullRangeLabelsLikeMobileApp() throws {
        let summary = try loadFixture()
        let hourlyTrend = MobileTrend(
            period: "today",
            granularity: "hour",
            startDate: "2026-06-02",
            endDate: "2026-06-02",
            points: (0..<24).map { hour in
                MobileTrendPoint(
                    bucket: String(format: "2026-06-02T%02d:00:00+08:00", hour),
                    label: String(format: "2026-06-02T%02d:00:00+08:00", hour),
                    tokens: hour + 1,
                    inputTokens: 0,
                    outputTokens: 0,
                    cacheTokens: 0,
                    cacheRatio: 0
                )
            }
        )
        let today = MobileSummary(
            schemaVersion: summary.schemaVersion,
            client: summary.client,
            generatedAt: summary.generatedAt,
            timezone: summary.timezone,
            period: summary.period,
            trend: hourlyTrend,
            sources: summary.sources,
            breakdown: summary.breakdown,
            limits: summary.limits
        )

        let state = MenuBarViewModel.build(
            from: today,
            selectedPeriodID: "today",
            now: try date("2026-06-02T11:00:00+08:00")
        )

        XCTAssertEqual(state.trendBars.count, 24)
        XCTAssertEqual(state.trendBars[0].label, "00:00")
        XCTAssertEqual(state.trendBars[12].label, "12:00")
        XCTAssertEqual(state.trendBars[23].label, "23:00")
        XCTAssertTrue(state.trendBars[1].label.isEmpty)
        XCTAssertEqual(state.trendBars[1].tooltipTitle, "01:00")

        let weeklyTrend = MobileTrend(
            period: "week",
            granularity: "day",
            startDate: "2026-05-28",
            endDate: "2026-06-03",
            points: ["2026-05-28", "2026-05-29", "2026-05-30", "2026-05-31", "2026-06-01", "2026-06-02", "2026-06-03"].enumerated().map { index, bucket in
                MobileTrendPoint(
                    bucket: bucket,
                    label: bucket,
                    tokens: index + 1,
                    inputTokens: 0,
                    outputTokens: 0,
                    cacheTokens: 0,
                    cacheRatio: 0
                )
            }
        )
        let week = MobileSummary(
            schemaVersion: summary.schemaVersion,
            client: summary.client,
            generatedAt: summary.generatedAt,
            timezone: summary.timezone,
            period: summary.period,
            trend: weeklyTrend,
            sources: summary.sources,
            breakdown: summary.breakdown,
            limits: summary.limits
        )
        let weekState = MenuBarViewModel.build(
            from: week,
            selectedPeriodID: "week",
            now: try date("2026-06-02T11:00:00+08:00")
        )
        XCTAssertEqual(weekState.trendBars.map(\.label), ["05-28", "", "", "05-31", "", "", "06-03"])
    }

    func testTrendBarsExposeStableProviderColorSemanticsAndConserveTokens() throws {
        let summary = try loadFixture()
        let trend = MobileTrend(
            period: "today",
            granularity: "hour",
            startDate: "2026-06-02",
            endDate: "2026-06-02",
            points: [
                MobileTrendPoint(
                    bucket: "2026-06-02T10:00:00+08:00",
                    label: "2026-06-02T10:00:00+08:00",
                    tokens: 600,
                    inputTokens: 200,
                    outputTokens: 100,
                    cacheTokens: 300,
                    cacheRatio: 50,
                    claudeTokens: 300,
                    codexTokens: 200,
                    unknownTokens: 100
                )
            ]
        )
        let state = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion,
                client: summary.client,
                generatedAt: summary.generatedAt,
                timezone: summary.timezone,
                period: summary.period,
                trend: trend,
                sources: summary.sources,
                breakdown: summary.breakdown,
                limits: summary.limits
            ),
            selectedPeriodID: "today",
            now: try date("2026-06-02T11:00:00+08:00")
        )

        let bar = try XCTUnwrap(state.trendBars.first)
        XCTAssertEqual(bar.segments.map(\.provider), [.unknown, .claude, .codex])
        XCTAssertEqual(bar.segments.map(\.tokens), [100, 300, 200])
        XCTAssertEqual(bar.segments.reduce(0) { $0 + $1.tokens }, bar.totalTokens)
        XCTAssertEqual(
            MenuTrendProvider.claude.color,
            MenuTrendColor(red: 0.855, green: 0.467, blue: 0.337, opacity: 1)
        )
        XCTAssertEqual(
            MenuTrendProvider.codex.color,
            MenuTrendColor(red: 0.039, green: 0.518, blue: 1, opacity: 1)
        )
        XCTAssertEqual(
            MenuTrendProvider.unknown.color,
            MenuTrendColor(red: 0.5, green: 0.5, blue: 0.52, opacity: 0.55)
        )
    }

    func testTrendWithoutProviderBreakdownDisplaysAllTokensAsUnknown() throws {
        let summary = try loadFixture()
        let state = MenuBarViewModel.build(
            from: summary,
            selectedPeriodID: "week",
            now: try date("2026-06-02T11:00:00+08:00")
        )

        XCTAssertFalse(state.trendBars.isEmpty)
        for bar in state.trendBars {
            XCTAssertEqual(bar.segments.map(\.provider), [.unknown])
            XCTAssertEqual(bar.segments.map(\.tokens), [bar.totalTokens])
        }
    }

    func testQuotaRingsUseLatestObservedUsagePerProviderWindow() throws {
        let summary = try loadFixture()
        let duplicateLimits = MobileLimits(
            observedCount: 4,
            totalCount: 4,
            windows: [
                MobileLimitWindow(
                    sourceID: "claude-main",
                    provider: "claude",
                    window: "session",
                    usedPercent: 92,
                    remainingPercent: 8,
                    resetAt: "2026-05-24T14:40:00+00:00",
                    windowDurationMinutes: 300,
                    observedAt: "2026-06-18T10:00:00+08:00",
                    sourceType: "active_limits_cache",
                    confidence: "observed",
                    status: "ok",
                    official: true
                ),
                MobileLimitWindow(
                    sourceID: "claude-main",
                    provider: "claude",
                    window: "session",
                    usedPercent: 96,
                    remainingPercent: 4,
                    resetAt: "2026-06-19T18:09:00+08:00",
                    windowDurationMinutes: 300,
                    observedAt: "2026-06-19T20:26:45+08:00",
                    sourceType: "official_cli_limit_message",
                    confidence: "observed",
                    status: "ok",
                    official: true
                ),
                MobileLimitWindow(
                    sourceID: "claude-main",
                    provider: "claude",
                    window: "week",
                    usedPercent: 47,
                    remainingPercent: 53,
                    resetAt: "2026-06-21T01:59:00+08:00",
                    windowDurationMinutes: 10080,
                    observedAt: "2026-06-19T20:26:45+08:00",
                    sourceType: "official_cli_limit_message",
                    confidence: "observed",
                    status: "ok",
                    official: true
                ),
                MobileLimitWindow(
                    sourceID: "codex-main",
                    provider: "codex",
                    window: "session",
                    usedPercent: 59,
                    remainingPercent: 41,
                    resetAt: "2026-06-19T14:42:15+00:00",
                    windowDurationMinutes: 300,
                    observedAt: "2026-06-19T20:26:45+08:00",
                    sourceType: "runtime_api",
                    confidence: "observed",
                    status: "ok",
                    official: true
                ),
            ]
        )
        let state = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion,
                client: summary.client,
                generatedAt: summary.generatedAt,
                timezone: summary.timezone,
                period: summary.period,
                trend: summary.trend,
                sources: summary.sources,
                breakdown: summary.breakdown,
                limits: summary.limits,
                providerSlots: [
                    providerSlot(
                        provider: "claude",
                        windows: duplicateLimits.windows.filter { $0.provider == "claude" }
                    ),
                    providerSlot(
                        provider: "codex",
                        windows: duplicateLimits.windows.filter { $0.provider == "codex" }
                    ),
                ]
            ),
            selectedPeriodID: "today",
            now: try date("2026-06-19T09:00:00+00:00")
        )

        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.outerPctText, "96%")
        XCTAssertEqual(claude.innerPctText, "47%")
        XCTAssertEqual(claude.outerFraction, 0.96, accuracy: 0.001)

        let codex = try XCTUnwrap(state.quotaRings.first { $0.id == "codex" })
        XCTAssertEqual(codex.outerPctText, "59%")
        XCTAssertEqual(codex.outerFraction, 0.59, accuracy: 0.001)
    }

    func testQuotaRingsIgnoreExpiredAndCacheOnlyWindows() throws {
        let summary = try loadFixture()
        let limits = MobileLimits(
            observedCount: 3,
            totalCount: 3,
            windows: [
                MobileLimitWindow(
                    sourceID: "claude-main",
                    provider: "claude",
                    window: "session",
                    usedPercent: 71,
                    remainingPercent: 29,
                    resetAt: "2000-01-01T00:00:00+00:00",
                    windowDurationMinutes: 300,
                    observedAt: "2026-06-24T12:19:09+08:00",
                    sourceType: "official_cli",
                    confidence: "observed",
                    status: "ok",
                    official: true
                ),
                MobileLimitWindow(
                    sourceID: "claude-main",
                    provider: "claude",
                    window: "week",
                    usedPercent: 52,
                    remainingPercent: 48,
                    resetAt: "2099-01-01T00:00:00+00:00",
                    windowDurationMinutes: 10080,
                    observedAt: "2026-06-24T15:30:26+08:00",
                    sourceType: "official_cli",
                    confidence: "observed",
                    status: "ok",
                    official: true
                ),
                MobileLimitWindow(
                    sourceID: "claude-main",
                    provider: "claude",
                    window: "session",
                    usedPercent: 96,
                    remainingPercent: 4,
                    resetAt: "2099-01-01T00:00:00+00:00",
                    windowDurationMinutes: 300,
                    observedAt: "2026-06-24T15:30:26+08:00",
                    sourceType: "active_limits_cache",
                    confidence: "observed",
                    status: "ok",
                    official: true
                ),
            ]
        )

        let state = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion,
                client: summary.client,
                generatedAt: summary.generatedAt,
                timezone: summary.timezone,
                period: summary.period,
                trend: summary.trend,
                sources: summary.sources,
                breakdown: summary.breakdown,
                limits: summary.limits,
                providerSlots: [
                    providerSlot(
                        provider: "claude",
                        windows: limits.windows.filter { $0.provider == "claude" }
                    )
                ]
            ),
            selectedPeriodID: "today",
            now: try date("2026-06-24T15:31:00+08:00")
        )

        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.outerPctText, "--")
        XCTAssertEqual(claude.innerPctText, "52%")
        XCTAssertEqual(claude.outerFraction, 0, accuracy: 0.001)
        XCTAssertEqual(claude.innerFraction, 0.52, accuracy: 0.001)
        XCTAssertEqual(state.primaryLimitText, "Claude week · 52% 已用")
        XCTAssertEqual(state.limitRows.map(\.title), ["Claude week"])
    }

    func testQuotaRingsShowDynamicWindowSourceFreshnessAndUnavailableState() throws {
        let summary = try loadFixture()
        let limits = MobileLimits(
            observedCount: 3,
            totalCount: 3,
            windows: [
                MobileLimitWindow(
                    sourceID: "linux-biai-wang", provider: "claude", window: "session",
                    usedPercent: 18, remainingPercent: 82,
                    resetAt: "2026-07-18T18:00:00+08:00", windowDurationMinutes: 300,
                    observedAt: "2026-07-18T02:20:00+00:00", sourceType: "official_cli",
                    confidence: "observed", status: "ok", official: true
                ),
                MobileLimitWindow(
                    sourceID: "linux-biai-wang", provider: "claude", window: "week",
                    usedPercent: 37, remainingPercent: 63,
                    resetAt: "2026-07-20T00:00:00+08:00", windowDurationMinutes: 10080,
                    observedAt: "2026-07-18T02:20:00+00:00", sourceType: "official_cli",
                    confidence: "observed", status: "ok", official: true
                ),
                MobileLimitWindow(
                    sourceID: "codex-main", provider: "codex", window: "primary",
                    usedPercent: 62, remainingPercent: 38,
                    resetAt: "2026-07-19T10:00:00+08:00", windowDurationMinutes: 1440,
                    observedAt: "2026-07-18T08:00:00+08:00", sourceType: "runtime_api",
                    confidence: "observed", status: "ok", official: true
                ),
            ]
        )
        let state = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion, client: summary.client,
                generatedAt: "2026-07-18T10:30:00+08:00", timezone: summary.timezone,
                period: summary.period, trend: summary.trend, sources: summary.sources,
                breakdown: summary.breakdown,
                limits: summary.limits,
                providerSlots: [
                    providerSlot(
                        provider: "claude",
                        windows: limits.windows.filter { $0.provider == "claude" }
                    ),
                    providerSlot(
                        provider: "codex",
                        windows: limits.windows.filter { $0.provider == "codex" }
                    ),
                ]
            ),
            selectedPeriodID: "today",
            now: try date("2026-07-18T10:30:00+08:00")
        )

        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.outerLabel, "5h")
        XCTAssertEqual(claude.innerLabel, "7d")
        XCTAssertEqual(claude.sourceText, "BIAI · wang")
        XCTAssertEqual(claude.updatedText, "10:20 更新")
        XCTAssertEqual(claude.availabilityText, "官方额度")

        let codex = try XCTUnwrap(state.quotaRings.first { $0.id == "codex" })
        XCTAssertEqual(codex.outerLabel, "额度")
        XCTAssertEqual(codex.outerPctText, "--")
        XCTAssertEqual(codex.sourceText, "Codex 官方")
        XCTAssertEqual(codex.updatedText, "08:00 更新")
        XCTAssertEqual(codex.availabilityText, "额度暂不可用")
    }

    func testQuotaRingKeepsStaleProviderSourceAndUpdateWhenValuesAreHidden() throws {
        let summary = try loadFixture()
        let claudeSlot = MobileProviderSlot(
            provider: "claude",
            usage: .missing,
            quota: MobileProviderQuota(
                status: "missing",
                reason: "stale",
                lastVerifiedAt: "2026-07-18T10:00:00+08:00",
                sourceID: "linux-biai-wangzhipeng",
                sourceType: "oauth_usage_api",
                windows: []
            )
        )
        let state = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion, client: summary.client,
                generatedAt: "2026-07-18T12:30:00+08:00", timezone: summary.timezone,
                period: summary.period, trend: summary.trend, sources: summary.sources,
                breakdown: summary.breakdown, limits: summary.limits,
                providerSlots: [claudeSlot]
            ),
            selectedPeriodID: "today", now: try date("2026-07-18T12:30:00+08:00")
        )

        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.outerPctText, "--")
        XCTAssertEqual(claude.sourceText, "BIAI · wangzhipeng")
        XCTAssertEqual(claude.updatedText, "10:00 更新")
        XCTAssertTrue(claude.availabilityText.contains("额度暂不可用"))
    }

    func testQuotaRingNeverCombinesWindowsFromDifferentSources() throws {
        let summary = try loadFixture()
        let commonReset = "2026-07-20T00:00:00+08:00"
        let claudeSlot = MobileProviderSlot(
            provider: "claude",
            usage: .missing,
            quota: MobileProviderQuota(
                status: "available",
                reason: nil,
                lastVerifiedAt: "2026-07-18T10:20:00+08:00",
                sourceID: "source-b",
                sourceType: "oauth_usage_api",
                windows: [
                MobileLimitWindow(
                    sourceID: "source-a", provider: "claude", window: "session",
                    usedPercent: 10, remainingPercent: 90, resetAt: commonReset,
                    windowDurationMinutes: 300, observedAt: "2026-07-18T10:10:00+08:00",
                    sourceType: "oauth_usage_api", confidence: "observed", status: "ok", official: true
                ),
                MobileLimitWindow(
                    sourceID: "source-b", provider: "claude", window: "week",
                    usedPercent: 20, remainingPercent: 80, resetAt: commonReset,
                    windowDurationMinutes: 10080, observedAt: "2026-07-18T10:20:00+08:00",
                    sourceType: "oauth_usage_api", confidence: "observed", status: "ok", official: true
                ),
                ]
            )
        )
        let state = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion, client: summary.client,
                generatedAt: "2026-07-18T10:30:00+08:00", timezone: summary.timezone,
                period: summary.period, trend: summary.trend, sources: summary.sources,
                breakdown: summary.breakdown, limits: summary.limits,
                providerSlots: [claudeSlot]
            ),
            selectedPeriodID: "today", now: try date("2026-07-18T10:30:00+08:00")
        )

        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.outerPctText, "--")
        XCTAssertEqual(claude.innerPctText, "20%")
        XCTAssertEqual(claude.sourceText, "Claude 官方")
    }

    func testTrendSelectionFollowsMouseLocation() throws {
        let summary = try loadFixture()
        let state = MenuBarViewModel.build(
            from: summary,
            selectedPeriodID: "week",
            now: try date("2026-06-02T11:00:00+08:00")
        )

        XCTAssertEqual(
            MenuTrendSelection.nearestBar(in: state.trendBars, xLocation: 1, width: 200)?.id,
            state.trendBars[0].id
        )
        XCTAssertEqual(
            MenuTrendSelection.nearestBar(in: state.trendBars, xLocation: 180, width: 200)?.id,
            state.trendBars[1].id
        )
    }

    func testRuntimeDefaultsStayOutOfDocuments() {
        let home = URL(fileURLWithPath: "/Users/product")

        let root = RuntimePaths.defaultRoot(homeDirectory: home)
        let paths = RuntimePaths(root: root)

        XCTAssertEqual(
            root.path,
            "/Users/product/Library/Application Support/ai-usage-widget/macos-menu-bar"
        )
        XCTAssertFalse(root.path.contains("/Documents/"))
        XCTAssertEqual(paths.configURL.lastPathComponent, "config.json")
        XCTAssertEqual(paths.periodCacheDirectoryURL.lastPathComponent, "summaries")
        XCTAssertEqual(paths.cacheURL(forPeriod: "today").lastPathComponent, "today-offset0.json")
        XCTAssertEqual(paths.logURL.lastPathComponent, "menu-bar.log")
    }

    private func providerSlot(
        provider: String,
        windows: [MobileLimitWindow],
        status: String = "available",
        reason: String? = nil,
        sourceID: String? = nil,
        sourceType: String? = nil,
        lastVerifiedAt: String? = nil
    ) -> MobileProviderSlot {
        MobileProviderSlot(
            provider: provider,
            usage: .missing,
            quota: MobileProviderQuota(
                status: status,
                reason: reason,
                lastVerifiedAt: lastVerifiedAt ?? windows.compactMap(\.observedAt).max(),
                sourceID: sourceID ?? windows.first?.sourceID,
                sourceType: sourceType ?? windows.first?.sourceType,
                windows: windows
            )
        )
    }

    private func loadFixture() throws -> MobileSummary {
        let url = try XCTUnwrap(Bundle.module.url(forResource: "mobile-summary", withExtension: "json"))
        let data = try Data(contentsOf: url)
        return try JSONDecoder().decode(MobileSummary.self, from: data)
    }

    private func date(_ iso: String) throws -> Date {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let value = formatter.date(from: iso) {
            return value
        }
        formatter.formatOptions = [.withInternetDateTime]
        return try XCTUnwrap(formatter.date(from: iso))
    }
}
