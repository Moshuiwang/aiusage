/**
 * #183-a：逐日留出回测与精度分级。
 *
 * 「累计 ΔU 够大」不代表「预测准」——一个族可能样本很多但系数完全拟合错了方向。
 * 所以分级看两个独立的数：
 * - `effectiveDeltaU`：这个族在训练区间里累计贡献了多少 ΔU（`coef × 价格加权token` 求和），
 *   衡量「有没有见过足够多这个族的真实用量变化」。
 * - `backtestDeviation`：逐日留出（每次拿掉一天的区间当测试集，用剩下的重新拟合）算出的
 *   多天总偏差（#271 v2；v1 是单日最大误差），衡量「拟合出来的系数外推到没见过的那天有多准」。
 *
 * 回测误差是账户级的（同一账户下所有族共用同一份系数联合预测当天 ΔU 之和），因为原始官方
 * 读数本身就是账户整体的额度百分比，没有「这一分钟是哪个族涨的」的真值可供拆分验证。
 * effectiveDeltaU 门槛：无价比的族看自身；有价比的族（#271 共用一个系数）看整组之和，
 * 自身不足 A 档门槛时最多 B（见 index.ts）。backtestDeviation 对同一账户下所有族相同。
 *
 * ## 性能：Sample 预计算一次，逐日留出只重做 NNLS
 *
 * 早期实现在每一天的留出循环里都重新对 `Interval[]` 做 `t0.slice(0,10)`、重新跑一遍
 * `intervalToRow`（特征向量）、重新调用 `weightOf`（内含 `Date.parse`）——这些值在不同的
 * 留出折里根本不会变，等于把「构造样本」的成本乘了「天数」倍。`toSamples()` 把这些只算
 * 一次，`leaveOneDayOutDeviation` 只在每天的循环体里做真正必须重做的事：按 `dayKey` 过滤、
 * 重新调 `fit()`（NNLS）。
 */
import { predictRow } from "./nnls";
import type { Grade, Interval } from "./types";

const MIN_DAILY_ACTUAL_DELTA_U = 3;
/**
 * Claude / Codex 官方 used_percent 是整数，小涨幅计分日自带 ±1 点取整误差（3 点日即 ±33%）。
 * 产品负责人 2026-10-06 决定（#206）对所有 provider 统一适用（Antigravity 读数是小数，没有取整
 * 误差这个理由，统一适用属于产品决定）：绝对误差 ≤ 1 个点的天记 0，其余天按实际误差点数计入
 * （#271 起计入总偏差的分子），大涨幅日不享受宽限。
 */
const QUANTIZATION_TOLERANCE_POINTS = 1;
/** 总偏差至少要有这么多个计分日才算回测证据（#271）。 */
const MIN_SCORED_DAYS = 3;

/** 一个区间预计算出的、逐日留出回测只需要的最小数据——不再持有整条 Interval。 */
export interface Sample {
  dayKey: string;
  row: number[];
  weight: number;
  deltaU: number;
}

export function intervalToRow(interval: Interval, keys: string[]): number[] {
  return keys.map((k) => interval.familyPricedTokens[k] ?? 0);
}

/** 把区间数组转换成回测/拟合都能直接复用的 Sample 数组，每个区间只算一次。 */
export function toSamples(intervals: Interval[], keys: string[], weightOf: (interval: Interval) => number): Sample[] {
  return intervals.map((interval) => ({
    dayKey: interval.t0.slice(0, 10),
    row: intervalToRow(interval, keys),
    weight: weightOf(interval),
    deltaU: interval.deltaU,
  }));
}

/**
 * 逐日留出回测（#271 v2 口径）：对每一天，用其余所有天的样本重新拟合，预测这一天各区间 ΔU 之和。
 * 返回所有计分日的总偏差 Σ|预测−实际| / Σ实际——v1 取单日最大相对误差，会被个别小涨幅
 * 异常日主导（生产 Claude 一天实际 10 点、预测 14–19 点就让任何公式都过不了门槛），产品负责人
 * 2026-10-07 决定改看多天总偏差。绝对误差 ≤1 个点的天按取整误差记 0（实际值仍计入分母）。
 * 计分日不足 `MIN_SCORED_DAYS` 时返回 null（意味着无法给出回测证据）。
 *
 * 写入 `quota_calibration.backtest_max_err`（列名沿用 v1，v2 起含义是这个总偏差，非负）；
 * 读侧只用它判定「回测未通过 / 数据不足」，不再下发给客户端。
 */
export function leaveOneDayOutDeviation(
  samples: Sample[],
  fit: (rows: number[][], targets: number[], weights: number[]) => number[],
): number | null {
  const byDay = new Map<string, Sample[]>();
  for (const s of samples) {
    const list = byDay.get(s.dayKey);
    if (list) list.push(s);
    else byDay.set(s.dayKey, [s]);
  }
  let scoredDays = 0;
  let actualTotal = 0;
  let errorTotal = 0;
  for (const day of [...byDay.keys()].sort()) {
    const test = byDay.get(day)!;
    const train = samples.filter((s) => s.dayKey !== day);
    const actualSum = test.reduce((s, x) => s + x.deltaU, 0);
    if (actualSum < MIN_DAILY_ACTUAL_DELTA_U || train.length === 0) continue;
    const coef = fit(
      train.map((s) => s.row),
      train.map((s) => s.deltaU),
      train.map((s) => s.weight),
    );
    const predictedSum = test.reduce((s, x) => s + predictRow(x.row, coef), 0);
    const absErr = Math.abs(predictedSum - actualSum);
    scoredDays += 1;
    actualTotal += actualSum;
    errorTotal += absErr <= QUANTIZATION_TOLERANCE_POINTS ? 0 : absErr;
  }
  if (scoredDays < MIN_SCORED_DAYS) return null;
  return errorTotal / actualTotal;
}

/** A 档总偏差上限。 */
export const A_MAX_DEVIATION = 0.1;
/** B 档总偏差上限；读侧据此区分「回测未通过」与「数据不足」。 */
export const B_MAX_DEVIATION = 0.2;

export function grade(effectiveDeltaU: number, backtestDeviation: number | null): Grade {
  if (backtestDeviation === null) return "none";
  const err = Math.abs(backtestDeviation);
  if (effectiveDeltaU >= 10 && err <= A_MAX_DEVIATION) return "A";
  if (effectiveDeltaU >= 4 && err <= B_MAX_DEVIATION) return "B";
  return "none";
}
