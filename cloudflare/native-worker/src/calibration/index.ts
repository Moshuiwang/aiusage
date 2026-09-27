/**
 * #183-a：计算内核入口。把「一批官方额度读数 + 一批小时聚合事实」变成
 * `[{provider, model_family, coef, effective_delta_u, backtest_max_err, grade, sample_intervals,
 * formula_version}]`。纯函数，不做任何 D1 读写——落库、cron 接线是 #183-b 的事。
 *
 * 步骤对应 #183 设计 v1 §1-2：
 * 1. 整个 provider 账户的官方读数合并成一条时间线切周期、补重置锚点（cycles.ts）。
 * 2. 合并相邻读数成 ≥3 小时区间，剔除饱和起点，按重叠比例分摊小时事实（intervals.ts）。
 * 3. 近期加权（半衰期）+ 突变检测（重置后系数偏离 >2 倍时只用突变后数据）。
 * 4. 非负最小二乘拟合出最终系数（nnls.ts）。
 * 5. 逐日留出回测定级（backtest.ts）。
 *
 * 周期切分为什么不按 `source_id` 分组：v1 账户口径是「每个 provider 一个账户」——同一账户的
 * 官方额度读数可能被多台机器各自的采集端重复上报，它们描述的是同一份真实配额状态，不是
 * 各自独立的时间线。实测过按 source 分组切周期：两台机器各自的重置检测互相独立，会把同一次
 * 真实重置数出两次（Codex 两个 source 各自算出 2 次和 3 次重置，加总 5 次，跟数据完整性核查
 * 里「9/19、9/26 两次自然 + 9/26 一次手动」这个从原始数据看到的真实重置事件数不一致）。
 * 合并成一条时间线后 Claude 得到 1 次重置，跟设计文档记录一致。
 */
import { FORMULA_VERSION, KNOWN_FAMILIES } from "./constants";
import type { Provider } from "./constants";
import { splitCycles, withResetAnchors } from "./cycles";
import { buildIntervals } from "./intervals";
import { grade, intervalToRow, leaveOneDayOutMaxError, toSamples } from "./backtest";
import type { Sample } from "./backtest";
import { nonNegativeLeastSquares, predictRow } from "./nnls";
import type { CalibrateOptions, CalibrationOutput, CalibrationResult, HourlyFamilyFact, Interval, LimitObservation } from "./types";

const DEFAULT_WINDOW_DAYS = 28;
const DEFAULT_HALF_LIFE_DAYS = 7;
/** 突变检测的偏离倍数门槛：重置后系数比全量系数偏离超过这个倍数才触发「只用突变后数据」。 */
const MUTATION_RATIO_THRESHOLD = 2;
/** 判断系数是否「有意义」的下限，避免用接近 0 的系数算比值得出虚假的巨大倍数。 */
const MEANINGFUL_COEF_EPSILON = 1e-6;
/** 最近一个周期作为「突变后数据」参与判定所需的最少区间数。 */
const MIN_RECENT_INTERVALS_FOR_MUTATION_CHECK = 3;

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

/** 最后一个周期的区间：突变检测里「重置后数据」的候选集合。 */
function mostRecentCycleIntervals(intervals: Interval[]): Interval[] {
  const maxCycle = intervals.reduce((max, i) => Math.max(max, i.cycleIndex), -1);
  return intervals.filter((i) => i.cycleIndex === maxCycle);
}

function detectMutationAndSelectTrainingSet(
  intervals: Interval[],
  keys: string[],
  weightOf: (i: Interval) => number,
): { training: Interval[]; mutationDetected: boolean } {
  const recent = mostRecentCycleIntervals(intervals);
  if (recent.length < MIN_RECENT_INTERVALS_FOR_MUTATION_CHECK || recent.length === intervals.length) {
    return { training: intervals, mutationDetected: false };
  }
  const fullCoef = fit(intervals.map((i) => intervalToRow(i, keys)), intervals.map((i) => i.deltaU), intervals.map(weightOf));
  const recentCoef = fit(recent.map((i) => intervalToRow(i, keys)), recent.map((i) => i.deltaU), recent.map(weightOf));
  let mutationDetected = false;
  for (let idx = 0; idx < keys.length; idx++) {
    const full = fullCoef[idx];
    const rec = recentCoef[idx];
    if (full <= MEANINGFUL_COEF_EPSILON || rec <= MEANINGFUL_COEF_EPSILON) continue;
    const ratio = rec / full;
    if (ratio > MUTATION_RATIO_THRESHOLD || ratio < 1 / MUTATION_RATIO_THRESHOLD) {
      mutationDetected = true;
      break;
    }
  }
  return { training: mutationDetected ? recent : intervals, mutationDetected };
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

  const windowedObservations = observations.filter((o) => Date.parse(o.observed_at) >= windowStartMs);
  const built = buildAllIntervals(provider, windowedObservations, facts);
  const intervals = built.intervals.filter((i) => Date.parse(i.t0) >= windowStartMs);

  const keys = KNOWN_FAMILIES[provider];
  const weightOf = (i: Interval) => recencyWeight(i, now, halfLifeDays);

  const fittedAt = now.toISOString();

  if (intervals.length === 0) {
    return {
      unattributedDroppedIntervals: built.droppedForUnattributed,
      results: keys.map((family) => ({
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

  const backtestMaxErr = leaveOneDayOutMaxError(samples, fit);

  const results: CalibrationResult[] = keys.map((family, idx) => {
    const coef = finalCoef[idx];
    let effectiveDeltaU = 0;
    for (const s of samples) effectiveDeltaU += coef * s.row[idx];
    return {
      provider,
      model_family: family,
      coef,
      effective_delta_u: effectiveDeltaU,
      backtest_max_err: backtestMaxErr,
      grade: grade(effectiveDeltaU, backtestMaxErr),
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
