import XCTest
@testable import AIUsageMenuBarCore

final class MenuBarViewModelTests: XCTestCase {
    func testBuildsCompactStatusAndPopoverSections() throws {
        let summary = try loadFixture()

        let state = MenuBarViewModel.build(
            from: summary,
            selectedPeriodID: "week",
            now: try date("2026-06-02T11:00:00+08:00")
        ,
            deviceTimeZone: shanghaiTZForTests)

        XCTAssertEqual(state.statusTitle, "5.0K")
        XCTAssertEqual(state.periodLabel, "本周")
        // #186 回归守卫：本机时区与 summary.timezone 偏移相同时不加任何标注。
        XCTAssertEqual(state.periodTitleSuffix, "")
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

    /// #186：本机时区（America/Los_Angeles）与 summary.timezone（Asia/Shanghai）当前 UTC 偏移
    /// 不同时——时刻类（headerUpdatedText）按本机时区显示，期间标题追加「（北京时间）」；
    /// 日界类（periodID/dateRangeText/所选周的起止日期）保持 summary 时区，不受影响。
    func testDeviceTimezoneDiffersFromSummaryAnnotatesPeriodTitleAndShowsClockInDeviceTime() throws {
        let summary = try loadFixture()
        let losAngeles = try XCTUnwrap(TimeZone(identifier: "America/Los_Angeles"))

        let state = MenuBarViewModel.build(
            from: summary,
            selectedPeriodID: "week",
            now: try date("2026-06-02T11:00:00+08:00"),
            deviceTimeZone: losAngeles
        )

        // 期间标题追加标注——periodLabel 本身保持不含标注的基础文本（期间菜单弹层按钮显示的是
        // PeriodMenuBuilder 缓存行 title，不是 periodLabel；periodTitleSuffix 由调用方
        // 【MenuBarUsageSectionView】拼接到实际渲染的标题后面，这里只锁 MenuBarState 的两个字段）。
        // 日界类字段（起止日期）逐字不变。
        XCTAssertEqual(state.periodLabel, "本周")
        XCTAssertEqual(state.periodTitleSuffix, "（北京时间）")
        XCTAssertEqual(state.dateRangeText, "2026-05-27 ～ 2026-06-02")

        // headerUpdatedText 是「时刻类」——fixture 最新 lastObservedAt "2026-06-02T10:40:00+08:00"
        // 换算到洛杉矶是 "2026-06-01T19:40:00-07:00"，与 now 换算后的洛杉矶日历日同一天（06-01），
        // 按本机时区显示为 "19:40 更新"（不是北京时间的 "10:40 更新"）。
        XCTAssertEqual(state.headerUpdatedText, "19:40 更新")
    }

    // #177 Opus 审查：headerUpdatedText 锁「HH:mm 更新」（同日）与「MM-dd HH:mm 更新」（跨天）两个分支的具体值。
    func testHeaderUpdatedTextLocksClockFormatSameDayAndCrossDay() throws {
        let summary = try loadFixture()
        // fixture 里最新的 source lastObservedAt 是 "2026-06-02T10:40:00+08:00"（linux-dev-wang）。
        let sameDayState = MenuBarViewModel.build(
            from: summary, selectedPeriodID: "week",
            now: try date("2026-06-02T11:00:00+08:00")
        ,
            deviceTimeZone: shanghaiTZForTests)
        XCTAssertEqual(sameDayState.headerUpdatedText, "10:40 更新")

        let crossDayState = MenuBarViewModel.build(
            from: summary, selectedPeriodID: "week",
            now: try date("2026-06-03T09:00:00+08:00")
        ,
            deviceTimeZone: shanghaiTZForTests)
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
        ,
            deviceTimeZone: shanghaiTZForTests)
        XCTAssertEqual(state.headerUpdatedText, "21:12 更新")
    }

    // 真机 bug：headerUpdatedText 取所有 source 最新同步时间时按 ISO **字符串**比大小，不同来源
    // 带不同时区 offset（+00:00 / +08:00）时字符串比较会选错——必须解析成 Date 再比较真实时间。
    func testHeaderUpdatedTextComparesActualTimeNotStringAcrossDifferentTimezoneOffsets() throws {
        let summary = try loadFixture()
        // 10:31:37+00:00 = 18:31:37 北京时间，晚于 16:47:12+08:00；但字符串
        // "2026-09-27T16:47:12+08:00" 在字典序上大于 "2026-09-27T10:31:37+00:00"，
        // 旧实现的 .max() 会误选后者（更早的 16:47）。
        let utcSource = MobileSource(
            sourceID: "utc-src", machine: "utc-machine", osUser: "wang", platform: "linux",
            displayName: nil, status: "ok",
            lastObservedAt: "2026-09-27T10:31:37+00:00", lastPushedAt: "2026-09-27T10:31:37+00:00",
            errorMessage: nil
        )
        let localSource = MobileSource(
            sourceID: "local-src", machine: "mac", osUser: "wang", platform: "macos",
            displayName: nil, status: "ok",
            lastObservedAt: "2026-09-27T16:47:12+08:00", lastPushedAt: "2026-09-27T16:47:12+08:00",
            errorMessage: nil
        )
        let state = MenuBarViewModel.build(
            from: summary, selectedPeriodID: "week",
            now: try date("2026-09-27T19:00:00+08:00"),
            additionalSources: [utcSource, localSource]
        ,
            deviceTimeZone: shanghaiTZForTests)
        XCTAssertEqual(state.headerUpdatedText, "18:31 更新")
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
        ,
            deviceTimeZone: shanghaiTZForTests)

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
        ,
            deviceTimeZone: shanghaiTZForTests)

        // #177 真机反馈：hour 粒度横轴标签改为「N点」，与 tooltip 的 "HH:mm" 分开——
        // tooltip 仍用于图例联动展示，标签只用于横轴刻度。
        XCTAssertEqual(state.trendBars.count, 24)
        XCTAssertEqual(state.trendBars[0].label, "0点")
        XCTAssertEqual(state.trendBars[12].label, "12点")
        XCTAssertEqual(state.trendBars[23].label, "23点")
        XCTAssertTrue(state.trendBars[1].label.isEmpty)
        XCTAssertEqual(state.trendBars[1].tooltipTitle, "01:00")

        // #186：本机时区（America/Los_Angeles）与 summary.timezone（Asia/Shanghai）当前 UTC
        // 偏移不同时，hour 粒度横轴标签必须加「北京 」前缀说明——小时数字本身仍是 summary 时区
        // 的小时（bucket 不变），只是多了一层标注,不影响 tooltipTitle（仍是 "HH:mm"，未改动）。
        let laState = MenuBarViewModel.build(
            from: today,
            selectedPeriodID: "today",
            now: try date("2026-06-02T11:00:00+08:00"),
            deviceTimeZone: try XCTUnwrap(TimeZone(identifier: "America/Los_Angeles"))
        )
        XCTAssertEqual(laState.trendBars[0].label, "北京 0点")
        XCTAssertEqual(laState.trendBars[12].label, "北京 12点")
        XCTAssertEqual(laState.trendBars[23].label, "北京 23点")
        XCTAssertEqual(laState.trendBars[1].tooltipTitle, "01:00", "tooltip 不受本机时区标注影响")

        let weeklyTrend = MobileTrend(
            period: "week",
            granularity: "day",
            startDate: "2026-06-01",
            endDate: "2026-06-02",
            points: [
                MobileTrendPoint(bucket: "2026-06-01", label: "2026-06-01", tokens: 10, inputTokens: 0, outputTokens: 0, cacheTokens: 0, cacheRatio: 0),
                MobileTrendPoint(bucket: "2026-06-02", label: "2026-06-02", tokens: 20, inputTokens: 0, outputTokens: 0, cacheTokens: 0, cacheRatio: 0),
            ]
        )
        let dayBoundaryToday = MobileSummary(
            schemaVersion: summary.schemaVersion,
            client: summary.client,
            generatedAt: summary.generatedAt,
            timezone: summary.timezone, // "Asia/Shanghai"
            period: summary.period,
            trend: weeklyTrend,
            sources: summary.sources,
            breakdown: summary.breakdown,
            limits: summary.limits
        )
        // #186：未来时段判定（isFutureBucket）是「日界类」——必须保持 summary.timezone，
        // 不能悄悄换成本机时区。now = 北京时间 2026-06-02T03:00:00+08:00：
        // 北京日历日是 06-02（bucket "2026-06-02" 是「今天」，不是未来）；换算到本机
        // America/Los_Angeles 是 2026-06-01T12:00:00-07:00，日历日是 06-01——如果误用
        // 本机时区判定，bucket "2026-06-02" 会被错误标记成未来（06-02 > 06-01）。
        let dayBoundaryState = MenuBarViewModel.build(
            from: dayBoundaryToday,
            selectedPeriodID: "week",
            now: try date("2026-06-02T03:00:00+08:00"),
            deviceTimeZone: try XCTUnwrap(TimeZone(identifier: "America/Los_Angeles"))
        )
        XCTAssertFalse(dayBoundaryState.trendBars[1].isFuture, "「今天」的 bucket 不能因为本机时区落后就被判成未来")
        XCTAssertEqual(dayBoundaryState.trendBars[1].valueText, "20", "非未来 bucket 必须正常显示 tokens，不能因误判未来而清空")

        let weeklyTrend2 = MobileTrend(
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
            trend: weeklyTrend2,
            sources: summary.sources,
            breakdown: summary.breakdown,
            limits: summary.limits
        )
        let weekState = MenuBarViewModel.build(
            from: week,
            selectedPeriodID: "week",
            now: try date("2026-06-02T11:00:00+08:00")
        ,
            deviceTimeZone: shanghaiTZForTests)
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
        ,
            deviceTimeZone: shanghaiTZForTests)

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
        ,
            deviceTimeZone: shanghaiTZForTests)

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
        ,
            deviceTimeZone: shanghaiTZForTests)
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
        ,
            deviceTimeZone: shanghaiTZForTests)
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
        ,
            deviceTimeZone: shanghaiTZForTests)
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
        ,
            deviceTimeZone: shanghaiTZForTests)
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
        ,
            deviceTimeZone: shanghaiTZForTests)
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
        ,
            deviceTimeZone: shanghaiTZForTests)

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
        ,
            deviceTimeZone: shanghaiTZForTests)

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
        ,
            deviceTimeZone: shanghaiTZForTests)

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
        ,
            deviceTimeZone: shanghaiTZForTests)

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
        ,
            deviceTimeZone: shanghaiTZForTests)

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
        ,
            deviceTimeZone: shanghaiTZForTests)

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
                        sourceID: "claude-main", provider: "claude", window: "week",
                        usedPercent: 26, remainingPercent: 74,
                        resetAt: "2026-07-21T18:00:00+08:00", windowDurationMinutes: 10080,
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
                        sourceID: "claude-main", provider: "claude", window: "week",
                        usedPercent: 80, remainingPercent: 20,
                        resetAt: "2026-07-11T18:00:00+08:00", windowDurationMinutes: 10080,
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
                        sourceID: "claude-main", provider: "claude", window: "week",
                        usedPercent: 55, remainingPercent: 45,
                        resetAt: "2026-06-20T18:00:00+08:00", windowDurationMinutes: 10080,
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
        ,
            deviceTimeZone: shanghaiTZForTests)
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
        ,
            deviceTimeZone: shanghaiTZForTests)

        XCTAssertEqual(weekState.quotaRings, monthState.quotaRings)
        let claude = try XCTUnwrap(weekState.quotaRings.first { $0.id == "claude" })
        // #203：Claude 只用周窗口，本测试的数据随之改为周窗口；解耦意图不变。
        XCTAssertEqual(claude.innerPctText, "26%")
        XCTAssertEqual(claude.primaryPctText, "26%")
    }

    // MARK: - #203：Claude 圆环只显示周窗口与周重置时间（与 Codex 一致）

    private func ringWindow(_ provider: String, _ window: String, used: Double, resetAt: String, minutes: Int) -> MobileLimitWindow {
        MobileLimitWindow(
            sourceID: "\(provider)-main", provider: provider, window: window,
            usedPercent: used, remainingPercent: 100 - used,
            resetAt: resetAt, windowDurationMinutes: minutes,
            observedAt: "2026-07-18T09:30:00+08:00", sourceType: "official_cli",
            confidence: "observed", status: "ok", official: true
        )
    }

    private func ringsFor(_ slots: [MobileProviderSlot], now: Date) throws -> [QuotaRingData] {
        let summary = try loadFixture()
        return MenuBarViewModel.build(
            from: summary, selectedPeriodID: "week", now: now, quotaSlots: slots,
            deviceTimeZone: shanghaiTZForTests
        ).quotaRings
    }

    func testClaudeRingCountdownUsesWeeklyResetLikeCodexNotFiveHourSession() throws {
        let now = try date("2026-07-18T10:00:00+08:00")
        let weekReset = "2026-07-21T18:00:00+08:00"
        let sessionReset = "2026-07-18T12:00:00+08:00" // 5h 窗口更早重置
        let rings = try ringsFor([
            providerSlot(provider: "claude", windows: [
                ringWindow("claude", "session", used: 70, resetAt: sessionReset, minutes: 300),
                ringWindow("claude", "week", used: 31, resetAt: weekReset, minutes: 10080),
            ]),
            providerSlot(provider: "codex", windows: [
                ringWindow("codex", "week", used: 27, resetAt: weekReset, minutes: 10080),
            ]),
            providerSlot(provider: "antigravity", windows: [
                ringWindow("antigravity", "session", used: 5, resetAt: sessionReset, minutes: 300),
            ]),
        ], now: now)
        let claude = try XCTUnwrap(rings.first { $0.id == "claude" })
        let codex = try XCTUnwrap(rings.first { $0.id == "codex" })
        let antigravitySession = try XCTUnwrap(rings.first { $0.id == "antigravity" })
        XCTAssertTrue(claude.isAvailable)
        // 倒计时与同一 reset 的 Codex 周窗口一致，且不等于 5h 窗口的倒计时。
        XCTAssertEqual(claude.resetCountdownText, codex.resetCountdownText)
        XCTAssertNotEqual(claude.resetCountdownText, antigravitySession.resetCountdownText)
        XCTAssertEqual(claude.primaryPctText, "31%")
        // 悬停浮层只剩周窗口一行，5h 窗口不再出现。
        XCTAssertEqual(claude.hoverRows.count, 1)
        XCTAssertFalse(claude.hoverRows.contains { $0.valueText.hasPrefix("70%") })
    }

    func testClaudeRingWithoutWeeklyWindowShowsDashNotFiveHourFallback() throws {
        let now = try date("2026-07-18T10:00:00+08:00")
        let rings = try ringsFor([
            providerSlot(provider: "claude", windows: [
                ringWindow("claude", "session", used: 70, resetAt: "2026-07-18T12:00:00+08:00", minutes: 300),
            ]),
        ], now: now)
        let claude = try XCTUnwrap(rings.first { $0.id == "claude" })
        XCTAssertFalse(claude.isAvailable)
        XCTAssertEqual(claude.primaryPctText, "—")
        XCTAssertEqual(claude.resetCountdownText, "--")
        XCTAssertEqual(claude.primaryFraction, 0)
    }

    func testAntigravityRingKeepsNearestResetWindowUnchangedByClaudeRule() throws {
        let now = try date("2026-07-18T10:00:00+08:00")
        let rings = try ringsFor([
            providerSlot(provider: "antigravity", windows: [
                ringWindow("antigravity", "session", used: 5, resetAt: "2026-07-18T12:00:00+08:00", minutes: 300),
                ringWindow("antigravity", "week", used: 9, resetAt: "2026-07-21T18:00:00+08:00", minutes: 10080),
            ]),
            providerSlot(provider: "codex", windows: [
                ringWindow("codex", "week", used: 27, resetAt: "2026-07-21T18:00:00+08:00", minutes: 10080),
            ]),
        ], now: now)
        let antigravity = try XCTUnwrap(rings.first { $0.id == "antigravity" })
        let codex = try XCTUnwrap(rings.first { $0.id == "codex" })
        XCTAssertNotEqual(antigravity.resetCountdownText, codex.resetCountdownText, "Antigravity 本次不改：仍取最近重置窗口")
        XCTAssertEqual(antigravity.hoverRows.count, 2)
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
        ,
            deviceTimeZone: shanghaiTZForTests)

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
        ,
            deviceTimeZone: shanghaiTZForTests)
        let fromHistory = MenuBarViewModel.build(
            from: historicalSummary, selectedPeriodID: "week", selectedOffset: -1, now: now, quotaSlots: quotaSlots
        ,
            deviceTimeZone: shanghaiTZForTests)
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
            ,
            deviceTimeZone: shanghaiTZForTests)
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
        // #203：Claude 只用周窗口，这里用周窗口继续守「最近成功值必须降级、不泄露 %」。
        let keptLastSuccess = try ring(windows: [
            MobileLimitWindow(
                sourceID: "s", provider: "claude", window: "week",
                usedPercent: 80, remainingPercent: 20, resetAt: "2026-07-18T18:00:00+08:00",
                windowDurationMinutes: 10080, observedAt: "2026-07-18T09:00:00+08:00",
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
        ,
            deviceTimeZone: shanghaiTZForTests)
        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.primaryPctText, "26%")
        // #177 Opus 审查：primaryPctNumberText 不带 %，视图自己拼一次单独字号的 %，
        // 避免 primaryPctText（已带 %）再被拼接出「26%%」。
        XCTAssertEqual(claude.primaryPctNumberText, "26")
        // #203：Claude 只用周窗口——倒计时来自周窗口（07-20 00:00，距 07-18 10:00 共 38 小时），
        // 不再取更早重置的 5 小时窗口（旧行为是「8h 0min」）。
        XCTAssertEqual(claude.resetCountdownText, "1d 14h")
        XCTAssertTrue(claude.isAvailable)
        // 可用状态下浮层行必须带百分比（与不可用场景的「不含 %」相对）；5 小时窗口行不再出现。
        XCTAssertEqual(claude.hoverRows.count, 1)
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
        ,
            deviceTimeZone: shanghaiTZForTests)
        let codex = try XCTUnwrap(state.quotaRings.first { $0.id == "codex" })
        XCTAssertTrue(codex.isAvailable)
        XCTAssertEqual(codex.hoverRows.count, 1, "got: \(codex.hoverRows)")
        XCTAssertFalse(codex.hoverRows.contains { $0.valueText.contains("--") && $0.valueText.contains("—") })
    }

    /// #177 第四轮真机反馈：悬停浮层的 7d/5h 两行改成具体北京时间重置时刻（而不是倒计时），
    /// 格式「今天/明天 HH:mm」或「M月d日 周X HH:mm」；圆环旁的倒计时（resetCountdownText）保持不变。
    func testQuotaRingHoverRowsShowAbsoluteResetMomentInsteadOfCountdown() throws {
        // #203：Claude 只用周窗口；本测试守的是重置时刻格式化，改用仍保留 5h 窗口的 Antigravity。
        let summary = try loadFixture()
        let slot = providerSlot(
            provider: "antigravity",
            windows: [
                // 同一天：session 窗口今天 18:00 重置
                MobileLimitWindow(
                    sourceID: "s", provider: "antigravity", window: "session",
                    usedPercent: 40, remainingPercent: 60, resetAt: "2026-07-18T18:00:00+08:00",
                    windowDurationMinutes: 300, observedAt: "2026-07-18T09:00:00+08:00",
                    sourceType: "official_cli", confidence: "observed", status: "ok", official: true
                ),
                // 2026-07-20 是周一，距 now（2026-07-18 周六）相差 2 天，不是「明天」。
                MobileLimitWindow(
                    sourceID: "s", provider: "antigravity", window: "week",
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
        ,
            deviceTimeZone: shanghaiTZForTests)
        let ring = try XCTUnwrap(state.quotaRings.first { $0.id == "antigravity" })
        XCTAssertEqual(ring.hoverRows.count, 2)
        let sessionRow = try XCTUnwrap(ring.hoverRows.first { $0.valueText.contains("40%") })
        XCTAssertTrue(sessionRow.valueText.contains("今天 18:00"), "got: \(sessionRow.valueText)")
        // 圆环旁的倒计时保持原有格式不变（不受本次改动影响）。
        XCTAssertEqual(ring.resetCountdownText, "8h 0min")

        let weekRow = try XCTUnwrap(ring.hoverRows.first { $0.valueText.contains("26%") })
        XCTAssertTrue(weekRow.valueText.contains("7月20日 周一 00:00"), "got: \(weekRow.valueText)")
    }

    /// 明天重置：resetAt 落在「明天」时格式为「明天 HH:mm」。
    func testQuotaRingHoverRowsShowTomorrowForNextDayReset() throws {
        // #203：Claude 只用周窗口；本测试守的是重置时刻格式化，改用仍保留 5h 窗口的 Antigravity。
        let summary = try loadFixture()
        let slot = providerSlot(
            provider: "antigravity",
            windows: [
                MobileLimitWindow(
                    sourceID: "s", provider: "antigravity", window: "session",
                    usedPercent: 40, remainingPercent: 60, resetAt: "2026-07-19T09:00:00+08:00",
                    windowDurationMinutes: 300, observedAt: "2026-07-18T09:00:00+08:00",
                    sourceType: "official_cli", confidence: "observed", status: "ok", official: true
                )
            ]
        )
        let state = MenuBarViewModel.build(
            from: summary, selectedPeriodID: "today",
            now: try date("2026-07-18T10:00:00+08:00"),
            quotaSlots: [slot]
        ,
            deviceTimeZone: shanghaiTZForTests)
        let ring = try XCTUnwrap(state.quotaRings.first { $0.id == "antigravity" })
        let sessionRow = try XCTUnwrap(ring.hoverRows.first)
        XCTAssertTrue(sessionRow.valueText.contains("明天 09:00"), "got: \(sessionRow.valueText)")
    }

    /// #177 第四轮 Opus 审查：resetAt 已经过去（<= now）时必须显示「即将重置」，与圆环旁的倒计时
    /// （timeRemainingText 对 secs<=0 的处理）保持一致——不能显示一个已经过去的具体钟点让人
    /// 误以为它还没重置。直接调用 resetMomentText（internal，与 trendBars/isFutureBucket 同款
    /// 惯例）——通过完整 build() 管线测不到这个分支：trustedProviderWindows 对 status=="available"
    /// 的窗口本来就会把 resetAt<=now 的窗口过滤掉，走不到 isAvailable=true 的百分比+时刻这一支。
    func testQuotaRingHoverRowsShowAboutToResetWhenResetAtIsInThePast() throws {
        let shanghai = try XCTUnwrap(TimeZone(identifier: "Asia/Shanghai"))
        let now = try date("2026-07-18T10:00:00+08:00")

        XCTAssertNil(MenuBarViewModel.resetMomentText(nil, timezone: shanghai, now: now))

        let pastText = MenuBarViewModel.resetMomentText(
            "2026-07-18T09:00:00+08:00", timezone: shanghai, now: now
        )
        XCTAssertEqual(pastText, "即将重置")

        // 边界相等（resetAt == now）也算「已过去」，与 timeRemainingText 的 secs<=0 一致。
        let boundaryText = MenuBarViewModel.resetMomentText(
            "2026-07-18T10:00:00+08:00", timezone: shanghai, now: now
        )
        XCTAssertEqual(boundaryText, "即将重置")
    }

    /// #186：决策变更——额度悬停浮层的重置时刻是「时刻类」，改为按**本机时区**（deviceTimeZone）
    /// 显示，不再按 summary.timezone。构造 now/resetAt 使二者按北京时间跨天（→ 旧实现会判「明天」），
    /// 但按洛杉矶（本机）时区落在同一天（→ 新实现须判「今天」）：
    /// - now = 2026-07-18T23:00:00+08:00 = 2026-07-18T08:00:00-07:00（北京 7/18 23:00，洛杉矶 7/18 08:00）
    /// - resetAt = 2026-07-18T13:00:00-07:00 = 2026-07-19T04:00:00+08:00（北京 7/19 04:00——跨天，
    ///   旧实现按 summary 时区会显示「明天 04:00」；洛杉矶同为 7/18——新实现须显示「今天 13:00」）。
    /// （#177 时代的同名测试断言方向相反——那是变更前的旧行为，已随本 Issue 决策翻转。）
    func testQuotaRingHoverRowsUseDeviceTimezoneNotSummaryTimezoneForResetMoment() throws {
        // #203：Claude 只用周窗口；本测试守的是重置时刻格式化，改用仍保留 5h 窗口的 Antigravity。
        let summary = try loadFixture() // fixture timezone 固定 "Asia/Shanghai"。
        let losAngeles = try XCTUnwrap(TimeZone(identifier: "America/Los_Angeles"))
        let slot = providerSlot(
            provider: "antigravity",
            windows: [
                MobileLimitWindow(
                    sourceID: "s", provider: "antigravity", window: "session",
                    usedPercent: 40, remainingPercent: 60,
                    resetAt: "2026-07-18T13:00:00-07:00",
                    windowDurationMinutes: 300, observedAt: "2026-07-18T07:30:00-07:00",
                    sourceType: "official_cli", confidence: "observed", status: "ok", official: true
                )
            ]
        )
        let state = MenuBarViewModel.build(
            from: summary, selectedPeriodID: "today",
            now: try date("2026-07-18T23:00:00+08:00"),
            quotaSlots: [slot]
        ,
            deviceTimeZone: losAngeles)
        let ring = try XCTUnwrap(state.quotaRings.first { $0.id == "antigravity" })
        let row = try XCTUnwrap(ring.hoverRows.first)
        XCTAssertTrue(row.valueText.contains("今天 13:00"), "got: \(row.valueText)")

        // #186 补充覆盖：额度环旁的 updatedText 同样是「时刻类」——observedAt "2026-07-18T07:30:00-07:00"
        // 换算到本机（洛杉矶）与 now（洛杉矶 08:00 同一天）同日，应显示 "07:30 更新"，不是北京时间。
        XCTAssertEqual(ring.updatedText, "07:30 更新")
    }

    /// #177 第四轮 Opus 审查防回归：跨午夜——now 是北京时间 23:30，resetAt 是次日 00:30，
    /// 必须判定为「明天」。用 UTC 反证：同一对时刻换算到 UTC 是同一个 UTC 日（15:30 → 16:30），
    /// 不会跨天，如果实现误用 UTC 计算日期差就会错误显示「今天」。
    func testQuotaRingHoverRowsHandleCrossMidnightInShanghaiTimezone() throws {
        // #203：Claude 只用周窗口；本测试守的是重置时刻格式化，改用仍保留 5h 窗口的 Antigravity。
        let summary = try loadFixture()
        let slot = providerSlot(
            provider: "antigravity",
            windows: [
                MobileLimitWindow(
                    sourceID: "s", provider: "antigravity", window: "session",
                    usedPercent: 40, remainingPercent: 60, resetAt: "2026-07-19T00:30:00+08:00",
                    windowDurationMinutes: 300, observedAt: "2026-07-18T23:00:00+08:00",
                    sourceType: "official_cli", confidence: "observed", status: "ok", official: true
                )
            ]
        )
        let state = MenuBarViewModel.build(
            from: summary, selectedPeriodID: "today",
            now: try date("2026-07-18T23:30:00+08:00"),
            quotaSlots: [slot]
        ,
            deviceTimeZone: shanghaiTZForTests)
        let ring = try XCTUnwrap(state.quotaRings.first { $0.id == "antigravity" })
        let row = try XCTUnwrap(ring.hoverRows.first)
        XCTAssertTrue(row.valueText.contains("明天 00:30"), "got: \(row.valueText)")
    }

    func testQuotaRingsStructuralFloorAlwaysHasThreeFixedProvidersInOrder() throws {
        let summary = try loadFixture()
        let state = MenuBarViewModel.build(
            from: summary, selectedPeriodID: "today",
            now: try date("2026-06-02T11:00:00+08:00"),
            quotaSlots: []
        ,
            deviceTimeZone: shanghaiTZForTests)
        XCTAssertEqual(state.quotaRings.count, 3)
        XCTAssertEqual(state.quotaRings.map(\.id), ["claude", "codex", "antigravity"])
    }

    // MARK: - 真机 bug 同类修复 #2：isBetterLimitWindow 在 sourceType 质量相同时按
    // observedAt **字符串**比大小选「更新的窗口」，不同时区 offset 会选错。

    func testBestWindowPerTypePicksActuallyLatestObservedWindowAcrossTimezonesWhenSourceQualityTies() throws {
        let summary = try loadFixture()
        // 两条 window="week"、sourceType 相同（quality 打平），只有 observedAt 的时区 offset
        // 不同：existing "18:40+08:00"（真实更早），candidate "10:59:00+00:00" = 18:59 北京时间
        // （真实更晚，仅晚 19 分钟——两条都在 now 前 120 分钟新鲜窗口内，不会被 isStale 提前
        // 过滤掉，确保真正走到 tie-break 分支）。字符串比较会因为 "10" < "18" 误判 candidate
        // 更旧，保留 existing(10%)；正确实现应解析成真实时间，candidate(42%) 胜出。
        let windows = [
            MobileLimitWindow(
                sourceID: "claude-main", provider: "claude", window: "week",
                usedPercent: 10, remainingPercent: 90,
                resetAt: "2026-10-01T00:00:00+08:00", windowDurationMinutes: 10080,
                observedAt: "2026-09-27T18:40:00+08:00", sourceType: "official_cli",
                confidence: "observed", status: "ok", official: true
            ),
            MobileLimitWindow(
                sourceID: "claude-main", provider: "claude", window: "week",
                usedPercent: 42, remainingPercent: 58,
                resetAt: "2026-10-01T00:00:00+08:00", windowDurationMinutes: 10080,
                observedAt: "2026-09-27T10:59:00+00:00", sourceType: "official_cli",
                confidence: "observed", status: "ok", official: true
            ),
        ]
        let state = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion, client: summary.client,
                generatedAt: summary.generatedAt, timezone: summary.timezone,
                period: summary.period, trend: summary.trend, sources: summary.sources,
                breakdown: summary.breakdown, limits: summary.limits,
                providerSlots: [providerSlot(provider: "claude", windows: windows)]
            ),
            selectedPeriodID: "today",
            now: try date("2026-09-27T19:05:00+08:00")
        ,
            deviceTimeZone: shanghaiTZForTests)
        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.innerPctText, "42%")
    }

    // MARK: - 真机 bug 同类修复 #3：额度环 updatedText 回退到 observedAt 时按字符串 .max()

    func testQuotaRingUpdatedTextFallsBackToActualLatestObservedAtAcrossTimezonesWhenNotVerified() throws {
        let summary = try loadFixture()
        // 同样两条都要落在 now 前 120 分钟新鲜窗口内（否则较早那条会被 isStale 提前过滤掉，
        // 根本走不到 .max() 比较）：session 18:40+08:00（真实更早），week 10:59:00+00:00 =
        // 18:59 北京时间（真实更晚）。字符串 .max() 会因为 "18:40:00+08:00" 字典序更大而
        // 误选它，回退文案就会显示错误的更新时间。
        let windows = [
            MobileLimitWindow(
                sourceID: "claude-main", provider: "claude", window: "session",
                usedPercent: 50, remainingPercent: 50,
                resetAt: "2026-09-28T00:00:00+08:00", windowDurationMinutes: 300,
                observedAt: "2026-09-27T18:40:00+08:00", sourceType: "official_cli",
                confidence: "observed", status: "ok", official: true
            ),
            MobileLimitWindow(
                sourceID: "claude-main", provider: "claude", window: "week",
                usedPercent: 30, remainingPercent: 70,
                resetAt: "2026-10-01T00:00:00+08:00", windowDurationMinutes: 10080,
                observedAt: "2026-09-27T10:59:00+00:00", sourceType: "official_cli",
                confidence: "observed", status: "ok", official: true
            ),
        ]
        // 直接构造 slot，不经 providerSlot() 测试 helper——helper 自己对 lastVerifiedAt 的默认值
        // 也是 windows.observedAt 的字符串 .max()，会掩盖被测的生产代码回退路径。
        let slot = MobileProviderSlot(
            provider: "claude",
            usage: .missing,
            quota: MobileProviderQuota(
                status: "available", reason: nil, lastVerifiedAt: nil,
                sourceID: "claude-main", sourceType: "official_cli", windows: windows
            )
        )
        let state = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion, client: summary.client,
                generatedAt: summary.generatedAt, timezone: summary.timezone,
                period: summary.period, trend: summary.trend, sources: summary.sources,
                breakdown: summary.breakdown, limits: summary.limits,
                providerSlots: [slot]
            ),
            selectedPeriodID: "today",
            now: try date("2026-09-27T19:05:00+08:00")
        ,
            deviceTimeZone: shanghaiTZForTests)
        let claude = try XCTUnwrap(state.quotaRings.first { $0.id == "claude" })
        XCTAssertEqual(claude.updatedText, "18:59 更新")
    }

    // MARK: - 真机 bug 同类修复 #4：compactResetTime 用 resetAt/generatedAt 的日期**前缀字符串**
    // 判断「已过/重置」，同一天的 UTC 时间戳换算成北京时间后可能已经跨天，前缀字符串却相同。

    func testLimitRowResetSuffixComparesBeijingCalendarDayNotRawDatePrefix() throws {
        let summary = try loadFixture()
        // resetAt 是北京时间 09-27 23:00（真实日历日 09-27）；generatedAt 是 UTC 09-27 16:00，
        // 换算成北京时间是 09-28 00:00（真实日历日 09-28）——两者日期前缀字符串都是 "2026-09-27"，
        // 但真实北京日历日不同：09-27 < 09-28，reset 应判「已过」。旧实现比较前缀字符串「相等」
        // 会走 else 分支判「重置」，是错的。
        let window = MobileLimitWindow(
            sourceID: "claude-main", provider: "claude", window: "week",
            usedPercent: 40, remainingPercent: 60,
            resetAt: "2026-09-27T23:00:00+08:00", windowDurationMinutes: 10080,
            observedAt: "2026-09-27T16:00:00+08:00", sourceType: "official_cli",
            confidence: "observed", status: "ok", official: true
        )
        let slot = providerSlot(provider: "claude", windows: [window])
        let state = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion, client: summary.client,
                generatedAt: "2026-09-27T16:00:00+00:00", timezone: summary.timezone,
                period: summary.period, trend: summary.trend, sources: summary.sources,
                breakdown: summary.breakdown, limits: summary.limits,
                providerSlots: [slot]
            ),
            selectedPeriodID: "today",
            now: try date("2026-09-27T16:05:00+08:00")
        ,
            deviceTimeZone: shanghaiTZForTests)
        let row = try XCTUnwrap(state.limitRows.first)
        XCTAssertTrue(row.value.hasSuffix("已过"), "got: \(row.value)")
    }

    func testLimitRowResetSuffixUsesSummaryTimezoneCalendarDay() throws {
        // Codex PR #194 审查 P2：按 summary.timezone 的日历日判断，而不是写死上海。
        // 洛杉矶同为 09-27：resetAt 01:00-07:00（上海 09-27 16:00），generatedAt 10:00-07:00（上海 09-28 01:00）。
        // 按上海会误判「已过」，按洛杉矶应为「重置」。
        let summary = try loadFixture()
        let window = MobileLimitWindow(
            sourceID: "claude-main", provider: "claude", window: "week",
            usedPercent: 40, remainingPercent: 60,
            resetAt: "2026-09-27T01:00:00-07:00", windowDurationMinutes: 10080,
            observedAt: "2026-09-27T00:00:00-07:00", sourceType: "official_cli",
            confidence: "observed", status: "ok", official: true
        )
        let slot = providerSlot(provider: "claude", windows: [window])
        let state = MenuBarViewModel.build(
            from: MobileSummary(
                schemaVersion: summary.schemaVersion, client: summary.client,
                generatedAt: "2026-09-27T10:00:00-07:00", timezone: "America/Los_Angeles",
                period: summary.period, trend: summary.trend, sources: summary.sources,
                breakdown: summary.breakdown, limits: summary.limits,
                providerSlots: [slot]
            ),
            selectedPeriodID: "today",
            now: try date("2026-09-27T00:30:00-07:00")
        ,
            deviceTimeZone: shanghaiTZForTests)
        let row = try XCTUnwrap(state.limitRows.first)
        XCTAssertTrue(row.value.hasSuffix("重置"), "got: \(row.value)")

        // #186 补充覆盖：
        // 1. row.value 实际渲染的钟点是「时刻类」——resetAt "2026-09-27T01:00:00-07:00" 换算到
        //    本机（Shanghai）是 09-27 16:00，与 generatedAt 换算到 Shanghai 后的 09-28 不同日，
        //    格式带 "MM-dd"，必须是 "09-27 16:00 重置"，不是洛杉矶时间 "01:00"。
        XCTAssertEqual(row.value, "09-27 16:00 重置")
        // 2. summary.timezone 不是 Asia/Shanghai 时的标注文案分支（"服务时区"）此前没有测试覆盖——
        //    本机 Shanghai 与 summary America/Los_Angeles 当前偏移不同，应标注「（服务时区）」。
        XCTAssertEqual(state.periodTitleSuffix, "（服务时区）")
    }

    func testTrendSelectionFollowsMouseLocation() throws {
        let summary = try loadFixture()
        let state = MenuBarViewModel.build(
            from: summary,
            selectedPeriodID: "week",
            now: try date("2026-06-02T11:00:00+08:00")
        ,
            deviceTimeZone: shanghaiTZForTests)

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
