import AIUsageMenuBarCore
@testable import AIUsageMenuBarApp
import XCTest

@MainActor
final class MenuBarAppModelTests: XCTestCase {
    func testPopoverQuitActionTerminatesApplication() {
        var didQuit = false
        let controller = StatusBarController(
            paths: RuntimePaths(root: URL(fileURLWithPath: "/tmp/ai-usage-menu-test")),
            quitApplication: {
                didQuit = true
            }
        )

        controller.quitFromPopover()

        XCTAssertTrue(didQuit)
    }

    func testIgnoresStaleRefreshAfterPeriodSwitch() async throws {
        let loader = ControlledSummaryLoader()
        let config = MenuBarRuntimeConfig(
            serverURL: "https://aiusage.chunbai.com",
            token: "test-token",
            dashboardURL: nil,
            defaultPeriod: "all"
        )
        let model = MenuBarAppModel(
            paths: RuntimePaths(root: URL(fileURLWithPath: "/tmp/ai-usage-menu-test")),
            config: config,
            cachedSummary: MobileSummary.empty(periodID: "all"),
            loadSummary: loader.load
        )

        model.refresh(periodID: "today")
        model.refresh(periodID: "week")
        try await loader.waitForRequestCount(2)

        await loader.complete(period: "today", summary: MobileSummary.empty(periodID: "today"))
        try await loader.waitForCompleted("today")
        await yieldToMainActor()
        XCTAssertEqual(model.summary.period.id, "all")
        XCTAssertTrue(model.isLoading)

        await loader.complete(period: "week", summary: MobileSummary.empty(periodID: "week"))
        await waitUntil {
            model.summary.period.id == "week" && model.isLoading == false
        }
    }

    func testIgnoresStaleFailureAfterNewerRefreshSucceeds() async throws {
        let loader = ControlledSummaryLoader()
        let config = MenuBarRuntimeConfig(
            serverURL: "https://aiusage.chunbai.com",
            token: "test-token",
            dashboardURL: nil,
            defaultPeriod: "all"
        )
        let model = MenuBarAppModel(
            paths: RuntimePaths(root: URL(fileURLWithPath: "/tmp/ai-usage-menu-test")),
            config: config,
            cachedSummary: MobileSummary.empty(periodID: "all"),
            loadSummary: loader.load
        )

        model.refresh(periodID: "today")
        model.refresh(periodID: "week")
        try await loader.waitForRequestCount(2)

        await loader.complete(period: "week", summary: MobileSummary.empty(periodID: "week"))
        await waitUntil {
            model.summary.period.id == "week" && model.isLoading == false
        }

        await loader.fail(period: "today")
        try await loader.waitForCompleted("today")
        await yieldToMainActor()
        XCTAssertNil(model.errorMessage)
        XCTAssertEqual(model.summary.period.id, "week")
    }

    func testShowsCachedDataWarningWhenRefreshFails() async throws {
        let loader = ControlledSummaryLoader()
        let config = MenuBarRuntimeConfig(
            serverURL: "https://aiusage.chunbai.com",
            token: "test-token",
            dashboardURL: nil,
            defaultPeriod: "today"
        )
        let cached = MobileSummary.empty(periodID: "today")
        let model = MenuBarAppModel(
            paths: RuntimePaths(root: URL(fileURLWithPath: "/tmp/ai-usage-menu-test")),
            config: config,
            cachedSummary: cached,
            loadSummary: loader.load
        )

        model.refresh()
        try await loader.waitForRequestCount(1)
        await loader.fail(period: "today")
        await waitUntil {
            model.isLoading == false
        }

        XCTAssertTrue(model.errorMessage?.hasPrefix("刷新失败，正在显示缓存：") == true)
        XCTAssertTrue(model.errorMessage?.contains("-1001") == true)
        XCTAssertEqual(model.summary, cached)
    }

    func testRefreshUsesUpdatedRuntimeConfigWithoutRestart() async throws {
        let loader = ControlledSummaryLoader()
        let paths = try temporaryRuntimePaths()
        try FileManager.default.createDirectory(at: paths.root, withIntermediateDirectories: true)
        let updatedConfig = """
        {
          "dashboard_url": "https://aiusage.chunbai.com/dashboard",
          "default_period": "today",
          "refresh_interval_seconds": 600,
          "server_url": "https://aiusage.chunbai.com",
          "token": "new-token"
        }
        """
        try updatedConfig.write(to: paths.configURL, atomically: true, encoding: .utf8)
        let staleConfig = MenuBarRuntimeConfig(
            serverURL: "https://vpn2.chunbai.com:8443",
            token: "old-token",
            dashboardURL: nil,
            defaultPeriod: "today"
        )
        let model = MenuBarAppModel(
            paths: paths,
            config: staleConfig,
            cachedSummary: MobileSummary.empty(periodID: "today"),
            loadSummary: loader.load
        )

        model.refresh()
        try await loader.waitForRequestCount(1)
        let requestConfig = try await loader.config(for: "today")

        XCTAssertEqual(requestConfig.baseURL.absoluteString, "https://aiusage.chunbai.com")
        XCTAssertEqual(requestConfig.bearerToken, "new-token")
        XCTAssertEqual(model.dashboardURL?.absoluteString, "https://aiusage.chunbai.com/dashboard")
    }

    private func waitUntil(
        timeoutIterations: Int = 50,
        _ predicate: @MainActor () -> Bool,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        for _ in 0..<timeoutIterations {
            if predicate() {
                return
            }
            try? await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("Timed out waiting for expected model state", file: file, line: line)
    }

    private func yieldToMainActor() async {
        for _ in 0..<5 {
            await Task.yield()
        }
    }

    private func temporaryRuntimePaths() throws -> RuntimePaths {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("ai-usage-menu-\(UUID().uuidString)", isDirectory: true)
        addTeardownBlock {
            try? FileManager.default.removeItem(at: root)
        }
        return RuntimePaths(root: root)
    }
}

private actor ControlledSummaryLoader {
    private var continuations: [String: CheckedContinuation<MobileSummary, Error>] = [:]
    private var configs: [String: MobileSummaryClientConfig] = [:]
    private var completedPeriods: Set<String> = []

    func load(config: MobileSummaryClientConfig) async throws -> MobileSummary {
        defer {
            completedPeriods.insert(config.period)
        }
        configs[config.period] = config
        return try await withCheckedThrowingContinuation { continuation in
            continuations[config.period] = continuation
        }
    }

    func complete(period: String, summary: MobileSummary) {
        continuations.removeValue(forKey: period)?.resume(returning: summary)
    }

    func fail(period: String) {
        continuations.removeValue(forKey: period)?.resume(throwing: URLError(.timedOut))
    }

    func waitForRequestCount(_ count: Int) async throws {
        for _ in 0..<50 {
            if continuations.count >= count {
                return
            }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("Timed out waiting for \(count) requests")
    }

    func waitForCompleted(_ period: String) async throws {
        for _ in 0..<50 {
            if completedPeriods.contains(period) {
                return
            }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("Timed out waiting for \(period) completion")
    }

    func config(for period: String) throws -> MobileSummaryClientConfig {
        guard let config = configs[period] else {
            throw XCTSkip("No request config recorded for \(period)")
        }
        return config
    }
}
