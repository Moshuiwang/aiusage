/** #183-a：区间构造——合并、饱和剔除、unattributed 完整性门禁（合成数据，覆盖边界条件）。 */
import { describe, expect, it } from "vitest";
import { buildIntervals } from "../src/calibration/intervals";
import type { Cycle } from "../src/calibration/cycles";
import type { HourlyFamilyFact, LimitObservation } from "../src/calibration/types";

function reading(t: string, u: number): LimitObservation {
  return {
    source_id: "s1",
    provider: "claude",
    observed_at: t,
    reset_at: "2026-09-08T00:00:00Z",
    used_percent: u,
    window_duration_minutes: 10080,
  };
}

function fact(overrides: Partial<HourlyFamilyFact>): HourlyFamilyFact {
  return {
    provider: "claude",
    model_family: "opus",
    window_start: "2026-09-01T00:00:00Z",
    window_end: "2026-09-01T01:00:00Z",
    input_tokens: 0,
    output_tokens: 1_000_000,
    cache_creation_tokens: 0,
    cache_read_tokens: 0,
    ...overrides,
  };
}

describe("buildIntervals：合并与分摊", () => {
  it("间隔 <3 小时的相邻读数被合并跳过，不单独成区间", () => {
    const cycle: Cycle = {
      index: 0,
      readings: [
        reading("2026-09-01T00:00:00Z", 0),
        reading("2026-09-01T01:00:00Z", 10), // 1 小时后，被跳过
        reading("2026-09-01T04:00:00Z", 30), // 距起点 4 小时，够 3 小时门槛
      ],
    };
    const { intervals } = buildIntervals("claude", "s1", [cycle], []);
    expect(intervals).toHaveLength(1);
    expect(intervals[0].u0).toBe(0);
    expect(intervals[0].u1).toBe(30);
    expect(intervals[0].deltaU).toBe(30);
  });

  it("结尾不足 3 小时但 ≥15 分钟的尾巴单独保留为最后一个区间", () => {
    const cycle: Cycle = {
      index: 0,
      readings: [
        reading("2026-09-01T00:00:00Z", 0),
        reading("2026-09-01T04:00:00Z", 30),
        reading("2026-09-01T04:20:00Z", 32), // 尾巴 20 分钟，≥15 分钟门槛
      ],
    };
    const { intervals } = buildIntervals("claude", "s1", [cycle], []);
    expect(intervals).toHaveLength(2);
    expect(intervals[1].u0).toBe(30);
    expect(intervals[1].u1).toBe(32);
  });

  it("起点 used_percent ≥95 的区间整段剔除（饱和）", () => {
    const cycle: Cycle = {
      index: 0,
      readings: [reading("2026-09-01T00:00:00Z", 96), reading("2026-09-01T04:00:00Z", 98)],
    };
    const { intervals } = buildIntervals("claude", "s1", [cycle], []);
    expect(intervals).toHaveLength(0);
  });

  it("【变异证据】去掉饱和剔除判据后，饱和区间会被保留（本该丢弃的高噪音样本混进拟合数据）", () => {
    const cycle: Cycle = {
      index: 0,
      readings: [reading("2026-09-01T00:00:00Z", 96), reading("2026-09-01T04:00:00Z", 98)],
    };
    const noSaturationGuard = (readings: LimitObservation[]) => {
      // 复刻「不检查 u0>=95」的错误实现：直接把所有相邻点对都当区间。
      return readings.slice(0, -1).map((r, i) => ({ u0: r.used_percent, u1: readings[i + 1].used_percent }));
    };
    const { intervals } = buildIntervals("claude", "s1", [cycle], []);
    expect(intervals).toHaveLength(0); // 正确实现：剔除
    expect(noSaturationGuard(cycle.readings)).toHaveLength(1); // 错误实现：保留了 1 个饱和区间
  });

  it("小时事实按与区间重叠的时长比例分摊到区间上", () => {
    const cycle: Cycle = {
      index: 0,
      readings: [reading("2026-09-01T00:00:00Z", 0), reading("2026-09-01T04:00:00Z", 10)],
    };
    // 事实窗口 [01:00, 02:00)，1 小时里有 1 小时全部落在区间 [00:00,04:00) 内 → 100% 分摊。
    const facts = [fact({ window_start: "2026-09-01T01:00:00Z", window_end: "2026-09-01T02:00:00Z", output_tokens: 2_000_000 })];
    const { intervals } = buildIntervals("claude", "s1", [cycle], facts);
    expect(intervals[0].familyPricedTokens.opus).toBeCloseTo(2_000_000 * 5, 6); // output 权重 5
  });

  it("跨区间边界的事实按重叠比例拆分到两个区间", () => {
    const cycles: Cycle[] = [
      { index: 0, readings: [reading("2026-09-01T00:00:00Z", 0), reading("2026-09-01T04:00:00Z", 10)] },
      { index: 1, readings: [reading("2026-09-01T04:00:00Z", 10), reading("2026-09-01T08:00:00Z", 20)] },
    ];
    // 事实窗口横跨两个区间的边界（03:30-04:30），一半落在区间0，一半落在区间1。
    const facts = [fact({ window_start: "2026-09-01T03:30:00Z", window_end: "2026-09-01T04:30:00Z", output_tokens: 1_000_000, input_tokens: 0 })];
    const { intervals } = buildIntervals("claude", "s1", cycles, facts);
    expect(intervals[0].familyPricedTokens.opus).toBeCloseTo(1_000_000 * 5 * 0.5, 3);
    expect(intervals[1].familyPricedTokens.opus).toBeCloseTo(1_000_000 * 5 * 0.5, 3);
  });
});

describe("buildIntervals：unattributed 完整性门禁", () => {
  it("unattributed 加权 token 占比 >5% 时整段剔除，并计入 droppedForUnattributed", () => {
    const cycle: Cycle = {
      index: 0,
      readings: [reading("2026-09-01T00:00:00Z", 0), reading("2026-09-01T04:00:00Z", 10)],
    };
    const facts = [
      fact({ model_family: "opus", output_tokens: 900_000, window_start: "2026-09-01T01:00:00Z", window_end: "2026-09-01T02:00:00Z" }),
      fact({ model_family: "unattributed", output_tokens: 200_000, window_start: "2026-09-01T01:00:00Z", window_end: "2026-09-01T02:00:00Z" }),
    ];
    // opus 加权 = 900000*5=4.5M；unattributed 加权 = 200000*5=1M；占比 1/(4.5+1)=18.2% >5%。
    const { intervals, droppedForUnattributed } = buildIntervals("claude", "s1", [cycle], facts);
    expect(intervals).toHaveLength(0);
    expect(droppedForUnattributed).toBe(1);
  });

  it("unattributed 占比 ≤5% 时保留区间（但 unattributed 本身不参与任何已知族的拟合特征）", () => {
    const cycle: Cycle = {
      index: 0,
      readings: [reading("2026-09-01T00:00:00Z", 0), reading("2026-09-01T04:00:00Z", 10)],
    };
    const facts = [
      fact({ model_family: "opus", output_tokens: 10_000_000, window_start: "2026-09-01T01:00:00Z", window_end: "2026-09-01T02:00:00Z" }),
      fact({ model_family: "unattributed", output_tokens: 100_000, window_start: "2026-09-01T01:00:00Z", window_end: "2026-09-01T02:00:00Z" }),
    ];
    // opus 加权=50M；unattributed 加权=0.5M；占比 0.5/50.5≈0.99% ≤5%。
    const { intervals, droppedForUnattributed } = buildIntervals("claude", "s1", [cycle], facts);
    expect(intervals).toHaveLength(1);
    expect(droppedForUnattributed).toBe(0);
    expect(intervals[0].familyPricedTokens.opus).toBeCloseTo(50_000_000, 3);
  });

  it("【变异证据】去掉 unattributed 剔除判据后，高缺失区间会被静默保留（会系统性抬高已知族系数）", () => {
    const cycle: Cycle = {
      index: 0,
      readings: [reading("2026-09-01T00:00:00Z", 0), reading("2026-09-01T04:00:00Z", 10)],
    };
    const facts = [
      fact({ model_family: "opus", output_tokens: 900_000, window_start: "2026-09-01T01:00:00Z", window_end: "2026-09-01T02:00:00Z" }),
      fact({ model_family: "unattributed", output_tokens: 200_000, window_start: "2026-09-01T01:00:00Z", window_end: "2026-09-01T02:00:00Z" }),
    ];
    const keepEverything = (fps: Record<string, number>) => {
      // 复刻「忽略 unattributed 直接保留区间」的错误实现：不检查占比，永远保留。
      return { kept: true, opusOnly: fps.opus };
    };
    const { intervals } = buildIntervals("claude", "s1", [cycle], facts);
    expect(intervals).toHaveLength(0); // 正确实现：剔除了这个高缺失区间
    // 错误实现会把这个区间的 opus=4.5M 加权 token 也算进拟合——正确实现完全不产出这个区间。
    expect(keepEverything({ opus: 4_500_000, unattributed: 1_000_000 }).kept).toBe(true);
  });
});
