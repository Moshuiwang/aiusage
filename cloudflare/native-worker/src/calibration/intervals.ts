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
 *
 * ## 性能：双指针扫描，不是 intervals × facts 全量双循环
 *
 * 早期实现对每个区间都重新遍历一次全部 facts（还在循环体里反复 `Date.parse` 同一批
 * facts 的 window_start/window_end），CPU 门禁测出耗时随天数近似平方增长：mult=1(~10天)
 * 4.2ms → mult=2(~20天) 13.2ms → mult=3(~28天) 27.2ms，远超 Cloudflare Free 单次调用 10ms
 * 预算（见 #183 收口报告）。
 *
 * 修的方式：facts 按 `window_start` 排序一次、时间戳预解析一次；候选区间本身也已经是按
 * `t0` 升序（cycles 按时间顺序、每个 cycle 内部合并后的点也升序）。于是只需要一次线性
 * 双指针扫描——`lo` 单调右移跳过「结束时间已经早于当前区间起点」的 facts，`idx` 从 `lo`
 * 往后扫到「起点已经晚于当前区间终点」为止（fact 窗口固定 1 小时，远小于区间的 3 小时
 * 合并门槛，所以每个区间实际扫到的 fact 数是常数量级，不随总量增长）。整体复杂度从
 * O(intervals × facts) 降到 O(intervals + facts)（外加一次 O(facts log facts) 排序）。
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

interface Candidate {
  t0Ms: number;
  t1Ms: number;
  u0: number;
  u1: number;
  cycleIndex: number;
}

interface TimedFact {
  fact: HourlyFamilyFact;
  wsMs: number;
  weMs: number;
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

/** 第一阶段：只算「起点/终点/ΔU」，不摸事实——候选区间按 t0 升序（cycles 本身就是时间顺序）。 */
function buildCandidates(cycles: Cycle[]): Candidate[] {
  const candidates: Candidate[] = [];
  for (const cycle of cycles) {
    const points: Point[] = cycle.readings.map((r) => ({ t: Date.parse(r.observed_at), u: r.used_percent }));
    const sel = greedySubsample(points);
    for (let i = 0; i < sel.length - 1; i++) {
      const p0 = sel[i];
      const p1 = sel[i + 1];
      if (p0.u >= SATURATION_PERCENT) continue; // 起点饱和，整段剔除
      candidates.push({ t0Ms: p0.t, t1Ms: p1.t, u0: p0.u, u1: p1.u, cycleIndex: cycle.index });
    }
  }
  return candidates;
}

/** 构造某个 provider 下所有周期的区间，并把小时事实按重叠比例分摊上去。 */
export function buildIntervals(
  provider: Provider,
  sourceId: string,
  cycles: Cycle[],
  facts: HourlyFamilyFact[],
): BuildIntervalsResult {
  const relevantFacts: TimedFact[] = facts
    .filter((f) => f.provider === provider && f.model_family !== null)
    .map((f) => ({ fact: f, wsMs: Date.parse(f.window_start), weMs: Date.parse(f.window_end) }))
    .sort((a, b) => a.wsMs - b.wsMs);

  const candidates = buildCandidates(cycles);

  const intervals: Interval[] = [];
  let droppedForUnattributed = 0;
  let lo = 0; // 单调右移：facts[lo] 是「可能仍与某个后续区间重叠」的最早一条

  for (const c of candidates) {
    while (lo < relevantFacts.length && relevantFacts[lo].weMs <= c.t0Ms) lo++;

    const familyPricedTokens: Record<string, number> = {};
    let idx = lo;
    while (idx < relevantFacts.length && relevantFacts[idx].wsMs < c.t1Ms) {
      const { fact, wsMs, weMs } = relevantFacts[idx];
      const overlapMs = Math.min(weMs, c.t1Ms) - Math.max(wsMs, c.t0Ms);
      if (overlapMs > 0) {
        const fraction = overlapMs / (weMs - wsMs);
        const priced = priceWeightedTokens(provider, fact) * fraction;
        const family = fact.model_family as string;
        familyPricedTokens[family] = (familyPricedTokens[family] ?? 0) + priced;
      }
      idx++;
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
      cycleIndex: c.cycleIndex,
      t0: new Date(c.t0Ms).toISOString(),
      t1: new Date(c.t1Ms).toISOString(),
      u0: c.u0,
      u1: c.u1,
      deltaU: c.u1 - c.u0,
      familyPricedTokens,
    });
  }
  return { intervals, droppedForUnattributed };
}
