import XCTest
@testable import AIUsageMenuBarCore

/// #177 收口：原先重复经由已删除的 `estimateWeeklyQuotaPercentText`（旧文本 API）覆盖的权重场景，
/// 迁移为直接断言结构化 `estimateWeeklyQuota` 的 `percent` / `dedicatedPercent`。
final class ModelQuotaEstimatorTests: XCTestCase {

    func testClaudeOpusHeavierWeightThanSonnet() throws {
        // 23M tokens of Opus (5x weight): 23,000,000 * 5 / 115,000,000 = 1.0%
        let opus = try XCTUnwrap(ModelQuotaEstimator.estimateWeeklyQuota(
            modelID: "claude-opus-5", label: "Claude Opus 5", agentID: "claude", tokens: 23_000_000
        ))
        XCTAssertEqual(opus.percent, 1.0, accuracy: 0.0001)

        // 23M tokens of Sonnet (1x weight): 23,000,000 * 1 / 115,000,000 = 0.2%
        let sonnet = try XCTUnwrap(ModelQuotaEstimator.estimateWeeklyQuota(
            modelID: "claude-sonnet-5", label: "Claude Sonnet 5", agentID: "claude", tokens: 23_000_000
        ))
        XCTAssertEqual(sonnet.percent, 0.2, accuracy: 0.0001)
        XCTAssertGreaterThan(opus.percent, sonnet.percent)
    }

    func testClaudeFableDualPoolMainAndDedicatedPercent() throws {
        // 35M tokens of Fable (1x weight, main pool): 35,000,000 / 115,000,000 ≈ 0.3043%
        // 专属池：35,000,000 / 600,000 ≈ 58.33%
        let fable = try XCTUnwrap(ModelQuotaEstimator.estimateWeeklyQuota(
            modelID: "claude-fable-5-1", label: "Claude Fable 5.1", agentID: "claude", tokens: 35_000_000
        ))
        XCTAssertEqual(fable.agentID, "claude")
        XCTAssertEqual(fable.percent, 35_000_000.0 / 115_000_000.0, accuracy: 0.0001)
        let dedicated = try XCTUnwrap(fable.dedicatedPercent)
        XCTAssertEqual(dedicated, 35_000_000.0 / 600_000.0, accuracy: 0.01)
    }

    func testCodexGPT6AstraHeavierWeightThanGPT56() throws {
        // 22M tokens of GPT-5.6 (1x weight): 22,000,000 / 22,000,000 = 1.0%
        let gpt56 = try XCTUnwrap(ModelQuotaEstimator.estimateWeeklyQuota(
            modelID: "gpt-5.6-sol", label: "GPT-5.6 Sol", agentID: "codex", tokens: 22_000_000
        ))
        XCTAssertEqual(gpt56.percent, 1.0, accuracy: 0.0001)

        // 7.33...M tokens of GPT-6 Astra (3x weight): 7,333,333 * 3 / 22,000,000 ≈ 1.0%
        let gpt6 = try XCTUnwrap(ModelQuotaEstimator.estimateWeeklyQuota(
            modelID: "gpt-6-astra", label: "GPT-6 Astra", agentID: "codex", tokens: 7_333_333
        ))
        XCTAssertEqual(gpt6.percent, 1.0, accuracy: 0.001)
    }

    func testZeroTokensReturnsNilAndTinyTokensYieldSmallNonZeroPercent() {
        XCTAssertNil(ModelQuotaEstimator.estimateWeeklyQuota(modelID: "claude-sonnet-5", agentID: "claude", tokens: 0))

        // 5,000 tokens of Sonnet (1x weight): 5,000 / 115,000,000 ≈ 0.00435% — 极小但非零，且必须落在
        // 视图层「< 0.1%」展示门限（0.05）以下，与旧文本 API 的 "< 0.1%" 分支覆盖同一条件。
        let tiny = try? XCTUnwrap(ModelQuotaEstimator.estimateWeeklyQuota(
            modelID: "claude-sonnet-5", agentID: "claude", tokens: 5_000
        ))
        XCTAssertNotNil(tiny)
        XCTAssertLessThan(tiny?.percent ?? .infinity, 0.05)
        XCTAssertGreaterThan(tiny?.percent ?? 0, 0)
    }

    func testGeminiProHeavierWeightThanFlashAndScalesLinearlyWithTokens() throws {
        // 10M tokens of Gemini 3.8 Flash (1x weight): 10,000,000 / 10,000,000 = 1.0%
        let flash = try XCTUnwrap(ModelQuotaEstimator.estimateWeeklyQuota(
            modelID: "gemini-3.8-flash", label: "gemini-3.8-flash", agentID: "antigravity", tokens: 10_000_000
        ))
        XCTAssertEqual(flash.percent, 1.0, accuracy: 0.0001)

        // 2.5M tokens of Gemini Pro (4x weight): 2,500,000 * 4 / 10,000,000 = 1.0%
        let pro = try XCTUnwrap(ModelQuotaEstimator.estimateWeeklyQuota(
            modelID: "gemini-pro-default", label: "gemini-pro-default", agentID: "antigravity", tokens: 2_500_000
        ))
        XCTAssertEqual(pro.percent, 1.0, accuracy: 0.0001)

        // 50M tokens of Gemini 3.8 Flash (线性缩放): 50,000,000 / 10,000,000 = 5.0%
        let largeFlash = try XCTUnwrap(ModelQuotaEstimator.estimateWeeklyQuota(
            modelID: "gemini-3.8-flash", label: "Gemini 3.8 Flash", agentID: "antigravity", tokens: 50_000_000
        ))
        XCTAssertEqual(largeFlash.percent, 5.0, accuracy: 0.0001)
    }

    // MARK: - #175 结构化 API：额度占比按 Agent 归属

    func testStructuredEstimateAttributesAntigravityHostedClaudeModelToAntigravityNotClaude() throws {
        let raw = ModelQuotaEstimator.estimateWeeklyQuota(
            modelID: "claude-opus-4-6-thinking",
            label: "claude-opus-4-6-thinking",
            agentID: "antigravity",
            tokens: 10_000_000
        )
        let estimate = try XCTUnwrap(raw)
        XCTAssertEqual(estimate.agentID, "antigravity")
        XCTAssertEqual(estimate.percent, 5.0, accuracy: 0.0001)
        XCTAssertNil(estimate.dedicatedPercent)
    }

    func testStructuredEstimateReturnsNilForNonClaudeModelUnderClaudeAgent() {
        let estimate = ModelQuotaEstimator.estimateWeeklyQuota(
            modelID: "deepseek-v4-pro",
            label: "DeepSeek V4 Pro",
            agentID: "claude",
            tokens: 5_000_000
        )
        XCTAssertNil(estimate)
    }

    func testStructuredEstimateStillReturnsClaudeForRealClaudeModelUnderClaudeAgent() throws {
        let raw = ModelQuotaEstimator.estimateWeeklyQuota(
            modelID: "claude-opus-5",
            label: "Claude Opus 5",
            agentID: "claude",
            tokens: 23_000_000
        )
        let estimate = try XCTUnwrap(raw)
        XCTAssertEqual(estimate.agentID, "claude")
        XCTAssertEqual(estimate.percent, 1.0, accuracy: 0.0001)
    }

    /// #175 决策：Agent 归属优先于模型名——Codex Agent 下即便模型名像 Claude 也按 Codex 基准计算，
    /// 不归到 Claude。旧文本 API 删除前由 `SourceHierarchyTests.testFlatModelsReflectAgentOwnershipDecisionForNonFamilyModelNames` 覆盖。
    func testStructuredEstimateUsesCodexBaselineForClaudeLikeModelNameUnderCodexAgent() throws {
        let raw = ModelQuotaEstimator.estimateWeeklyQuota(
            modelID: "claude-mini",
            label: "claude-mini",
            agentID: "codex",
            tokens: 22_000_000
        )
        let estimate = try XCTUnwrap(raw)
        XCTAssertEqual(estimate.agentID, "codex")
        // 22,000,000 * 1(默认权重) / 22,000,000(Codex 基准) = 1.0%，不是"未知"或按 Claude 基准计算。
        XCTAssertEqual(estimate.percent, 1.0, accuracy: 0.0001)
    }
}
