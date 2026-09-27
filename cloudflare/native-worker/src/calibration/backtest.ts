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
 */
import { predictRow } from "./nnls";
import type { Grade, Interval } from "./types";

const MIN_DAILY_ACTUAL_DELTA_U = 3;

/** 把区间按 `t0` 的日期（UTC）分组，返回排序后的日期键与对应区间。 */
function groupByDay(intervals: Interval[]): Map<string, Interval[]> {
  const groups = new Map<string, Interval[]>();
  for (const interval of intervals) {
    const day = interval.t0.slice(0, 10);
    const list = groups.get(day) ?? [];
    list.push(interval);
    groups.set(day, list);
  }
  return groups;
}

export function intervalToRow(interval: Interval, keys: string[]): number[] {
  return keys.map((k) => interval.familyPricedTokens[k] ?? 0);
}

/**
 * 逐日留出回测：对每一天，用其余所有天的区间重新拟合，预测这一天各区间 ΔU 之和，
 * 跟这一天区间的实际 ΔU 之和比较相对误差。返回所有天里绝对值最大的相对误差；
 * 没有任何一天满足最小 ΔU 门槛（数据太稀疏）时返回 null（意味着无法给出回测证据）。
 */
export function leaveOneDayOutMaxError(
  intervals: Interval[],
  keys: string[],
  fit: (rows: number[][], targets: number[], weights: number[]) => number[],
  weightOf: (interval: Interval) => number,
): number | null {
  const byDay = groupByDay(intervals);
  const days = [...byDay.keys()].sort();
  let maxErr: number | null = null;
  for (const day of days) {
    const test = byDay.get(day)!;
    const train = intervals.filter((i) => i.t0.slice(0, 10) !== day);
    const actualSum = test.reduce((s, i) => s + i.deltaU, 0);
    if (actualSum < MIN_DAILY_ACTUAL_DELTA_U || train.length === 0) continue;
    const coef = fit(
      train.map((i) => intervalToRow(i, keys)),
      train.map((i) => i.deltaU),
      train.map(weightOf),
    );
    const predictedSum = test.reduce((s, i) => s + predictRow(intervalToRow(i, keys), coef), 0);
    const relErr = (predictedSum - actualSum) / actualSum;
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
