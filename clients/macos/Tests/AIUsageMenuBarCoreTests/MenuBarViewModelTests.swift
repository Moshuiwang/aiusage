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
        XCTAssertEqual(state.tokenBreakdownText, "输入 2.8K · 输出 1.4K · 缓存命中 16.0%")
        XCTAssertEqual(state.healthText, "2/2 正常")
        XCTAssertEqual(state.primaryLimitText, "暂无可信额度")
        // #177 Opus 审查：headerUpdatedText 锁具体值而不是宽松的 hasSuffix；跨天分支见
        // testHeaderUpdatedTextLocksClockFormatSameDayAndCrossDay。
        XCTAssertEqual(state.headerUpdatedText, "10:40 更新")
        // #177：旧 state.sources / flatModels 已删除，等价覆盖迁移到 serverCards——
        // 该 fixture 没有 agents 明细（legacy 格式），Server 卡片必须只有汇总值，不能凭空造出模型行。
        XCTAssertEqual(state.serverCards.map(\.title), ["linux-dev", "macbook-pro"])
        XCTAssertTrue(state.serverCards.allSatisfy { $0.models.isEmpty })
        XCTAssertTrue(state.limitRows.isEmpty)
        XCTAssertEqual(state.quotaRings.map(\.id), ["claude", "codex", "antigravity"])
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

    // #177 Opus 审查：headerUpdatedText 锁「HH:mm 更新」（同日）与「MM-dd HH:mm 更新」（跨天）两个分支的具体值。
    func testHeaderUpdatedTextLocksClockFormatSameDayAndCrossDay() throws {
        let summary = try loadFixture()
        // fixture 里最新的 source lastObservedAt 是 "2026-06-02T10:40:00+08:00"（linux-dev-wang）。
        let sameDayState = MenuBarViewModel.build(
            from: summary, selectedPeriodID: "week",
            now: try date("2026-06-02T11:00:00+08:00")
        )
        XCTAssertEqual(sameDayState.headerUpdatedText, "10:40 更新")

        let crossDayState = MenuBarViewModel.build(
            from: summary, selectedPeriodID: "week",
            now: try date("2026-06-03T09:00:00+08:00")
        )
        XCTAssertEqual(crossDayState.headerUpdatedText, "06-02 10:40 更新")
    }

    /// #177 真机反馈：标题栏时间之前只取「所选 summary」自己的 sources，切到历史周期后
    /// 会显示历史快照里的旧同步时间。headerUpdatedText 必须取所有已知 summary（当前 +
    /// todaySummary + 缓存）sources 里最新的一个，与额度环 quotaSlots 同一思路。
    func testHeaderUpdatedTextTakesLatestAcrossAdditionalSources() throws {
        let summary = try loadFixture()
        // fixture 自身最新 lastObservedAt 是 "2026-06-02T10:40:00+08:00"。
        let newerSource = MobileSource(
            sourceID: "extra",
            machine: "mac-extra",
            osUser: "wang",
            platform: "macos",
            displayName: nil,
            status: "ok",
            lastObservedAt: "2026-06-02T21:12:00+08:00",
            lastPushedAt: "2026-06-02T21:12:00+08:00",
            errorMessage: nil
        )
        let state = MenuBarViewModel.build(
            from: summary, selectedPeriodID: "week",
            now: try date("2026-06-02T22:00:00+08:00"),
            additionalSources: [newerSource]
        )
        XCTAssertEqual(state.headerUpdatedText, "21:12 更新")
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

        // #177：旧 state.sources 已删除，等价覆盖迁移到 serverCards——
        // 一台机器被 3 个不同 os_user 的 source 共享时必须仍是一张卡，不按 source 拆分。
        XCTAssertEqual(state.serverCards.count, 1)
        XCTAssertEqual(state.serverCards.map(\.title), ["ip-10-50-128-30.eu-west-1.compute.internal"])
        XCTAssertEqual(state.serverCards.map(\.valueText), ["800.0K"])
        XCTAssertTrue(state.serverCards.first?.models.isEmpty == true)
        XCTAssertTrue(state.serverCards.first?.subtitle.hasPrefix("3 个用户") == true, "got: \(state.serverCards.first?.subtitle ?? "")")
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

        // #177 真机反馈：hour 粒度横轴标签改为「N点」，与 tooltip 的 "HH:mm" 分开——
        // tooltip 仍用于图例联动展示，标签只用于横轴刻度。
        XCTAssertEqual(state.trendBars.count, 24)
        XCTAssertEqual(state.trendBars[0].label, "0点")
        XCTAssertEqual(state.trendBars[12].label, "12点")
        XCTAssertEqual(state.trendBars[23].label, "23点")
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
        // #176: 段顺序自底向上 claude → codex → antigravity → unknown（Claude 在底）。
        XCTAssertEqual(bar.segments.map(\.provider), [.claude, .codex, .unknown])
        XCTAssertEqual(bar.segments.map(\.tokens), [300, 200, 100])
        XCTAssertEqual(bar.segments.reduce(0) { $0 + $1.tokens }, bar.totalTokens)
        // 颜色必须与 AgentBranding（#175）完全一致，不再有第二套色值。
        XCTAssertEqual(
            MenuTrendProvider.claude.color,
            AgentBranding.color(for: "claude")
        )
        XCTAssertEqual(
            MenuTrendProvider.codex.color,
            AgentBranding.color(for: "codex")
        )
        XCTAssertEqual(
            MenuTrendProvider.unknown.color,
            AgentBranding.color(for: "unknown")
        )
        XCTAssertEqual(
            MenuTrendProvider.antigravity.color,
            AgentBranding.color(for: "antigravity")
        )
        XCTAssertEqual(
            MenuTrendProvider.claude.color,
            MenuTrendColor(red: 0.851, green: 0.467, blue: 0.341, opacity: 1)
        )
        XCTAssertEqual(
            MenuTrendProvider.codex.color,
            MenuTrendColor(red: 0.184, green: 0.486, blue: 0.965, opacity: 1)
        )
        XCTAssertEqual(
            MenuTrendProvider.unknown.color,
            MenuTrendColor(red: 0.557, green: 0.557, blue: 0.576, opacity: 1)
        )
        XCTAssertEqual(
            MenuTrendProvider.antigravity.color,
            MenuTrendColor(red: 0.608, green: 0.447, blue: 0.796, opacity: 1)
        )
        XCTAssertEqual(MenuTrendProvider.antigravity.displayName, "Antigravity")
    }

    func testTrendWithAntigravityTokensProducesAntigravitySegment() throws {
        let summary = try loadFixture()
        let trend = MobileTrend(
            period: "today",
            granularity: "hour",
            startDate: "2026-06-02",
            endDate: "2026-06-02",
            points: [
                MobileTrendPoint(
                    bucket: "2026-06-02T10:00:00+08:00",
                    label: "10:00",
                    tokens: 750,
                    inputTokens: 200,
                    outputTokens: 100,
                    cacheTokens: 450,
                    cacheRatio: 60,
                    claudeTokens: 300,
                    codexTokens: 200,
                    geminiTokens: 150,
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
        XCTAssertEqual(bar.segments.map(\.provider), [.claude, .codex, .antigravity, .unknown])
        XCTAssertEqual(bar.segments.map(\.tokens), [300, 200, 150, 100])
        XCTAssertEqual(bar.segments.reduce(0) { $0 + $1.tokens }, bar.totalTokens)
    }

    /// 结构下限：段顺序精确、守恒（从产物独立复算，不跑实现自己的断言）。
    func testTrendStackOrderClaudeCodexAntigravityUnknownExact() throws {
        let point = MobileTrendPoint(
            bucket: "2026-06-02T10:00:00+08:00",
            label: "10:00",
            tokens: 1000,
            inputTokens: 0,
            outputTokens: 0,
            cacheTokens: 0,
            cacheRatio: 0,
            claudeTokens: 500,
            codexTokens: 300,
            geminiTokens: 150,
            unknownTokens: 50
        )
        let summary = try loadFixture()
        let trend = MobileTrend(period: "today", granularity: "hour", startDate: "2026-06-02", endDate: "2026-06-02", points: [point])
        let state = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion, client: summary.client,
                generatedAt: summary.generatedAt, timezone: summary.timezone,
                period: summary.period, trend: trend, sources: summary.sources,
                breakdown: summary.breakdown, limits: summary.limits
            ),
            selectedPeriodID: "today",
            now: try date("2026-06-02T11:00:00+08:00")
        )
        let bar = try XCTUnwrap(state.trendBars.first)
        XCTAssertEqual(bar.segments.map(\.provider), [.claude, .codex, .antigravity, .unknown])
        XCTAssertEqual(bar.segments.map(\.tokens), [500, 300, 150, 50])
        // 守恒：独立复算 sum(segments.tokens) == totalTokens，不用实现自己的断言。
        let recomputedSum = bar.segments.reduce(0) { $0 + $1.tokens }
        XCTAssertEqual(recomputedSum, 1000)
        XCTAssertEqual(recomputedSum, bar.totalTokens)
    }

    /// 超额缩放：已知分量之和超过 tokens 总量时按比例缩放，段和仍必须等于总量。
    func testTrendOverAllocatedComponentsScaleDownAndStillConserve() throws {
        let point = MobileTrendPoint(
            bucket: "2026-06-02T10:00:00+08:00",
            label: "10:00",
            tokens: 1000,
            inputTokens: 0,
            outputTokens: 0,
            cacheTokens: 0,
            cacheRatio: 0,
            claudeTokens: 500,
            codexTokens: 400,
            geminiTokens: 300,
            unknownTokens: 0
        )
        let summary = try loadFixture()
        let trend = MobileTrend(period: "today", granularity: "hour", startDate: "2026-06-02", endDate: "2026-06-02", points: [point])
        let state = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion, client: summary.client,
                generatedAt: summary.generatedAt, timezone: summary.timezone,
                period: summary.period, trend: trend, sources: summary.sources,
                breakdown: summary.breakdown, limits: summary.limits
            ),
            selectedPeriodID: "today",
            now: try date("2026-06-02T11:00:00+08:00")
        )
        let bar = try XCTUnwrap(state.trendBars.first)
        XCTAssertEqual(bar.segments.map(\.provider), [.claude, .codex, .antigravity])
        XCTAssertEqual(bar.segments.map(\.tokens), [416, 333, 251])
        XCTAssertEqual(bar.segments.reduce(0) { $0 + $1.tokens }, 1000)
    }

    /// 未来时段：week 当期，now 在周三 → 周四至周日 isFuture 且无段；过去几天不是。
    func testFutureBucketsHaveNoSegmentsAndAreExcludedFromMax() throws {
        let summary = try loadFixture()
        // 2026-06-24 是周三（Monday=2026-06-22）。
        let bucketDates = ["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26", "2026-06-27", "2026-06-28"]
        let points = bucketDates.enumerated().map { index, bucket in
            MobileTrendPoint(
                bucket: bucket, label: bucket, tokens: (index + 1) * 100,
                inputTokens: 0, outputTokens: 0, cacheTokens: 0, cacheRatio: 0,
                claudeTokens: (index + 1) * 100
            )
        }
        let trend = MobileTrend(period: "week", granularity: "day", startDate: "2026-06-22", endDate: "2026-06-28", points: points)
        let state = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion, client: summary.client,
                generatedAt: summary.generatedAt, timezone: summary.timezone,
                period: summary.period, trend: trend, sources: summary.sources,
                breakdown: summary.breakdown, limits: summary.limits
            ),
            selectedPeriodID: "week",
            now: try date("2026-06-24T09:00:00+08:00")
        )
        let bars = state.trendBars
        XCTAssertEqual(bars.map(\.isFuture), [false, false, false, true, true, true, true])
        for bar in bars where bar.isFuture {
            XCTAssertTrue(bar.segments.isEmpty, "future bar \(bar.id) must carry no segments")
            XCTAssertEqual(bar.totalTokens, 0)
        }
        // 未来点不参与最大值：过去最大 tokens 是 06-24 的 300，其 ratio 必须是 1.0。
        let todayBar = try XCTUnwrap(bars.first { $0.id == "2026-06-24" })
        XCTAssertEqual(todayBar.ratio, 1.0, accuracy: 0.001)
        // 参考线/顶部刻度同样只按过去点计算：与只含过去三点的 trend 结果一致。
        let pastOnly = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion, client: summary.client,
                generatedAt: summary.generatedAt, timezone: summary.timezone,
                period: summary.period,
                trend: MobileTrend(period: "week", granularity: "day", startDate: "2026-06-22", endDate: "2026-06-28", points: Array(points.prefix(3))),
                sources: summary.sources, breakdown: summary.breakdown, limits: summary.limits
            ),
            selectedPeriodID: "week",
            now: try date("2026-06-24T09:00:00+08:00")
        )
        XCTAssertFalse(pastOnly.trendRefCeilingText.isEmpty)
        XCTAssertEqual(state.trendRefCeilingText, pastOnly.trendRefCeilingText)
        XCTAssertEqual(state.trendCeilingFraction, pastOnly.trendCeilingFraction, accuracy: 0.0001)
    }

    func testHourBucketsFutureOnlyAfterNowAndHistoricalDayHasNoFuture() throws {
        let buckets = ["2026-06-24T11:00:00+08:00", "2026-06-24T12:00:00+08:00", "2026-06-24T13:00:00+08:00"]
        let now = try date("2026-06-24T12:30:00+08:00")
        XCTAssertEqual(
            buckets.map { MenuBarViewModel.isFutureBucket($0, granularity: "hour", now: now, timezone: "Asia/Shanghai") },
            [false, false, true]
        )
        let yesterday = (0..<24).map { String(format: "2026-06-23T%02d:00:00+08:00", $0) }
        XCTAssertEqual(yesterday.count, 24)
        XCTAssertTrue(yesterday.allSatisfy { !MenuBarViewModel.isFutureBucket($0, granularity: "hour", now: now, timezone: "Asia/Shanghai") })
    }

    func testTrendLegendTotalsAggregateByAgentAcrossAllBars() throws {
        let summary = try loadFixture()
        let points = [
            MobileTrendPoint(
                bucket: "2026-06-01", label: "2026-06-01", tokens: 300,
                inputTokens: 0, outputTokens: 0, cacheTokens: 0, cacheRatio: 0,
                claudeTokens: 200, codexTokens: 100
            ),
            MobileTrendPoint(
                bucket: "2026-06-02", label: "2026-06-02", tokens: 300,
                inputTokens: 0, outputTokens: 0, cacheTokens: 0, cacheRatio: 0,
                claudeTokens: 100, geminiTokens: 150, unknownTokens: 50
            ),
        ]
        let trend = MobileTrend(period: "week", granularity: "day", startDate: "2026-06-01", endDate: "2026-06-02", points: points)
        let state = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion, client: summary.client,
                generatedAt: summary.generatedAt, timezone: summary.timezone,
                period: summary.period, trend: trend, sources: summary.sources,
                breakdown: summary.breakdown, limits: summary.limits
            ),
            selectedPeriodID: "week",
            now: try date("2026-06-02T11:00:00+08:00")
        )
        // 独立复算：claude=200+100=300, codex=100, antigravity=150, unknown=50, total=600。
        XCTAssertEqual(state.trendLegendTotals.map(\.provider), [.claude, .codex, .antigravity, .unknown])
        XCTAssertEqual(state.trendLegendTotals.map(\.tokens), [300, 100, 150, 50])
        let recomputedTotal = state.trendLegendTotals.reduce(0) { $0 + $1.tokens }
        XCTAssertEqual(recomputedTotal, 600)
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
        // #177：单环视图以周窗口为主（week 优先于 session），primaryFraction 取 47% 而非 outer 的 96%。
        XCTAssertEqual(claude.primaryFraction, 0.47, accuracy: 0.001)

        let codex = try XCTUnwrap(state.quotaRings.first { $0.id == "codex" })
        XCTAssertEqual(codex.outerPctText, "59%")
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
        // #177：outer(session) 已过期不可见时，primaryFraction 退回 week 窗口的 52%。
        XCTAssertEqual(claude.primaryFraction, 0.52, accuracy: 0.001)
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
        XCTAssertEqual(claude.updatedText, "10:20 更新")
        XCTAssertEqual(claude.availabilityText, "")

        let codex = try XCTUnwrap(state.quotaRings.first { $0.id == "codex" })
        XCTAssertEqual(codex.outerLabel, "额度")
        XCTAssertEqual(codex.outerPctText, "--")
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
    }

    func testQuotaRingsAreDecoupledFromSelectedPeriodSummarySlots() throws {
        let summary = try loadFixture()
        let quotaSlots = [
            providerSlot(
                provider: "claude",
                windows: [
                    MobileLimitWindow(
                        sourceID: "claude-main", provider: "claude", window: "session",
                        usedPercent: 26, remainingPercent: 74,
                        resetAt: "2026-07-18T18:00:00+08:00", windowDurationMinutes: 300,
                        observedAt: "2026-07-18T09:00:00+08:00", sourceType: "official_cli",
                        confidence: "observed", status: "ok", official: true
                    )
                ]
            )
        ]
        let historicalWeekSlots = [
            providerSlot(
                provider: "claude",
                windows: [
                    MobileLimitWindow(
                        sourceID: "claude-main", provider: "claude", window: "session",
                        usedPercent: 80, remainingPercent: 20,
                        resetAt: "2026-07-11T18:00:00+08:00", windowDurationMinutes: 300,
                        observedAt: "2026-07-11T09:00:00+08:00", sourceType: "official_cli",
                        confidence: "observed", status: "ok", official: true
                    )
                ]
            )
        ]
        let historicalMonthSlots = [
            providerSlot(
                provider: "claude",
                windows: [
                    MobileLimitWindow(
                        sourceID: "claude-main", provider: "claude", window: "session",
                        usedPercent: 55, remainingPercent: 45,
                        resetAt: "2026-06-20T18:00:00+08:00", windowDurationMinutes: 300,
                        observedAt: "2026-06-20T09:00:00+08:00", sourceType: "official_cli",
                        confidence: "observed", status: "ok", official: true
                    )
                ]
            )
        ]
        let now = try date("2026-07-18T10:00:00+08:00")

        let weekState = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion, client: summary.client,
                generatedAt: summary.generatedAt, timezone: summary.timezone,
                period: summary.period, trend: summary.trend, sources: summary.sources,
                breakdown: summary.breakdown, limits: summary.limits,
                providerSlots: historicalWeekSlots
            ),
            selectedPeriodID: "week", selectedOffset: -1, now: now,
            quotaSlots: quotaSlots
        )
        let monthState = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion, client: summary.client,
                generatedAt: summary.generatedAt, timezone: summary.timezone,
                period: summary.period, trend: summary.trend, sources: summary.sources,
                breakdown: summary.breakdown, limits: summary.limits,
                providerSlots: historicalMonthSlots
            ),
            selectedPeriodID: "month", selectedOffset: -2, now: now,
            quotaSlots: quotaSlots
        )

        XCTAssertEqual(weekState.quotaRings, monthState.quotaRings)
        let claude = try XCTUnwrap(weekState.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.outerPctText, "26%")
        XCTAssertEqual(claude.primaryPctText, "26%")
    }

    func testQuotaRingDisplayNameForAntigravityAndFixedBrandColors() throws {
        let summary = try loadFixture()
        let quotaSlots = [
            providerSlot(provider: "claude", windows: []),
            providerSlot(provider: "codex", windows: []),
            providerSlot(provider: "antigravity", windows: []),
        ]
        let state = MenuBarViewModel.build(
            from: summary, selectedPeriodID: "today",
            now: try date("2026-06-02T11:00:00+08:00"),
            quotaSlots: quotaSlots
        )

        XCTAssertEqual(state.quotaRings.map(\.id), ["claude", "codex", "antigravity"])
        let antigravity = try XCTUnwrap(state.quotaRings.first { $0.id == "antigravity" })
        XCTAssertEqual(antigravity.displayName, "Antigravity")

        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        let codex = try XCTUnwrap(state.quotaRings.first { $0.id == "codex" })
        XCTAssertEqual(claude.brandColor, MenuTrendColor(red: 0.851, green: 0.467, blue: 0.341, opacity: 1))
        XCTAssertEqual(codex.brandColor, MenuTrendColor(red: 0.184, green: 0.486, blue: 0.965, opacity: 1))
        XCTAssertEqual(antigravity.brandColor, MenuTrendColor(red: 0.608, green: 0.447, blue: 0.796, opacity: 1))
    }

    func testQuotaRingUpdatedTextIgnoresSelectedSummaryGeneratedAt() throws {
        let fixture = try loadFixture()
        let data = try JSONEncoder().encode(fixture)
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        object["generated_at"] = "2026-07-18T09:50:00+08:00"
        let todaySummary = try JSONDecoder().decode(
            MobileSummary.self, from: JSONSerialization.data(withJSONObject: object)
        )
        object["generated_at"] = "2026-07-11T09:50:00+08:00"
        let historicalSummary = try JSONDecoder().decode(
            MobileSummary.self, from: JSONSerialization.data(withJSONObject: object)
        )
        let quotaSlots = [
            providerSlot(
                provider: "claude",
                windows: [
                    MobileLimitWindow(
                        sourceID: "claude-main", provider: "claude", window: "session",
                        usedPercent: 26, remainingPercent: 74,
                        resetAt: "2026-07-18T18:00:00+08:00", windowDurationMinutes: 300,
                        observedAt: "2026-07-18T09:00:00+08:00", sourceType: "official_cli",
                        confidence: "observed", status: "ok", official: true
                    )
                ],
                lastVerifiedAt: "2026-07-18T09:00:00+08:00"
            )
        ]
        let now = try date("2026-07-18T10:00:00+08:00")
        let fromToday = MenuBarViewModel.build(
            from: todaySummary, selectedPeriodID: "today", now: now, quotaSlots: quotaSlots
        )
        let fromHistory = MenuBarViewModel.build(
            from: historicalSummary, selectedPeriodID: "week", selectedOffset: -1, now: now, quotaSlots: quotaSlots
        )
        let todayRing = try XCTUnwrap(fromToday.quotaRings.first { $0.id == "claude" })
        let historyRing = try XCTUnwrap(fromHistory.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(todayRing.updatedText, "09:00 更新")
        XCTAssertEqual(historyRing.updatedText, "09:00 更新", "圆环更新时间不应随所选历史期变化")
        XCTAssertEqual(fromToday.quotaRings, fromHistory.quotaRings)
    }

    func testQuotaRingDegradesAvailabilityForNonObservedOrFailedWindows() throws {
        let summary = try loadFixture()

        func ring(windows: [MobileLimitWindow], status: String = "available", reason: String? = nil) throws -> QuotaRingData {
            let slot = providerSlot(provider: "claude", windows: windows, status: status, reason: reason)
            let state = MenuBarViewModel.build(
                from: summary, selectedPeriodID: "today",
                now: try date("2026-07-18T10:00:00+08:00"),
                quotaSlots: [slot]
            )
            return try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        }

        // estimated：confidence 非 observed
        let estimated = try ring(windows: [
            MobileLimitWindow(
                sourceID: "s", provider: "claude", window: "session",
                usedPercent: 40, remainingPercent: 60, resetAt: "2026-07-18T18:00:00+08:00",
                windowDurationMinutes: 300, observedAt: "2026-07-18T09:00:00+08:00",
                sourceType: "official_cli", confidence: "estimated", status: "ok", official: true
            )
        ])
        XCTAssertFalse(estimated.isAvailable)
        XCTAssertEqual(estimated.primaryPctText, "—")

        // missing：quota.status 为 missing，无 window
        let missing = try ring(windows: [], status: "missing")
        XCTAssertFalse(missing.isAvailable)
        XCTAssertEqual(missing.primaryPctText, "—")

        // unsupported：quota.reason 为 unsupported
        let unsupported = try ring(windows: [], status: "missing", reason: "unsupported")
        XCTAssertFalse(unsupported.isAvailable)
        XCTAssertEqual(unsupported.primaryPctText, "—")
        XCTAssertTrue(unsupported.availabilityText.contains("暂不可用"))

        // official == false
        let notOfficial = try ring(windows: [
            MobileLimitWindow(
                sourceID: "s", provider: "claude", window: "session",
                usedPercent: 40, remainingPercent: 60, resetAt: "2026-07-18T18:00:00+08:00",
                windowDurationMinutes: 300, observedAt: "2026-07-18T09:00:00+08:00",
                sourceType: "official_cli", confidence: "observed", status: "ok", official: false
            )
        ])
        XCTAssertFalse(notOfficial.isAvailable)
        XCTAssertEqual(notOfficial.primaryPctText, "—")

        // status != ok
        let notOk = try ring(windows: [
            MobileLimitWindow(
                sourceID: "s", provider: "claude", window: "session",
                usedPercent: 40, remainingPercent: 60, resetAt: "2026-07-18T18:00:00+08:00",
                windowDurationMinutes: 300, observedAt: "2026-07-18T09:00:00+08:00",
                sourceType: "official_cli", confidence: "observed", status: "error", official: true
            )
        ])
        XCTAssertFalse(notOk.isAvailable)
        XCTAssertEqual(notOk.primaryPctText, "—")

        // missing 但带着 App 层嫁接回来的「最近成功值」窗口（官方/observed/ok）：仍必须降级
        let keptLastSuccess = try ring(windows: [
            MobileLimitWindow(
                sourceID: "s", provider: "claude", window: "session",
                usedPercent: 80, remainingPercent: 20, resetAt: "2026-07-18T18:00:00+08:00",
                windowDurationMinutes: 300, observedAt: "2026-07-18T09:00:00+08:00",
                sourceType: "official_cli", confidence: "observed", status: "ok", official: true
            )
        ], status: "missing", reason: "provider_failed")
        XCTAssertFalse(keptLastSuccess.isAvailable)
        XCTAssertEqual(keptLastSuccess.primaryPctText, "—")
        XCTAssertEqual(keptLastSuccess.primaryPctNumberText, "—")
        XCTAssertEqual(keptLastSuccess.resetCountdownText, "--")
        XCTAssertTrue(keptLastSuccess.availabilityText.contains("最近成功值"))
        // #177 Opus 审查：isAvailable=false 时浮层不得泄露「最近成功值」窗口残留的旧百分比（80%）——
        // 悬停行必须只显示降级状态说明，不能出现任何 "%"。
        XCTAssertFalse(keptLastSuccess.hoverRows.isEmpty)
        XCTAssertTrue(
            keptLastSuccess.hoverRows.allSatisfy { !$0.valueText.contains("%") },
            "got: \(keptLastSuccess.hoverRows)"
        )
        XCTAssertTrue(keptLastSuccess.hoverRows.contains { $0.valueText.contains("最近成功值") })
    }

    func testQuotaRingPrimaryPctPrefersWeekAndCountsDownToNearestReset() throws {
        let summary = try loadFixture()
        let slot = providerSlot(
            provider: "claude",
            windows: [
                MobileLimitWindow(
                    sourceID: "s", provider: "claude", window: "session",
                    usedPercent: 40, remainingPercent: 60, resetAt: "2026-07-18T18:00:00+08:00",
                    windowDurationMinutes: 300, observedAt: "2026-07-18T09:00:00+08:00",
                    sourceType: "official_cli", confidence: "observed", status: "ok", official: true
                ),
                MobileLimitWindow(
                    sourceID: "s", provider: "claude", window: "week",
                    usedPercent: 26, remainingPercent: 74, resetAt: "2026-07-20T00:00:00+08:00",
                    windowDurationMinutes: 10080, observedAt: "2026-07-18T09:00:00+08:00",
                    sourceType: "official_cli", confidence: "observed", status: "ok", official: true
                ),
            ]
        )
        let state = MenuBarViewModel.build(
            from: summary, selectedPeriodID: "today",
            now: try date("2026-07-18T10:00:00+08:00"),
            quotaSlots: [slot]
        )
        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.primaryPctText, "26%")
        // #177 Opus 审查：primaryPctNumberText 不带 %，视图自己拼一次单独字号的 %，
        // 避免 primaryPctText（已带 %）再被拼接出「26%%」。
        XCTAssertEqual(claude.primaryPctNumberText, "26")
        // 最近一次重置来自 session 窗口（18:00 早于 07-20 00:00）
        XCTAssertEqual(claude.resetCountdownText, "8h 0min")
        XCTAssertTrue(claude.isAvailable)
        // 可用状态下浮层行必须带百分比（与不可用场景的「不含 %」相对）。
        XCTAssertEqual(claude.hoverRows.count, 2)
        XCTAssertTrue(claude.hoverRows.allSatisfy { $0.valueText.contains("%") })
    }

    /// #177 真机反馈：只有 7d/week 窗口、没有 session 窗口时（如 Codex），悬停浮层不能出现
    /// 「额度 — · --」这种无数据占位行——只显示确实有数据的窗口行。
    func testQuotaRingHoverRowsOmitWindowsWithoutData() throws {
        let summary = try loadFixture()
        let slot = providerSlot(
            provider: "codex",
            windows: [
                MobileLimitWindow(
                    sourceID: "s", provider: "codex", window: "week",
                    usedPercent: 12, remainingPercent: 88, resetAt: "2026-07-20T00:00:00+08:00",
                    windowDurationMinutes: 10080, observedAt: "2026-07-18T09:00:00+08:00",
                    sourceType: "official_cli", confidence: "observed", status: "ok", official: true
                )
            ]
        )
        let state = MenuBarViewModel.build(
            from: summary, selectedPeriodID: "today",
            now: try date("2026-07-18T10:00:00+08:00"),
            quotaSlots: [slot]
        )
        let codex = try XCTUnwrap(state.quotaRings.first { $0.id == "codex" })
        XCTAssertTrue(codex.isAvailable)
        XCTAssertEqual(codex.hoverRows.count, 1, "got: \(codex.hoverRows)")
        XCTAssertFalse(codex.hoverRows.contains { $0.valueText.contains("--") && $0.valueText.contains("—") })
    }

    func testQuotaRingsStructuralFloorAlwaysHasThreeFixedProvidersInOrder() throws {
        let summary = try loadFixture()
        let state = MenuBarViewModel.build(
            from: summary, selectedPeriodID: "today",
            now: try date("2026-06-02T11:00:00+08:00"),
            quotaSlots: []
        )
        XCTAssertEqual(state.quotaRings.count, 3)
        XCTAssertEqual(state.quotaRings.map(\.id), ["claude", "codex", "antigravity"])
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
