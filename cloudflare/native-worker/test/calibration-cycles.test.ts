/**
 * #183-a：周期切分与重置识别（合成数据，覆盖边界条件；真实数据的整体行为见
 * calibration-fixture.test.ts）。
 */
import { describe, expect, it } from "vitest";
import { splitCycles, withResetAnchors } from "../src/calibration/cycles";
import type { LimitObservation } from "../src/calibration/types";

function obs(overrides: Partial<LimitObservation>): LimitObservation {
  return {
    source_id: "s1",
    provider: "claude",
    observed_at: "2026-09-01T00:00:00Z",
    reset_at: "2026-09-08T00:00:00Z",
    used_percent: 0,
    window_duration_minutes: 10080,
    ...overrides,
  };
}

describe("splitCycles", () => {
  it("reset_at 变化超过 2 分钟时切出新周期", () => {
    const readings = [
      obs({ observed_at: "2026-09-01T00:00:00Z", reset_at: "2026-09-08T00:00:00Z", used_percent: 90 }),
      obs({ observed_at: "2026-09-08T01:00:00Z", reset_at: "2026-09-15T00:00:00Z", used_percent: 5 }),
    ];
    const cycles = splitCycles(readings);
    expect(cycles).toHaveLength(2);
    expect(cycles[0].readings).toHaveLength(1);
    expect(cycles[1].readings).toHaveLength(1);
  });

  it("used_percent 下降时切出新周期（即使 reset_at 没变超过阈值）", () => {
    const readings = [
      obs({ observed_at: "2026-09-01T00:00:00Z", reset_at: "2026-09-08T00:00:00Z", used_percent: 90 }),
      obs({ observed_at: "2026-09-01T01:00:00Z", reset_at: "2026-09-08T00:00:00Z", used_percent: 3 }),
    ];
    const cycles = splitCycles(readings);
    expect(cycles).toHaveLength(2);
  });

  it("reset_at 漂移在 2 分钟以内、used_percent 不下降时不切周期", () => {
    const readings = [
      obs({ observed_at: "2026-09-01T00:00:00Z", reset_at: "2026-09-08T00:00:00.000Z", used_percent: 10 }),
      obs({ observed_at: "2026-09-01T01:00:00Z", reset_at: "2026-09-08T00:01:30.000Z", used_percent: 12 }),
    ];
    const cycles = splitCycles(readings);
    expect(cycles).toHaveLength(1);
    expect(cycles[0].readings).toHaveLength(2);
  });

  it("used_percent 全程为 0 且读数条数 ≤8 时整段丢弃（reset_at 滚动噪音，不是真实重置）", () => {
    const readings: LimitObservation[] = [];
    for (let i = 0; i < 5; i++) {
      readings.push(
        obs({
          observed_at: `2026-09-01T0${i}:00:00Z`,
          reset_at: `2026-09-01T0${i}:30:00Z`, // 每条都漂移 >2 分钟，但 used 全是 0
          used_percent: 0,
        }),
      );
    }
    expect(splitCycles(readings)).toHaveLength(0);
  });

  it("used_percent 全程为 0 但读数条数 >8 时保留为一个真实周期（不是噪音，是真的没在用）", () => {
    const readings: LimitObservation[] = [];
    for (let i = 0; i < 9; i++) {
      readings.push(
        obs({
          observed_at: `2026-09-01T${String(i).padStart(2, "0")}:00:00Z`,
          reset_at: "2026-09-08T00:00:00Z",
          used_percent: 0,
        }),
      );
    }
    expect(splitCycles(readings)).toHaveLength(1);
    expect(splitCycles(readings)[0].readings).toHaveLength(9);
  });

  it("【变异证据】去掉 used_percent 下降判据后，会把一次真实重置误判成同一个周期", () => {
    // 模拟「不切重置」的错误实现：只看 reset_at 漂移，不看 used_percent 下降。
    const readings = [
      obs({ observed_at: "2026-09-01T00:00:00Z", reset_at: "2026-09-08T00:00:00Z", used_percent: 95 }),
      obs({ observed_at: "2026-09-01T01:00:00Z", reset_at: "2026-09-08T00:00:00Z", used_percent: 2 }), // 真实重置，但 reset_at 没变
    ];
    const brokenSplit = (obsList: LimitObservation[]) => {
      // 故意只用 reset_at 漂移判据，复刻「不切 used_percent 下降」这个 bug。
      const segs: LimitObservation[][] = [];
      let cur: LimitObservation[] = [];
      for (const r of obsList) {
        if (cur.length > 0 && Math.abs(Date.parse(r.reset_at) - Date.parse(cur[cur.length - 1].reset_at)) > 120000) {
          segs.push(cur);
          cur = [];
        }
        cur.push(r);
      }
      if (cur.length) segs.push(cur);
      return segs;
    };
    // 正确实现：2 个周期。
    expect(splitCycles(readings)).toHaveLength(2);
    // 「不切 used_percent 下降」的错误实现：只有 1 个（错误地把两次重置状态合并）。
    expect(brokenSplit(readings)).toHaveLength(1);
  });
});

describe("withResetAnchors", () => {
  it("给新周期在 reset_at − window 处补一个 used=0 的锚点", () => {
    const cycle0 = [obs({ observed_at: "2026-09-01T00:00:00Z", reset_at: "2026-09-08T00:00:00Z", used_percent: 95 })];
    const cycle1 = [
      obs({ observed_at: "2026-09-08T02:00:00Z", reset_at: "2026-09-15T00:00:00Z", used_percent: 5 }),
    ];
    const cycles = [
      { index: 0, readings: cycle0 },
      { index: 1, readings: cycle1 },
    ];
    const anchored = withResetAnchors(cycles);
    expect(anchored[0].readings).toHaveLength(1); // 第一个周期不补锚点
    expect(anchored[1].readings).toHaveLength(2);
    expect(anchored[1].readings[0].used_percent).toBe(0);
    // reset_at(9/15) - window(7天) = 9/8T00:00，早于第一条真实读数(9/8T02:00)。
    expect(anchored[1].readings[0].observed_at).toBe("2026-09-08T00:00:00.000Z");
  });

  it("锚点时间早于上一周期结尾太多（gap ≥30 小时）时不补锚点", () => {
    const cycle0 = [obs({ observed_at: "2026-09-01T00:00:00Z", reset_at: "2026-09-08T00:00:00Z", used_percent: 95 })];
    const cycle1 = [
      // 第二个周期第一条读数离上一周期结尾很久之后才出现，锚点会落在两周期之间的空档里。
      obs({ observed_at: "2026-09-20T00:00:00Z", reset_at: "2026-09-22T00:00:00Z", used_percent: 5 }),
    ];
    const cycles = [
      { index: 0, readings: cycle0 },
      { index: 1, readings: cycle1 },
    ];
    const anchored = withResetAnchors(cycles);
    expect(anchored[1].readings).toHaveLength(1); // 没有补锚点
  });
});
