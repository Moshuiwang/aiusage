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

  it("reset_at 不变而 used_percent 下降是上游纠正：回溯丢弃被撤销的读数，不切周期", () => {
    // #206 真实序列（Codex 2026-09-30，同一 reset_at）：本地 0 token 时 22→43，数小时后纠正回 24。
    // 生产全部历史里 reset_at 不变的下降没有一次是真实重置（真实重置都会把 reset_at 推后一周）。
    const reset = "2026-10-03T16:58:00Z";
    const readings = [
      obs({ provider: "codex", observed_at: "2026-09-29T16:51:00Z", reset_at: reset, used_percent: 21 }),
      obs({ provider: "codex", observed_at: "2026-09-29T17:15:00Z", reset_at: reset, used_percent: 22 }),
      obs({ provider: "codex", observed_at: "2026-09-29T17:25:00Z", reset_at: reset, used_percent: 43 }),
      obs({ provider: "codex", observed_at: "2026-09-29T23:01:00Z", reset_at: reset, used_percent: 46 }),
      obs({ provider: "codex", observed_at: "2026-09-30T01:35:00Z", reset_at: reset, used_percent: 49 }),
      obs({ provider: "codex", observed_at: "2026-09-30T05:14:00Z", reset_at: reset, used_percent: 24 }),
      obs({ provider: "codex", observed_at: "2026-09-30T05:19:00Z", reset_at: reset, used_percent: 49 }), // 纠正期间的交错读数
      obs({ provider: "codex", observed_at: "2026-09-30T05:35:00Z", reset_at: reset, used_percent: 24 }),
      obs({ provider: "codex", observed_at: "2026-10-01T00:02:00Z", reset_at: reset, used_percent: 25 }),
    ];
    const cycles = splitCycles(readings);
    expect(cycles).toHaveLength(1);
    expect(cycles[0].readings.map((r) => r.used_percent)).toEqual([21, 22, 24, 24, 25]);
  });

  it("纠正只撤销高于纠正值的读数，纠正之前的正常增长保留", () => {
    const readings = [
      obs({ observed_at: "2026-09-01T00:00:00Z", used_percent: 10 }),
      obs({ observed_at: "2026-09-01T01:00:00Z", used_percent: 12 }),
      obs({ observed_at: "2026-09-01T02:00:00Z", used_percent: 15 }),
      obs({ observed_at: "2026-09-01T03:00:00Z", used_percent: 14 }),
    ];
    const cycles = splitCycles(readings);
    expect(cycles).toHaveLength(1);
    expect(cycles[0].readings.map((r) => r.used_percent)).toEqual([10, 12, 14]);
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

  it("【变异证据】把纠正当成新周期（旧实现）会让被撤销的 +21 留在训练区间里", () => {
    const reset = "2026-10-03T16:58:00Z";
    const readings = [
      obs({ provider: "codex", observed_at: "2026-09-29T17:15:00Z", reset_at: reset, used_percent: 22 }),
      obs({ provider: "codex", observed_at: "2026-09-29T17:25:00Z", reset_at: reset, used_percent: 43 }),
      obs({ provider: "codex", observed_at: "2026-09-30T05:14:00Z", reset_at: reset, used_percent: 24 }),
    ];
    // 旧实现：used 下降即切新周期，22→43 保留在第一个周期里。
    const splitOnDrop = (list: LimitObservation[]) => {
      const segs: LimitObservation[][] = [];
      let cur: LimitObservation[] = [];
      for (const r of list) {
        if (cur.length > 0 && r.used_percent < cur[cur.length - 1].used_percent - 0.01) {
          segs.push(cur);
          cur = [];
        }
        cur.push(r);
      }
      if (cur.length) segs.push(cur);
      return segs;
    };
    const broken = splitOnDrop(readings);
    expect(broken).toHaveLength(2);
    expect(broken[0].map((r) => r.used_percent)).toEqual([22, 43]);
    // 正确实现：一个周期，被撤销的 43 不再出现。
    const cycles = splitCycles(readings);
    expect(cycles).toHaveLength(1);
    expect(cycles[0].readings.map((r) => r.used_percent)).toEqual([22, 24]);
  });

  it("真实重置（reset_at 推后一周）即使 used 下降也仍然切出新周期", () => {
    const readings = [
      obs({ observed_at: "2026-09-01T00:00:00Z", reset_at: "2026-09-08T00:00:00Z", used_percent: 95 }),
      obs({ observed_at: "2026-09-08T01:00:00Z", reset_at: "2026-09-15T00:00:00Z", used_percent: 2 }),
    ];
    const cycles = splitCycles(readings);
    expect(cycles).toHaveLength(2);
    expect(cycles[0].readings.map((r) => r.used_percent)).toEqual([95]);
    expect(cycles[1].readings.map((r) => r.used_percent)).toEqual([2]);
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
