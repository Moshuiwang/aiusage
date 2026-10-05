/**
 * #183-a：逐日留出回测与精度分级。
 *
 * 「累计 ΔU 够大」不代表「预测准」——一个族可能样本很多但系数完全拟合错了方向。
 * 所以分级看两个独立的数：
 * - `effectiveDeltaU`：这个族在训练区间里累计贡献了多少 ΔU（`coef × 价格加权token` 求和），
 *   衡量「有没有见过足够多这个族的真实用量变化」。
 * - `backtestMaxErr`：逐日留出（每次拿掉一天的区间当测试集，用剩下的重新拟合）算出的
 *   累计误差里最大的那个，衡量「拟合出来的系数外推到没见过的那天有多准」。
 *
 * 回测误差是账户级的（同一账户下所有族共用同一份系数联合预测当天 ΔU 之和），因为原始官方
 * 读数本身就是账户整体的额度百分比，没有「这一分钟是哪个族涨的」的真值可供拆分验证。
 * 分级门槛按族分别应用在 effectiveDeltaU 上，但 backtestMaxErr 对同一账户下所有族相同。
 *
 * ## 性能：Sample 预计算一次，逐日留出只重做 NNLS
 *
 * 早期实现在每一天的留出循环里都重新对 `Interval[]` 做 `t0.slice(0,10)`、重新跑一遍
 * `intervalToRow`（特征向量）、重新调用 `weightOf`（内含 `Date.parse`）——这些值在不同的
 * 留出折里根本不会变，等于把「构造样本」的成本乘了「天数」倍。`toSamples()` 把这些只算
 * 一次，`leaveOneDayOutMaxError` 只在每天的循环体里做真正必须重做的事：按 `dayKey` 过滤、
 * 重新调 `fit()`（NNLS）。
 */
import { predictRow } from "./nnls";
import type { Grade, Interval } from "./types";

const MIN_DAILY_ACTUAL_DELTA_U = 3;
/**
 * Claude / Codex 官方 used_percent 是整数，小涨幅计分日自带 ±1 点取整误差（3 点日即 ±33%）。
 * 产品负责人 2026-10-06 决定（#206）对所有 provider 统一适用（Antigravity 读数是小数，没有取整
 * 误差这个理由，统一适用属于产品决定）：某天「相对误差 ≤ 门槛」或「绝对误差 ≤ 1 个点」即合格——
 * 绝对误差在这个范围内的天记 0，其余天照常按相对误差计入最大值，大涨幅日不享受宽限。
 */
const QUANTIZATION_TOLERANCE_POINTS = 1;

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
 * 逐日留出回测：对每一天，用其余所有天的样本重新拟合，预测这一天各区间 ΔU 之和，
 * 跟这一天区间的实际 ΔU 之和比较相对误差（绝对误差 ≤1 个点的天记 0，见上）。返回所有天里绝对值最大的相对误差；
 * 没有任何一天满足最小 ΔU 门槛（数据太稀疏）时返回 null（意味着无法给出回测证据）。
 */
export function leaveOneDayOutMaxError(
  samples: Sample[],
  fit: (rows: number[][], targets: number[], weights: number[]) => number[],
): number | null {
  const byDay = new Map<string, Sample[]>();
  for (const s of samples) {
    const list = byDay.get(s.dayKey);
    if (list) list.push(s);
    else byDay.set(s.dayKey, [s]);
  }
  const days = [...byDay.keys()].sort();
  let maxErr: number | null = null;
  for (const day of days) {
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
    const relErr =
      Math.abs(predictedSum - actualSum) <= QUANTIZATION_TOLERANCE_POINTS ? 0 : (predictedSum - actualSum) / actualSum;
    if (maxErr === null || Math.abs(relErr) > Math.abs(maxErr)) maxErr = relErr;
  }
  return maxErr;
}

export function grade(effectiveDeltaU: number, backtestMaxErr: number | null): Grade {
  if (backtestMaxErr === null) return "none";
  const err = Math.abs(backtestMaxErr);
  if (effectiveDeltaU >= 10 && err <= 0.1) return "A";
  if (effectiveDeltaU >= 4 && err <= 0.25) return "B";
  return "none";
}
