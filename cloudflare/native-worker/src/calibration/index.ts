/**
 * #183-a：计算内核入口。把「一批官方额度读数 + 一批小时聚合事实」变成
 * `[{provider, model_family, coef, effective_delta_u, backtest_max_err, grade, sample_intervals,
 * formula_version}]`。纯函数，不做任何 D1 读写——落库、cron 接线是 #183-b 的事。
 *
 * 步骤对应 #183 设计 v1 §1-2：
 * 1. 整个 provider 账户的官方读数合并成一条时间线切周期、补重置锚点（cycles.ts）。
 * 2. 合并相邻读数成 ≥3 小时区间，剔除饱和起点，按重叠比例分摊小时事实（intervals.ts）。
 * 3. 近期加权（半衰期）+ 突变检测（周期边界前后系数偏离 >2 倍时只用变化点之后的全部数据）。
 * 4. 非负最小二乘拟合出最终系数（nnls.ts）。
 * 5. 逐日留出回测定级（backtest.ts）。
 *
 * v2（#271）在 2 与 3 之间加两步：
 * - 训练集只取最近一个已知订阅计量变更日（`KNOWN_CHANGE_POINTS`）之后的区间；
 * - 有价比先验（`FAMILY_PRICE_RATIO`）的族合并成一列特征 Σ 价比×加权 token，共用一个系数
 *   （单一隐藏额度）；没有价比的族仍各自一列。拟合后按价比把共用系数拆回各族。
 *   好处：参数从「族数」降到 1，新族零样本时也能按价比估算；代价是假设订阅计量与价目成比例，
 *   #271 用生产回放验证过 Claude 与 Codex（09-29 之后）都成立。
 *
 * 周期切分为什么不按 `source_id` 分组：v1 账户口径是「每个 provider 一个账户」——同一账户的
 * 官方额度读数可能被多台机器各自的采集端重复上报，它们描述的是同一份真实配额状态，不是
 * 各自独立的时间线。实测过按 source 分组切周期：两台机器各自的重置检测互相独立，会把同一次
 * 真实重置数出两次（Codex 两个 source 各自算出 2 次和 3 次重置，加总 5 次，跟数据完整性核查
 * 里「9/19、9/26 两次自然 + 9/26 一次手动」这个从原始数据看到的真实重置事件数不一致）。
 * 合并成一条时间线后 Claude 得到 1 次重置，跟设计文档记录一致。
 */
import { FAMILY_PRICE_RATIO, FORMULA_VERSION, KNOWN_FAMILIES, PRICED_FEATURE, trainingStartFor } from "./constants";
import type { Provider } from "./constants";
import { splitCycles, withResetAnchors } from "./cycles";
import { buildIntervals } from "./intervals";
import { grade, intervalToRow, leaveOneDayOutDeviation, toSamples } from "./backtest";
import type { Sample } from "./backtest";
import { nonNegativeLeastSquares, predictRow } from "./nnls";
import type { CalibrateOptions, CalibrationOutput, CalibrationResult, HourlyFamilyFact, Interval, LimitObservation } from "./types";

const DEFAULT_WINDOW_DAYS = 28;
const DEFAULT_HALF_LIFE_DAYS = 7;
/** 突变检测的偏离倍数门槛：重置后系数比全量系数偏离超过这个倍数才触发「只用突变后数据」。 */
const MUTATION_RATIO_THRESHOLD = 2;
/**
 * 判断系数是否「有意义」的下限，避免用接近 0 的系数算比值得出虚假的巨大倍数。
 * 系数单位是「额度点 / 每个价格加权 token」，真实值约 3e-8～1.6e-6；门槛必须远低于这个量级，
 * 只用来排除 NNLS 压到 0 的族（#206：曾误设为 1e-6，所有族都被跳过，突变检测从未生效）。
 */
const MEANINGFUL_COEF_EPSILON = 1e-12;
/** 突变检测时变化点前后两段各自至少需要的区间数，太少的段拟合不出可比的系数。 */
const MIN_SEGMENT_INTERVALS_FOR_MUTATION_CHECK = 3;
/** 只比较在前后两段里价格加权 token 占比都不低于这个比例的族；小占比族的系数本身不稳定。 */
const MIN_FAMILY_SHARE_FOR_MUTATION_CHECK = 0.2;
/**
 * 切成两段后的加权残差平方和必须不超过「不切分、全量拟合」的这个比例才认定突变——切分本身
 * 一定让残差下降，不和全量比较时，比值门槛一旦被噪音触发就必判突变（#206 评审：按小时重放
 * 生产数据，Claude 有 19 个时刻被误判，B 级降成 none）。
 */
const MAX_SPLIT_SSE_RATIO = 0.5;
/**
 * 变化点前后两段各自至少需要的累计 ΔU（额度点）。官方读数是整数百分比，累计不足 10 点的段
 * 光取整误差就 >10%，拟合出的系数比值不可信（#206：Antigravity 3 天 18 个碎周期里，一个
 * 只有 3 点的前段被误判成突变，凑出了假的 B 级）。
 */
const MIN_SEGMENT_DELTA_U_FOR_MUTATION_CHECK = 10;
/**
 * 只检查最近这么多个合格边界，限制每次 cron 额外 NNLS 次数，守住 Free 计划单次 10ms CPU 预算。
 * 周窗口账户 28 天内约 4–5 个自然边界，基本全覆盖；碎周期多的账户（如 Antigravity）更早的变化点
 * 可能被略过，此时退化为混用新旧数据，只会让回测误差偏大、定级更保守，不会错误升级。
 */
const MAX_CHANGE_POINT_CANDIDATES = 4;

function recencyWeight(interval: Interval, now: Date, halfLifeDays: number): number {
  const ageMs = now.getTime() - Date.parse(interval.t1);
  const ageDays = Math.max(0, ageMs / (24 * 60 * 60 * 1000));
  return Math.pow(0.5, ageDays / halfLifeDays);
}

function fit(rows: number[][], targets: number[], weights: number[]): number[] {
  return nonNegativeLeastSquares(rows, targets, weights);
}

/**
 * 构建一个 provider 账户下的全部区间：所有 source_id 的官方读数合并成一条时间线切周期、
 * 补锚点，再合并成区间。`Interval.sourceId` 只保留「这条区间起点读数来自哪个 source」的
 * 溯源信息，不影响周期切分或拟合。
 */
function buildAllIntervals(
  provider: Provider,
  observations: LimitObservation[],
  facts: HourlyFamilyFact[],
): { intervals: Interval[]; droppedForUnattributed: number } {
  const cycles = withResetAnchors(splitCycles(observations));
  return buildIntervals(provider, "combined", cycles, facts);
}

function familyShares(rows: number[][]): number[] {
  const totals = rows[0].map((_, idx) => rows.reduce((sum, row) => sum + row[idx], 0));
  const all = totals.reduce((sum, v) => sum + v, 0);
  return totals.map((v) => (all > 0 ? v / all : 0));
}

function significantlyDifferent(a: number[], b: number[], sharesA: number[], sharesB: number[]): boolean {
  for (let idx = 0; idx < a.length; idx++) {
    if (sharesA[idx] < MIN_FAMILY_SHARE_FOR_MUTATION_CHECK || sharesB[idx] < MIN_FAMILY_SHARE_FOR_MUTATION_CHECK) continue;
    if (a[idx] <= MEANINGFUL_COEF_EPSILON || b[idx] <= MEANINGFUL_COEF_EPSILON) continue;
    const ratio = b[idx] / a[idx];
    if (ratio > MUTATION_RATIO_THRESHOLD || ratio < 1 / MUTATION_RATIO_THRESHOLD) return true;
  }
  return false;
}

function weightedSse(rows: number[][], targets: number[], weights: number[], coef: number[]): number {
  let sse = 0;
  for (let n = 0; n < rows.length; n++) {
    const residual = predictRow(rows[n], coef) - targets[n];
    sse += weights[n] * residual * residual;
  }
  return sse;
}

/**
 * 突变检测（#206）：在周期边界上找「规则变化点」。对每个候选边界 k，把区间分成 k 之前 / k 之后
 * 两段各自拟合；两段都占足份额的族里有任一族系数偏离超过 MUTATION_RATIO_THRESHOLD 倍、且切分后
 * 残差明显低于全量拟合，才算候选，候选中取两段加权残差平方和最小的那个边界。检测到时训练集 = 变化点之后的**全部**周期——不是只取
 * 最近一个周期，否则每次周重置后训练集都缩回几条区间，新规则下的数据永远攒不过一周。
 */
export function detectMutationAndSelectTrainingSet<T extends Interval>(
  intervals: T[],
  keys: string[],
  weightOf: (i: T) => number,
): { training: T[]; mutationDetected: boolean } {
  const cycleIds = [...new Set(intervals.map((i) => i.cycleIndex))].sort((x, y) => x - y);
  const sumDeltaU = (segment: T[]) => segment.reduce((sum, i) => sum + i.deltaU, 0);
  const qualifies = (segment: T[]) =>
    segment.length >= MIN_SEGMENT_INTERVALS_FOR_MUTATION_CHECK && sumDeltaU(segment) >= MIN_SEGMENT_DELTA_U_FOR_MUTATION_CHECK;
  const candidates = cycleIds.slice(1)
    .map((k) => ({ head: intervals.filter((i) => i.cycleIndex < k), tail: intervals.filter((i) => i.cycleIndex >= k) }))
    .filter(({ head, tail }) => qualifies(head) && qualifies(tail))
    .slice(-MAX_CHANGE_POINT_CANDIDATES);
  if (candidates.length === 0) return { training: intervals, mutationDetected: false };
  const allRows = intervals.map((i) => intervalToRow(i, keys));
  const allTargets = intervals.map((i) => i.deltaU);
  const allWeights = intervals.map(weightOf);
  const sseFull = weightedSse(allRows, allTargets, allWeights, fit(allRows, allTargets, allWeights));
  let best: { tail: T[]; sse: number } | null = null;
  for (const { head, tail } of candidates) {
    const headRows = head.map((i) => intervalToRow(i, keys));
    const tailRows = tail.map((i) => intervalToRow(i, keys));
    const headTargets = head.map((i) => i.deltaU);
    const tailTargets = tail.map((i) => i.deltaU);
    const headWeights = head.map(weightOf);
    const tailWeights = tail.map(weightOf);
    const headCoef = fit(headRows, headTargets, headWeights);
    const tailCoef = fit(tailRows, tailTargets, tailWeights);
    if (!significantlyDifferent(headCoef, tailCoef, familyShares(headRows), familyShares(tailRows))) continue;
    const sse = weightedSse(headRows, headTargets, headWeights, headCoef) + weightedSse(tailRows, tailTargets, tailWeights, tailCoef);
    if (sse > MAX_SPLIT_SSE_RATIO * sseFull) continue;
    if (best === null || sse < best.sse) best = { tail, sse };
  }
  return best ? { training: best.tail, mutationDetected: true } : { training: intervals, mutationDetected: false };
}

/** 拟合用的区间：`familyPricedTokens` 换成特征列，原始逐族加权 token 留在 `familyTokens`。 */
type FeaturedInterval = Interval & { familyTokens: Record<string, number> };

function isPriced(provider: Provider, family: string): boolean {
  return Object.hasOwn(FAMILY_PRICE_RATIO[provider], family);
}

/** 特征列：有价比的族合并成 `PRICED_FEATURE` 一列，其余已知族各自一列。 */
function featureKeys(provider: Provider): string[] {
  const unpriced = KNOWN_FAMILIES[provider].filter((family) => !isPriced(provider, family));
  return KNOWN_FAMILIES[provider].some((family) => isPriced(provider, family)) ? [PRICED_FEATURE, ...unpriced] : unpriced;
}

function toFeatured(provider: Provider, interval: Interval): FeaturedInterval {
  const features: Record<string, number> = {};
  for (const [family, tokens] of Object.entries(interval.familyPricedTokens)) {
    const key = isPriced(provider, family) ? PRICED_FEATURE : family;
    const value = isPriced(provider, family) ? FAMILY_PRICE_RATIO[provider][family] * tokens : tokens;
    features[key] = (features[key] ?? 0) + value;
  }
  return { ...interval, familyPricedTokens: features, familyTokens: interval.familyPricedTokens };
}

export function calibrate(
  provider: Provider,
  observations: LimitObservation[],
  facts: HourlyFamilyFact[],
  options: CalibrateOptions,
): CalibrationOutput {
  const windowDays = options.windowDays ?? DEFAULT_WINDOW_DAYS;
  const halfLifeDays = options.halfLifeDays ?? DEFAULT_HALF_LIFE_DAYS;
  const now = options.now;
  const windowStartMs = now.getTime() - windowDays * 24 * 60 * 60 * 1000;
  const changePoint = trainingStartFor(provider, now);
  const trainingStartMs = changePoint === null ? windowStartMs : Math.max(windowStartMs, Date.parse(changePoint));

  const windowedObservations = observations.filter((o) => Date.parse(o.observed_at) >= windowStartMs);
  const built = buildAllIntervals(provider, windowedObservations, facts);
  const intervals = built.intervals
    .filter((i) => Date.parse(i.t0) >= trainingStartMs)
    .map((i) => toFeatured(provider, i));

  const families = KNOWN_FAMILIES[provider];
  const keys = featureKeys(provider);
  const weightOf = (i: Interval) => recencyWeight(i, now, halfLifeDays);

  const fittedAt = now.toISOString();

  if (intervals.length === 0) {
    return {
      unattributedDroppedIntervals: built.droppedForUnattributed,
      results: families.map((family) => ({
        provider,
        model_family: family,
        coef: 0,
        effective_delta_u: 0,
        backtest_max_err: null,
        grade: "none",
        sample_intervals: 0,
        formula_version: FORMULA_VERSION,
        fitted_at: fittedAt,
      })),
    };
  }

  const { training } = detectMutationAndSelectTrainingSet(intervals, keys, weightOf);

  // Sample 只算一次：特征向量、近期加权、dayKey 都不随「留出哪一天」变化，
  // 逐日留出回测（backtest.ts）复用同一批 Sample，只重新跑 NNLS。
  const samples: Sample[] = toSamples(training, keys, weightOf);

  const finalCoef = fit(
    samples.map((s) => s.row),
    samples.map((s) => s.deltaU),
    samples.map((s) => s.weight),
  );
  const coefOf = (key: string) => finalCoef[keys.indexOf(key)] ?? 0;

  const backtestDeviation = leaveOneDayOutDeviation(samples, fit);

  const familyTokens = (family: string) => training.reduce((sum, i) => sum + (i.familyTokens[family] ?? 0), 0);
  const pricedGroupDeltaU = families
    .filter((family) => isPriced(provider, family))
    .reduce((sum, family) => sum + coefOf(PRICED_FEATURE) * FAMILY_PRICE_RATIO[provider][family] * familyTokens(family), 0);

  const results: CalibrationResult[] = families.map((family) => {
    const priced = isPriced(provider, family);
    const coef = priced ? coefOf(PRICED_FEATURE) * FAMILY_PRICE_RATIO[provider][family] : coefOf(family);
    const effectiveDeltaU = coef * familyTokens(family);
    let familyGrade = grade(priced ? pricedGroupDeltaU : effectiveDeltaU, backtestDeviation);
    // 有价比的族靠共用系数估算：自身样本不足 A 档门槛时最多 B（零样本的新族冷启动即落在这里）。
    if (priced && familyGrade === "A" && effectiveDeltaU < 10) familyGrade = "B";
    return {
      provider,
      model_family: family,
      coef,
      effective_delta_u: effectiveDeltaU,
      backtest_max_err: backtestDeviation,
      grade: familyGrade,
      sample_intervals: training.length,
      formula_version: FORMULA_VERSION,
      fitted_at: fittedAt,
    };
  });

  return { results, unattributedDroppedIntervals: built.droppedForUnattributed };
}

export { predictRow };
export type { CalibrationOutput, CalibrationResult, HourlyFamilyFact, Interval, LimitObservation } from "./types";
export { FORMULA_VERSION, UNATTRIBUTED_FAMILY, UNATTRIBUTED_DROP_RATIO } from "./constants";
export { isStale } from "./staleness";
