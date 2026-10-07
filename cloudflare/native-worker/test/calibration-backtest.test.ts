/** #183-a / #271：精度分级门槛（grade）与逐日留出回测的基本行为。 */
import { describe, expect, it } from "vitest";
import { B_MAX_DEVIATION, grade, leaveOneDayOutDeviation, toSamples } from "../src/calibration/backtest";
import { nonNegativeLeastSquares } from "../src/calibration/nnls";
import type { Interval } from "../src/calibration/types";

describe("grade", () => {
  // #271：门槛从「逐日留出单日最大误差」改为「逐日留出多天总偏差」（产品负责人 2026-10-07 决定）。
  it("effectiveDeltaU ≥10 且总偏差 ≤10% → A", () => {
    expect(grade(10, 0.1)).toBe("A");
    expect(grade(50, 0)).toBe("A");
  });

  it("effectiveDeltaU ≥4 且总偏差 ≤20% → B（不满足 A 的门槛时降级，不是直接 A）", () => {
    expect(grade(4, 0.2)).toBe("B");
    expect(grade(10, 0.15)).toBe("B"); // effU 够 A，但偏差超过 10%，只能是 B
    expect(B_MAX_DEVIATION).toBe(0.2);
  });

  it("effectiveDeltaU 或偏差任一不达标 → none", () => {
    expect(grade(3.9, 0.05)).toBe("none"); // effU 不够
    expect(grade(4, 0.21)).toBe("none"); // 偏差超过 B 门槛
    expect(grade(4, 0.25)).toBe("none"); // v1 的 B 上限 25% 在 v2 不再达标
    expect(grade(0, 0)).toBe("none");
  });

  it("回测偏差为 null（计分天数不足）时永远 none，不管 effectiveDeltaU 多大", () => {
    expect(grade(1000, null)).toBe("none");
  });

  it("【变异证据】未见族（effectiveDeltaU=0）如果不经过门槛检查直接判 A/B，会把没见过的族错误定级", () => {
    const brokenGrade = (effU: number, err: number | null) => (err !== null && Math.abs(err) <= 0.2 ? "B" : "none");
    expect(grade(0, 0.1)).toBe("none"); // 正确实现：effU=0 不达标，none
    expect(brokenGrade(0, 0.1)).toBe("B"); // 错误实现：忘记检查 effectiveDeltaU 门槛，直接判 B
  });
});

function iv(t0: string, deltaU: number, feature: number): Interval {
  return {
    sourceId: "s",
    cycleIndex: 0,
    t0,
    t1: t0,
    u0: 0,
    u1: deltaU,
    deltaU,
    familyPricedTokens: { a: feature },
  };
}

describe("leaveOneDayOutDeviation", () => {
  const fit = (rows: number[][], targets: number[], weights: number[]) => nonNegativeLeastSquares(rows, targets, weights);
  const w = () => 1;
  const samplesOf = (intervals: Interval[]) => toSamples(intervals, ["a"], w);
  // 固定系数 2 的桩：预测值精确可控（预测 = 2 × feature），不依赖 NNLS 数值偏差。
  const fixedFit = () => [2];
  const perfect = [
    iv("2026-09-01T00:00:00Z", 20, 10),
    iv("2026-09-02T00:00:00Z", 40, 20),
    iv("2026-09-03T00:00:00Z", 60, 30),
  ];

  it("完美线性数据（y=2x，跨多天）留出总偏差应接近 0", () => {
    const err = leaveOneDayOutDeviation(samplesOf([...perfect, iv("2026-09-04T00:00:00Z", 80, 40)]), fit);
    expect(err).not.toBeNull();
    expect(err as number).toBeLessThan(0.05);
  });

  it("单个小涨幅异常日不再主导结论：总偏差 = Σ|预测−实际| / Σ实际（独立手算）", () => {
    // 9 天完美（实际 20 = 2×10），1 天实际 10、预测 14：单日相对误差 40%，v1 会直接判不达标。
    const days = Array.from({ length: 9 }, (_, d) => iv(`2026-09-${String(d + 1).padStart(2, "0")}T00:00:00Z`, 20, 10));
    const bad = iv("2026-09-10T00:00:00Z", 10, 7);
    const err = leaveOneDayOutDeviation(samplesOf([...days, bad]), fixedFit);
    expect(err).toBeCloseTo(4 / (9 * 20 + 10), 9);
  });

  it("绝对误差 ≤1 个点的天按取整误差记 0，但实际值仍计入分母（实际 3、预测 4）", () => {
    const err = leaveOneDayOutDeviation(samplesOf([...perfect, iv("2026-09-04T00:00:00Z", 3, 2)]), fixedFit);
    expect(err).toBe(0);
  });

  it("超过 1 个点的误差按实际点数计入（实际 20、预测 14 → 6 / 140）", () => {
    const err = leaveOneDayOutDeviation(samplesOf([...perfect, iv("2026-09-04T00:00:00Z", 20, 7)]), fixedFit);
    expect(err).toBeCloseTo(6 / 140, 9);
  });

  it("当天实际 ΔU 之和小于最小门槛（3）的天不计分，不进分子也不进分母", () => {
    const err = leaveOneDayOutDeviation(samplesOf([...perfect, iv("2026-09-04T00:00:00Z", 2, 5)]), fixedFit);
    expect(err).toBe(0);
  });

  it("计分天数不足 3 天时返回 null（一两天的偏差不构成回测证据）", () => {
    const intervals = [iv("2026-09-01T00:00:00Z", 20, 10), iv("2026-09-02T00:00:00Z", 40, 20), iv("2026-09-03T00:00:00Z", 1, 0.5)];
    expect(leaveOneDayOutDeviation(samplesOf(intervals), fixedFit)).toBeNull();
    expect(leaveOneDayOutDeviation(samplesOf(perfect), fixedFit)).toBe(0);
  });
});

describe("toSamples", () => {
  it("独立复算：dayKey 是 t0 的日期部分，row 是 keys 顺序对应的 familyPricedTokens，weight 来自 weightOf", () => {
    const interval = iv("2026-09-05T12:34:56Z", 7, 3);
    const [sample] = toSamples([interval], ["a", "b"], () => 0.5);
    expect(sample.dayKey).toBe("2026-09-05");
    expect(sample.row).toEqual([3, 0]); // "a" 有 feature=3，"b" 没出现在 familyPricedTokens 里 → 0
    expect(sample.weight).toBe(0.5);
    expect(sample.deltaU).toBe(7);
  });
});
