import XCTest
@testable import AIUsageMenuBarCore

final class ModelQuotaEstimatorTests: XCTestCase {

    func testClaudeOpusHigherWeightThanSonnet() {
        // 23M tokens of Opus (5x weight) should be approx 1.0%
        let opusText = ModelQuotaEstimator.estimateWeeklyQuotaPercentText(
            modelID: "claude-opus-5",
            label: "Claude Opus 5",
            agentID: "claude",
            tokens: 23_000_000
        )
        XCTAssertEqual(opusText, "约占周额度 1.0%")

        // 23M tokens of Sonnet (1x weight) should be approx 0.2%
        let sonnetText = ModelQuotaEstimator.estimateWeeklyQuotaPercentText(
            modelID: "claude-sonnet-5",
            label: "Claude Sonnet 5",
            agentID: "claude",
            tokens: 23_000_000
        )
        XCTAssertEqual(sonnetText, "约占周额度 0.2%")
    }

    func testClaudeFableDualPool() {
        // Fable consumes share in the main pool, and also has its dedicated pool
        let fableText = ModelQuotaEstimator.estimateWeeklyQuotaPercentText(
            modelID: "claude-fable-5-1",
            label: "Claude Fable 5.1",
            agentID: "claude",
            tokens: 35_000_000
        )
        XCTAssertNotNil(fableText)
        XCTAssertTrue(fableText!.contains("约占周额度 0.3%"))
        XCTAssertTrue(fableText!.contains("专属约 58%"))
    }

    func testCodexGPT6vsGPT56() {
        // 22M tokens of GPT-5.6 should be approx 1.0%
        let gpt56Text = ModelQuotaEstimator.estimateWeeklyQuotaPercentText(
            modelID: "gpt-5.6-sol",
            label: "GPT-5.6 Sol",
            agentID: "codex",
            tokens: 22_000_000
        )
        XCTAssertEqual(gpt56Text, "约占周额度 1.0%")

        // 7.33M tokens of GPT-6 Astra (3x weight) should be approx 1.0%
        let gpt6Text = ModelQuotaEstimator.estimateWeeklyQuotaPercentText(
            modelID: "gpt-6-astra",
            label: "GPT-6 Astra",
            agentID: "codex",
            tokens: 7_333_333
        )
        XCTAssertEqual(gpt6Text, "约占周额度 1.0%")
    }

    func testZeroAndTinyTokens() {
        // Zero tokens returns nil
        XCTAssertNil(ModelQuotaEstimator.estimateWeeklyQuotaPercentText(
            modelID: "claude-sonnet-5",
            tokens: 0
        ))

        // Very tiny tokens (e.g. 5,000) returns "< 0.1%"
        let tinyText = ModelQuotaEstimator.estimateWeeklyQuotaPercentText(
            modelID: "claude-sonnet-5",
            tokens: 5_000
        )
        XCTAssertEqual(tinyText, "约占周额度 < 0.1%")
    }
}
