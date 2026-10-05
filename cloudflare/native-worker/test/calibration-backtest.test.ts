/** #183-a：精度分级门槛（grade）与逐日留出回测的基本行为。 */
import { describe, expect, it } from "vitest";
import { grade, leaveOneDayOutMaxError, toSamples } from "../src/calibration/backtest";
import { nonNegativeLeastSquares } from "../src/calibration/nnls";
import type { Interval } from "../src/calibration/types";

describe("grade", () => {
  it("effectiveDeltaU ≥10 且回测最大误差 ≤10% → A", () => {
    expect(grade(10, 0.1)).toBe("A");
    expect(grade(50, 0)).toBe("A");
  });

  it("effectiveDeltaU ≥4 且回测最大误差 ≤25% → B（不满足 A 的门槛时降级，不是直接 A）", () => {
    expect(grade(4, 0.25)).toBe("B");
    expect(grade(10, 0.2)).toBe("B"); // effU 够 A，但误差超过 10%，只能是 B
  });

  it("effectiveDeltaU 或误差任一不达标 → none", () => {
    expect(grade(3.9, 0.05)).toBe("none"); // effU 不够
    expect(grade(4, 0.26)).toBe("none"); // 误差超过 B 门槛
    expect(grade(0, 0)).toBe("none");
  });

  it("回测误差为 null（没有任何一天满足最小 ΔU 门槛）时永远 none，不管 effectiveDeltaU 多大", () => {
    expect(grade(1000, null)).toBe("none");
  });

  it("误差取绝对值：负的相对误差同样受门槛约束", () => {
    expect(grade(10, -0.05)).toBe("A");
    expect(grade(10, -0.2)).toBe("B");
  });

  it("【变异证据】未见族（effectiveDeltaU=0）如果不经过门槛检查直接判 A/B，会把没见过的族错误定级", () => {
    const brokenGrade = (effU: number, err: number | null) => (err !== null && Math.abs(err) <= 0.25 ? "B" : "none");
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

describe("leaveOneDayOutMaxError", () => {
  const fit = (rows: number[][], targets: number[], weights: number[]) => nonNegativeLeastSquares(rows, targets, weights);
  const w = () => 1;
  const samplesOf = (intervals: Interval[]) => toSamples(intervals, ["a"], w);

  it("完美线性数据（y=2x，跨多天）留出回测误差应接近 0", () => {
    const intervals = [
      iv("2026-09-01T00:00:00Z", 20, 10),
      iv("2026-09-02T00:00:00Z", 40, 20),
      iv("2026-09-03T00:00:00Z", 60, 30),
      iv("2026-09-04T00:00:00Z", 80, 40),
    ];
    const err = leaveOneDayOutMaxError(samplesOf(intervals), fit);
    expect(err).not.toBeNull();
    expect(Math.abs(err as number)).toBeLessThan(0.05);
  });

  it("当天实际 ΔU 之和小于最小门槛（3）时跳过该天，不产出误判的巨大相对误差", () => {
    const intervals = [
      iv("2026-09-01T00:00:00Z", 20, 10),
      iv("2026-09-02T00:00:00Z", 20, 10),
      iv("2026-09-03T00:00:00Z", 1, 0.5), // 当天 ΔU=1 <3，应被跳过
    ];
    const err = leaveOneDayOutMaxError(samplesOf(intervals), fit);
    // 只有两天参与（09-01、09-02），线性完美拟合，误差应接近 0；09-03 被跳过不会拉高误差。
    expect(err).not.toBeNull();
    expect(Math.abs(err as number)).toBeLessThan(0.05);
  });

  // #206：官方 used_percent 是整数，3 点的计分日自带 ±1 点（±33%）取整误差。
  // 产品负责人 2026-10-06 决定：某天「相对误差 ≤ 门槛」或「绝对误差 ≤ 1 个点」即算合格。
  const perfect = [
    iv("2026-09-01T00:00:00Z", 20, 10),
    iv("2026-09-02T00:00:00Z", 40, 20),
    iv("2026-09-03T00:00:00Z", 60, 30),
  ];

  it("绝对误差 ≤1 个点的计分日属于整数取整误差，记 0（实际 3、预测 4）", () => {
    const err = leaveOneDayOutMaxError(samplesOf([...perfect, iv("2026-09-04T00:00:00Z", 3, 2)]), fit);
    expect(err).not.toBeNull();
    expect(Math.abs(err as number)).toBeLessThan(0.05);
  });

  it("绝对误差超过 1 个点仍按相对误差计（实际 4、预测 6 → +50%）", () => {
    const err = leaveOneDayOutMaxError(samplesOf([...perfect, iv("2026-09-04T00:00:00Z", 4, 3)]), fit);
    expect(err).toBeCloseTo(0.5, 2);
  });

  it("大涨幅日不享受 1 个点宽限（实际 20、预测 26 → +30%）", () => {
    const err = leaveOneDayOutMaxError(samplesOf([...perfect, iv("2026-09-04T00:00:00Z", 20, 13)]), fit);
    expect(err).toBeCloseTo(0.3, 2);
  });

  it("没有任何一天的 ΔU 达到门槛时返回 null", () => {
    const intervals = [iv("2026-09-01T00:00:00Z", 1, 0.5), iv("2026-09-02T00:00:00Z", 2, 1)];
    expect(leaveOneDayOutMaxError(samplesOf(intervals), fit)).toBeNull();
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
