import AIUsageMenuBarCore
@testable import AIUsageMenuBarApp
import XCTest

@MainActor
final class MenuBarAppModelTests: XCTestCase {
    func testIgnoresStaleRefreshAfterPeriodSwitch() async throws {
        let loader = ControlledSummaryLoader()
        let config = MenuBarRuntimeConfig(
            serverURL: "https://vpn2.chunbai.com:8443",
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
            serverURL: "https://vpn2.chunbai.com:8443",
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

    func testKeepsCachedSummaryQuietlyWhenRefreshFails() async throws {
        let loader = ControlledSummaryLoader()
        let config = MenuBarRuntimeConfig(
            serverURL: "https://vpn2.chunbai.com:8443",
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

        XCTAssertNil(model.errorMessage)
        XCTAssertEqual(model.summary, cached)
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
}

private actor ControlledSummaryLoader {
    private var continuations: [String: CheckedContinuation<MobileSummary, Error>] = [:]
    private var completedPeriods: Set<String> = []

    func load(config: MobileSummaryClientConfig) async throws -> MobileSummary {
        defer {
            completedPeriods.insert(config.period)
        }
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
}
