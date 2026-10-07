/**
 * #183-a：官方额度持续校准——计算内核共享常量。
 *
 * 模型族映射与价格加权口径集中定义在这一个文件，其它模块（区间构造、拟合、回测）都从这里
 * 读取，不各自重复判断逻辑。`FORMULA_VERSION` 随口径变化递增，写入 `quota_calibration` 供
 * #183-b 落库时标记「这批系数是用哪个公式算出来的」。
 */

/**
 * 口径版本号。价格加权系数、族映射规则、价比先验、定级口径任何一处变化都要递增这个值。
 * v2（#271）：同一 provider 下有价格的族共用一个系数（单一隐藏额度 × API 价比），
 * Codex 族内权重改按官方 credit 表，已知变更日强制切分，定级改看逐日留出总偏差。
 */
export const FORMULA_VERSION = "v2";

export type Provider = "claude" | "codex" | "antigravity";

/** 每种 token 类型的价格加权系数。cache_creation 与 cache_read 两账户目前共用同一套比例。 */
export interface PriceWeights {
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
}

/**
 * Claude output 定价是 input 的 5 倍（#183 设计 v1 §1）。Codex 按官方 credit 表
 * （learn.chatgpt.com/docs/pricing，2026-10-07 读取：output = 5× input、cached = 0.1× input），
 * #271 从 v1 的 8 倍改为 5 倍；cache_read 两家都按 0.1×——#271 生产回放显示 Claude 订阅计量
 * 没有传导 Opus 5.5（0.05×）/ Fable 5.1（0.025×）的缓存读降价，按 API 标价反而拟合更差。
 * Antigravity 暂无独立验证数据，先套用 Claude 口径并在输出里标注待验证——
 * 不新增第三套未经验证的常量，避免看起来「更精确」但实际是编造。
 */
export const PRICE_WEIGHTS: Record<Provider, PriceWeights> = {
  claude: { input_tokens: 1, output_tokens: 5, cache_creation_tokens: 1.25, cache_read_tokens: 0.1 },
  codex: { input_tokens: 1, output_tokens: 5, cache_creation_tokens: 1.25, cache_read_tokens: 0.1 },
  antigravity: { input_tokens: 1, output_tokens: 5, cache_creation_tokens: 1.25, cache_read_tokens: 0.1 },
};

/**
 * #271：族之间的价比先验。同一 provider 下列在这里的族共用一个拟合参数（单一隐藏额度），
 * 各族系数 = 该参数 × 本表的值；只有比值有意义，单位按各家公开价目取：
 * - Claude：当前代各族 API input 价（$/MTok：Opus 5.5 $4、Sonnet 5.5 $2、Haiku 4.5 $1、Fable 5.1 $10）；
 * - Codex：官方 credit 表的 input credits / MTok（Astra 250、Sol 50、Luna 2.5；Terra 无官方 credit，
 *   按其 API 价 $2 与 Sol 同档）。review 无公开价，不列入，按 v1 方式单独拟合。
 * Antigravity 没有公开价目可用，全部族按 v1 方式各自拟合。
 */
export const FAMILY_PRICE_RATIO: Record<Provider, Record<string, number>> = {
  claude: { opus: 4, sonnet: 2, haiku: 1, fable: 10 },
  codex: { astra: 250, sol: 50, terra: 50, luna: 2.5 },
  antigravity: {},
};

/** 有价比先验的族在拟合特征里合并成的那一列。 */
export const PRICED_FEATURE = "priced";

/**
 * #271：已知的订阅计量变更日（UTC）。训练集只用 now 之前最近一个变更日之后的区间——变更日可能
 * 落在周期中段，按周重置边界找变化点的突变检测看不到它。
 * - 2026-09-22：GPT-6 Sol/Luna 上线，生产回放前后两段单位 credit 消耗额度相差约 2 倍；
 * - 2026-09-29：Pro $200 改用量计算（官方：新额度折合 API 消费减半），本账户回放再降约一半；
 * - 2026-10-29：官方公布的老 Pro $200 订阅额度过渡期结束日。
 */
export const KNOWN_CHANGE_POINTS: Record<Provider, string[]> = {
  claude: [],
  codex: ["2026-09-22T00:00:00Z", "2026-09-29T00:00:00Z", "2026-10-29T00:00:00Z"],
  antigravity: [],
};

/** now 之前（含）最近的一个已知变更日；没有则 null（训练窗口不额外截断）。 */
export function trainingStartFor(provider: Provider, now: Date): string | null {
  let latest: string | null = null;
  for (const point of KNOWN_CHANGE_POINTS[provider]) {
    if (Date.parse(point) <= now.getTime()) latest = point;
  }
  return latest;
}

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
