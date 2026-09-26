import Foundation

/// 结构化的模型周额度估算结果。
///
/// `agentID` 是估算所归属的 Agent（"claude" / "codex" / "antigravity"），按 #175 决策，
/// 额度占比归属模型**所在 Agent**，而不是模型名本身暗示的厂商（Antigravity 里调用的
/// claude-opus 记为 Antigravity，不记 Claude）。
public struct ModelQuotaEstimate: Equatable, Sendable {
    public let agentID: String
    public let percent: Double
    /// 仅 Claude Fable 有专属池：主池占比之外的专属池占比。
    public let dedicatedPercent: Double?

    public init(agentID: String, percent: Double, dedicatedPercent: Double? = nil) {
        self.agentID = agentID
        self.percent = percent
        self.dedicatedPercent = dedicatedPercent
    }
}

/// 基于 7 天滑动窗口与多因素权重的模型周额度折算估算器。
///
/// 官方额度并不是简单的 `token_count` 线性对应，而是多元影响（模型算力倍率、Prompt Caching 折算、输出权重大于输入）。
/// 本折算器采用 7 天滑动窗口（Rolling 7-Day Window）基准，能够自适应官方限流策略与价格策略的微调。
public enum ModelQuotaEstimator: Sendable {

    /// Claude 通用周额度池（Sonnet 等价基准）：1% 周额度约 1.15 亿 Sonnet 等价 Tokens
    public static let claudeWeeklySonnetEquivalentPerPercent: Double = 115_000_000.0

    /// Claude Fable 专属周额度池基准：1% 专属额度约 60 万 Tokens
    public static let claudeFableDedicatedPerPercent: Double = 600_000.0

    /// Codex 通用周额度池（GPT-5.6 等价基准）：1% 周额度约 2,200 万 GPT-5.6 等价 Tokens
    public static let codexWeeklyGPT56EquivalentPerPercent: Double = 22_000_000.0

    /// Gemini / Antigravity 通用周额度池（Flash 等价基准）：1% 周额度约 1,000 万 Flash 等价 Tokens
    public static let geminiWeeklyFlashEquivalentPerPercent: Double = 10_000_000.0

    /// 估算模型 Token 对应的周额度占比（结构化结果）。
    ///
    /// 归属规则：Agent 优先于模型名——Antigravity 通道里调用的 claude-opus 也记为 Antigravity。
    /// 当 `agentID` 为空时，回退到按模型名推断（向后兼容旧调用点）。
    /// Claude Agent 下如果模型名完全不像 Claude 系（例如 deepseek-v4-pro），视为不计入 Claude
    /// 周额度，返回 nil（#175 决策记录）。
    /// - Parameters:
    ///   - modelID: 模型 ID（如 "claude-opus-5", "gpt-5.6-sol", "gemini-3.8-flash"）
    ///   - label: 模型展示标签
    ///   - agentID: 归属 Agent（如 "claude", "codex", "antigravity"）
    ///   - tokens: 实际消耗 Token 总量
    /// - Returns: 结构化估算结果；无法估算（tokens<=0，或 Claude Agent 下的非 Claude 系模型）时为 nil。
    public static func estimateWeeklyQuota(
        modelID: String,
        label: String = "",
        agentID: String = "",
        tokens: Int
    ) -> ModelQuotaEstimate? {
        guard tokens > 0 else { return nil }

        let normalizedKey = "\(modelID) \(label)".lowercased()
        let agent = agentID.lowercased()

        let looksLikeClaudeFamily = normalizedKey.contains("claude") || normalizedKey.contains("sonnet")
            || normalizedKey.contains("opus") || normalizedKey.contains("fable") || normalizedKey.contains("haiku")
        let looksLikeGemini = normalizedKey.contains("gemini")
        let looksLikeCodex = normalizedKey.contains("gpt") || normalizedKey.contains("sol")
            || normalizedKey.contains("astra") || normalizedKey.contains("luna")

        // 1. Antigravity / Gemini 系列：Agent 归属优先于模型名。
        if agent.contains("antigravity") || agent.contains("gemini") || (agent.isEmpty && looksLikeGemini) {
            let weight: Double
            if normalizedKey.contains("pro") {
                weight = 4.0
            } else if looksLikeClaudeFamily {
                weight = 5.0
            } else {
                // gemini-3.8-flash, gemini-3.7-flash, gemini-3-flash, gemini-2.5-flash 等 Flash 系列基准
                weight = 1.0
            }
            let percent = (Double(tokens) * weight) / geminiWeeklyFlashEquivalentPerPercent
            return ModelQuotaEstimate(agentID: "antigravity", percent: percent)
        }

        // 2. Codex / OpenAI 系列
        if agent.contains("codex") || agent.contains("openai") || (agent.isEmpty && looksLikeCodex) {
            let weight: Double
            if normalizedKey.contains("gpt-6") || normalizedKey.contains("astra") {
                weight = 3.0
            } else if normalizedKey.contains("review") {
                weight = 0.5
            } else {
                weight = 1.0 // GPT-5.6 (Sol / Luna)
            }
            let percent = (Double(tokens) * weight) / codexWeeklyGPT56EquivalentPerPercent
            return ModelQuotaEstimate(agentID: "codex", percent: percent)
        }

        // 3. Claude 系列（非 Antigravity 渠道）
        if agent.contains("claude") || (agent.isEmpty && looksLikeClaudeFamily) {
            guard looksLikeClaudeFamily else {
                // Claude Agent 下出现的非 Claude 系模型（如 deepseek-v4-pro）：不计入 Claude 周额度。
                return nil
            }
            let isFable = normalizedKey.contains("fable")
            let weight: Double
            if normalizedKey.contains("opus") {
                weight = 5.0
            } else if normalizedKey.contains("haiku") {
                weight = 0.2
            } else {
                weight = 1.0 // Sonnet, Fable, etc.
            }
            let mainPercent = (Double(tokens) * weight) / claudeWeeklySonnetEquivalentPerPercent
            if isFable {
                // Fable 有专属池子，但也会在通用大池子里占用份额
                let dedicatedPercent = Double(tokens) / claudeFableDedicatedPerPercent
                return ModelQuotaEstimate(agentID: "claude", percent: mainPercent, dedicatedPercent: dedicatedPercent)
            }
            return ModelQuotaEstimate(agentID: "claude", percent: mainPercent)
        }

        return nil
    }
}
