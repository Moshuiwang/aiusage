import Foundation

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

    /// 估算模型 Token 对应的周额度百分比文本
    /// - Parameters:
    ///   - modelID: 模型 ID（如 "claude-opus-5", "gpt-5.6-sol", "gemini-3.8-flash"）
    ///   - label: 模型展示标签
    ///   - agentID: 归属 Agent（如 "claude", "codex", "antigravity"）
    ///   - tokens: 实际消耗 Token 总量
    /// - Returns: 格式化的周额度百分比文本，例如 "约占周额度 2.4%"
    public static func estimateWeeklyQuotaPercentText(
        modelID: String,
        label: String = "",
        agentID: String = "",
        tokens: Int
    ) -> String? {
        guard tokens > 0 else { return nil }

        let normalizedKey = "\(modelID) \(label)".lowercased()
        let agent = agentID.lowercased()

        // 1. Claude 系列（非 Antigravity 渠道）
        if (agent.contains("claude") || normalizedKey.contains("claude") || normalizedKey.contains("sonnet") || normalizedKey.contains("opus") || normalizedKey.contains("fable") || normalizedKey.contains("haiku")) && !agent.contains("antigravity") && !agent.contains("gemini") {
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
                return formatFablePercent(mainPercent: mainPercent, dedicatedPercent: dedicatedPercent)
            } else {
                return formatPercent(mainPercent)
            }
        }

        // 2. Codex / OpenAI 系列
        if agent.contains("codex") || agent.contains("openai") || normalizedKey.contains("gpt") || normalizedKey.contains("sol") || normalizedKey.contains("astra") || normalizedKey.contains("luna") {
            let weight: Double
            if normalizedKey.contains("gpt-6") || normalizedKey.contains("astra") {
                weight = 3.0
            } else if normalizedKey.contains("review") {
                weight = 0.5
            } else {
                weight = 1.0 // GPT-5.6 (Sol / Luna)
            }

            let percent = (Double(tokens) * weight) / codexWeeklyGPT56EquivalentPerPercent
            return formatPercent(percent)
        }

        // 3. Gemini / Antigravity 系列
        if agent.contains("antigravity") || agent.contains("gemini") || normalizedKey.contains("gemini") {
            let weight: Double
            if normalizedKey.contains("pro") {
                weight = 4.0
            } else if normalizedKey.contains("claude") || normalizedKey.contains("opus") {
                weight = 5.0
            } else {
                // gemini-3.8-flash, gemini-3.7-flash, gemini-3-flash, gemini-2.5-flash 等 Flash 系列基准
                weight = 1.0
            }

            let percent = (Double(tokens) * weight) / geminiWeeklyFlashEquivalentPerPercent
            return formatPercent(percent)
        }

        return nil
    }

    private static func formatPercent(_ percent: Double) -> String {
        if percent < 0.05 {
            return "约占周额度 < 0.1%"
        } else {
            return String(format: "约占周额度 %.1f%%", percent)
        }
    }

    private static func formatFablePercent(mainPercent: Double, dedicatedPercent: Double) -> String {
        let mainStr = mainPercent < 0.05 ? "< 0.1%" : String(format: "%.1f%%", mainPercent)
        let dedicatedStr = dedicatedPercent < 0.05 ? "< 0.1%" : String(format: "%.0f%%", dedicatedPercent)
        return "约占周额度 \(mainStr) (专属约 \(dedicatedStr))"
    }
}
