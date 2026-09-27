/**
 * #183-a：区间构造。
 *
 * 把一个周期内的官方读数序列，压缩成一串「起点 → 终点，额度涨了多少，这段时间里各模型族
 * 花了多少价格加权 token」的区间，再喂给拟合器。
 *
 * 做法（#183 设计 v1 §1）：
 * - 同一周期内相邻读数用贪心方式合并，直到间隔 ≥ `MERGE_GAP_MS`（3 小时）——原始读数
 *   之间间隔太短时，官方额度的量化误差会主导 ΔU，噪音比信号大。
 * - 合并后如果结尾还剩一段够长（≥15 分钟）但不够 3 小时的尾巴，单独作为最后一个区间保留，
 *   否则周期末尾的真实用量会被直接丢弃。
 * - 起点 `used_percent ≥ SATURATION_PERCENT`（95）的区间整段剔除：饱和状态下额度不再随
 *   用量线性增长（可能触顶、限流），拿来拟合系数会把线性假设直接带偏。
 * - 小时事实按「区间与事实窗口的重叠时长 / 事实窗口总时长」分摊到区间上，而不是整段搬进去
 *   ——一条小时事实可能跨在两个区间边界上。
 */
import type { Provider } from "./constants";
import { priceWeightedTokens, UNATTRIBUTED_DROP_RATIO, UNATTRIBUTED_FAMILY } from "./constants";
import type { Cycle } from "./cycles";
import type { HourlyFamilyFact, Interval } from "./types";

const MERGE_GAP_MS = 3 * 60 * 60 * 1000;
const TAIL_MIN_GAP_MS = 15 * 60 * 1000;
export const SATURATION_PERCENT = 95;

export interface BuildIntervalsResult {
  intervals: Interval[];
  /** 因 unattributed 占比过高被整段剔除的区间数（数据完整性不够，不参与拟合与回测）。 */
  droppedForUnattributed: number;
}

interface Point {
  t: number;
  u: number;
}

function greedySubsample(points: Point[]): Point[] {
  if (points.length === 0) return [];
  const sel: Point[] = [points[0]];
  for (const p of points.slice(1)) {
    if (p.t - sel[sel.length - 1].t >= MERGE_GAP_MS) sel.push(p);
  }
  const last = points[points.length - 1];
  const selLast = sel[sel.length - 1];
  if (selLast.t !== last.t && last.t - selLast.t >= TAIL_MIN_GAP_MS) sel.push(last);
  return sel;
}

/** 构造某个 provider 下所有周期的区间，并把小时事实按重叠比例分摊上去。 */
export function buildIntervals(
  provider: Provider,
  sourceId: string,
  cycles: Cycle[],
  facts: HourlyFamilyFact[],
): BuildIntervalsResult {
  const relevantFacts = facts.filter((f) => f.provider === provider && f.model_family !== null);
  const intervals: Interval[] = [];
  let droppedForUnattributed = 0;

  for (const cycle of cycles) {
    const points: Point[] = cycle.readings.map((r) => ({ t: Date.parse(r.observed_at), u: r.used_percent }));
    const sel = greedySubsample(points);
    for (let i = 0; i < sel.length - 1; i++) {
      const p0 = sel[i];
      const p1 = sel[i + 1];
      if (p0.u >= SATURATION_PERCENT) continue; // 起点饱和，整段剔除
      const familyPricedTokens: Record<string, number> = {};
      for (const fact of relevantFacts) {
        const ws = Date.parse(fact.window_start);
        const we = Date.parse(fact.window_end);
        const factDurationMs = we - ws;
        if (factDurationMs <= 0) continue;
        const overlapMs = Math.min(we, p1.t) - Math.max(ws, p0.t);
        if (overlapMs <= 0) continue;
        const fraction = overlapMs / factDurationMs;
        const priced = priceWeightedTokens(provider, fact) * fraction;
        const family = fact.model_family as string;
        familyPricedTokens[family] = (familyPricedTokens[family] ?? 0) + priced;
      }
      // 数据完整性门禁：unattributed（缺 model 行的差额）占该区间加权 token 总量比例过高，
      // 说明这段时间的模型归因不可信，整段剔除，不静默保留（会系统性抬高已知族的系数）。
      const totalPriced = Object.values(familyPricedTokens).reduce((s, v) => s + v, 0);
      const unattributedPriced = familyPricedTokens[UNATTRIBUTED_FAMILY] ?? 0;
      if (totalPriced > 0 && unattributedPriced / totalPriced > UNATTRIBUTED_DROP_RATIO) {
        droppedForUnattributed += 1;
        continue;
      }
      intervals.push({
        sourceId,
        cycleIndex: cycle.index,
        t0: new Date(p0.t).toISOString(),
        t1: new Date(p1.t).toISOString(),
        u0: p0.u,
        u1: p1.u,
        deltaU: p1.u - p0.u,
        familyPricedTokens,
      });
    }
  }
  return { intervals, droppedForUnattributed };
}
