/**
 * #183-a：官方额度持续校准——计算内核共享常量。
 *
 * 模型族映射与价格加权口径集中定义在这一个文件，其它模块（区间构造、拟合、回测）都从这里
 * 读取，不各自重复判断逻辑。`FORMULA_VERSION` 随口径变化递增，写入 `quota_calibration` 供
 * #183-b 落库时标记「这批系数是用哪个公式算出来的」。
 */

/** 口径版本号。价格加权系数、族映射规则任何一处变化都要递增这个值。 */
export const FORMULA_VERSION = "v1";

export type Provider = "claude" | "codex" | "antigravity";

/** 每种 token 类型的价格加权系数。cache_creation 与 cache_read 两账户目前共用同一套比例。 */
export interface PriceWeights {
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
}

/**
 * Claude output 定价是 input 的 5 倍；Codex 是 8 倍（#183 设计 v1 §1）。
 * Antigravity 暂无独立验证数据，先套用 Claude 口径并在输出里标注待验证——
 * 不新增第三套未经验证的常量，避免看起来「更精确」但实际是编造。
 */
export const PRICE_WEIGHTS: Record<Provider, PriceWeights> = {
  claude: { input_tokens: 1, output_tokens: 5, cache_creation_tokens: 1.25, cache_read_tokens: 0.1 },
  codex: { input_tokens: 1, output_tokens: 8, cache_creation_tokens: 1.25, cache_read_tokens: 0.1 },
  antigravity: { input_tokens: 1, output_tokens: 5, cache_creation_tokens: 1.25, cache_read_tokens: 0.1 },
};

/** Antigravity 价格加权口径尚未有独立验证数据支撑，下发时需要标注。 */
export const ANTIGRAVITY_PRICE_WEIGHTS_UNVERIFIED = true;

export const TOKEN_TYPES: Array<keyof PriceWeights> = [
  "input_tokens",
  "output_tokens",
  "cache_creation_tokens",
  "cache_read_tokens",
];

/**
 * 数据完整性核查发现：部分小时事实缺模型行（Codex mac-local 9/14–9/20 100% 缺失、
 * linux-biai-wangzp 仅 8.3% 覆盖），fixture 生成脚本据此把「fact 总 token − 其 model 行
 * 合计」的差额落到这个伪族名下（无 model 行则全额落到这里）。这不是一个可以拟合系数的
 * 真实模型族——`KNOWN_FAMILIES` 不包含它，NNLS 特征矩阵也不会给它建列，它只用来在
 * `intervals.ts` 判断「这个区间的数据完整性够不够拿来拟合」。
 */
export const UNATTRIBUTED_FAMILY = "unattributed";

/** 区间内 unattributed 加权 token 占该账户加权 token 总量的比例超过这个门槛就整段剔除。 */
export const UNATTRIBUTED_DROP_RATIO = 0.05;

/**
 * 模型族映射：按子串匹配，顺序即优先级（先匹配到的族生效）。
 * Claude agent 下非 Anthropic 模型（deepseek 等）不属于任何族，`familyForModel` 返回 null，
 * 调用方必须把这类事实整体丢弃，不落到某个族名下（不能伪造成 "other"）。
 */
const FAMILY_MATCHERS: Record<Provider, Array<{ family: string; match: (modelLower: string) => boolean }>> = {
  claude: [
    { family: "opus", match: (m) => m.includes("opus") },
    { family: "sonnet", match: (m) => m.includes("sonnet") },
    { family: "haiku", match: (m) => m.includes("haiku") },
    { family: "fable", match: (m) => m.includes("fable") },
  ],
  // Codex 按档位分族（#206）：同一版本前缀下 astra / sol / luna 的额度消耗相差十倍以上，
  // 版本号（gpt-6 / gpt-6.1 / gpt-5.6）不决定消耗。没有档位名的模型（本地 qwen 等）不属于任何族。
  // 已知风险：将来若出现消耗 Codex 额度却不带档位名的模型（如裸 gpt-7），它会被排除出拟合且
  // 不进 unattributed，系数会被低估；读侧对其如实显示 unsupported_model。出现新档位时在此补一行。
  codex: [
    { family: "review", match: (m) => m.includes("review") },
    { family: "astra", match: (m) => m.includes("astra") },
    { family: "sol", match: (m) => m.includes("-sol") },
    { family: "luna", match: (m) => m.includes("luna") },
    { family: "terra", match: (m) => m.includes("terra") },
  ],
  antigravity: [
    { family: "flash", match: (m) => m.includes("flash") },
    { family: "pro", match: (m) => m.includes("pro") },
    { family: "claude-on-antigravity", match: (m) => m.includes("claude") },
  ],
};

/** 每个 provider 下所有已知模型族（用于「训练集里未见过的族」判断，见 backtest.ts）。 */
export const KNOWN_FAMILIES: Record<Provider, string[]> = {
  claude: FAMILY_MATCHERS.claude.map((m) => m.family),
  codex: FAMILY_MATCHERS.codex.map((m) => m.family),
  antigravity: FAMILY_MATCHERS.antigravity.map((m) => m.family),
};

/**
 * 把某个 provider 下的模型名解析成模型族。大小写不敏感。
 * 返回 null 表示这个模型不属于任何已知族——调用方（interval 构造）必须整条丢弃，
 * 不能落到某个兜底族名下，否则会把「未知模型」的 token 量算进已知族的系数里。
 */
export function familyForModel(provider: Provider, modelName: string): string | null {
  const lower = modelName.toLowerCase();
  const matchers = FAMILY_MATCHERS[provider];
  for (const m of matchers) {
    if (m.match(lower)) return m.family;
  }
  return null;
}

/** 某个族对应的价格加权系数总和（Σ token_type × price_weight，单位：原始 token 数）。 */
export function priceWeightedTokens(
  provider: Provider,
  tokens: { input_tokens: number; output_tokens: number; cache_creation_tokens: number; cache_read_tokens: number },
): number {
  const w = PRICE_WEIGHTS[provider];
  return (
    tokens.input_tokens * w.input_tokens +
    tokens.output_tokens * w.output_tokens +
    tokens.cache_creation_tokens * w.cache_creation_tokens +
    tokens.cache_read_tokens * w.cache_read_tokens
  );
}
