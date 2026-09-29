/**
 * #206：额度规则突变（如套餐升级）后训练集的选取。
 *
 * 真实系数的单位是「额度点 / 每个价格加权 token」，量级约 3e-8～1.6e-6（见 quota_calibration
 * 生产行）。这里的合成区间刻意用同一量级，防止「有意义系数」门槛再次按 1e-6 这类与单位
 * 不符的绝对值误判（#206 调查：门槛 1e-6 让突变检测对所有族都跳过，从未生效）。
 */
import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { KNOWN_FAMILIES } from "../src/calibration/constants";
import type { Provider } from "../src/calibration/constants";
import { splitCycles, withResetAnchors } from "../src/calibration/cycles";
import { detectMutationAndSelectTrainingSet } from "../src/calibration/index";
import { buildIntervals } from "../src/calibration/intervals";
import type { HourlyFamilyFact, Interval, LimitObservation } from "../src/calibration/types";

const KEYS = ["a"];
const w = () => 1;

/** 一个区间：t0 在 day 当天 hour 点，价格加权 token = tokens，ΔU = coef × tokens（取整模拟整数百分比读数）。 */
function iv(cycleIndex: number, day: string, hour: number, tokens: number, coef: number): Interval {
  const t0 = `${day}T${String(hour).padStart(2, "0")}:00:00.000Z`;
  const deltaU = Math.round(coef * tokens * 100) / 100;
  return { sourceId: "combined", cycleIndex, t0, t1: t0, u0: 0, u1: deltaU, deltaU, familyPricedTokens: { a: tokens } };
}

/** 一个周期：连续若干天、每天 3 个区间，token 量有起伏。 */
function cycle(cycleIndex: number, days: string[], coef: number): Interval[] {
  const out: Interval[] = [];
  const volumes = [8e6, 12e6, 5e6];
  for (const day of days) volumes.forEach((tokens, k) => out.push(iv(cycleIndex, day, 2 + k * 5, tokens, coef)));
  return out;
}

const OLD = 8e-7; // 旧规则：每 1M 加权 token 约 0.8 点
const NEW = 2.5e-7; // 新规则（套餐升级后）：约 0.25 点，差约 3 倍

describe("规则突变：训练集选取", () => {
  it("系数量级 ~1e-7 时，最近周期相对全量偏离 >2 倍必须被识别为突变，只用新规则数据", () => {
    const old0 = cycle(0, ["2026-09-17", "2026-09-18"], OLD);
    const old1 = cycle(1, ["2026-09-20", "2026-09-21", "2026-09-22"], OLD);
    const new2 = cycle(2, ["2026-09-27", "2026-09-28"], NEW);
    const all = [...old0, ...old1, ...new2];
    const { training, mutationDetected } = detectMutationAndSelectTrainingSet(all, KEYS, w);
    expect(mutationDetected).toBe(true);
    expect(training).toHaveLength(new2.length);
    expect(training.every((i) => i.cycleIndex === 2)).toBe(true);
  });

  it("新规则跨过一次周重置后，训练集保留突变点之后的全部周期，不缩回最近一个周期", () => {
    const old0 = cycle(0, ["2026-09-17", "2026-09-18", "2026-09-19"], OLD);
    const old1 = cycle(1, ["2026-09-20", "2026-09-21", "2026-09-22"], OLD);
    const new2 = cycle(2, ["2026-09-27", "2026-09-28", "2026-09-29"], NEW);
    const new3 = cycle(3, ["2026-10-04"], NEW); // 周重置后刚开始，只有 3 个区间
    const all = [...old0, ...old1, ...new2, ...new3];
    const { training, mutationDetected } = detectMutationAndSelectTrainingSet(all, KEYS, w);
    expect(mutationDetected).toBe(true);
    expect(training).toHaveLength(new2.length + new3.length);
    expect(new Set(training.map((i) => i.cycleIndex))).toEqual(new Set([2, 3]));
  });

  it("多族、整数百分比取整噪音下，主力族系数降为约 1/3 仍被识别为突变（正向用例，防门槛过严漏判）", () => {
    // 3 个族按 60/30/10 占比混用，ΔU 取整到整数点（官方读数形态）；旧规则 a=8e-7、b=1.5e-7，
    // 新规则 a 降到 2.5e-7（#206 生产实测 Codex gpt-6 从约 0.8 降到约 0.2 点/1M），b 不变。
    const keys = ["a", "b", "c"];
    const coefOld = [8e-7, 1.5e-7, 3e-8];
    const coefNew = [2.5e-7, 1.5e-7, 3e-8];
    const volumes = [9e6, 14e6, 6e6, 11e6];
    const mk = (cycleIndex: number, days: string[], coef: number[]): Interval[] => days.flatMap((day) =>
      volumes.map((v, k) => {
        const tokens = { a: v * 0.6, b: v * 0.3, c: v * 0.1 };
        const exact = tokens.a * coef[0] + tokens.b * coef[1] + tokens.c * coef[2];
        const deltaU = Math.round(exact);
        const t0 = `${day}T${String(1 + k * 5).padStart(2, "0")}:00:00.000Z`;
        return { sourceId: "combined", cycleIndex, t0, t1: t0, u0: 0, u1: deltaU, deltaU, familyPricedTokens: tokens };
      }));
    const old0 = mk(0, ["2026-09-17", "2026-09-18", "2026-09-19"], coefOld);
    const old1 = mk(1, ["2026-09-20", "2026-09-21", "2026-09-22"], coefOld);
    const new2 = mk(2, ["2026-09-27", "2026-09-28", "2026-09-29"], coefNew);
    const all = [...old0, ...old1, ...new2];
    const { training, mutationDetected } = detectMutationAndSelectTrainingSet(all, keys, w);
    expect(mutationDetected).toBe(true);
    expect(training).toHaveLength(new2.length);
    expect(training.every((i) => i.cycleIndex === 2)).toBe(true);
  });

  it("各周期系数一致（同一规则、量级 ~1e-7）时不判突变，使用全部区间", () => {
    const all = [
      ...cycle(0, ["2026-09-17", "2026-09-18"], NEW),
      ...cycle(1, ["2026-09-20", "2026-09-21"], NEW * 1.2),
      ...cycle(2, ["2026-09-27", "2026-09-28"], NEW * 0.9),
    ];
    const { training, mutationDetected } = detectMutationAndSelectTrainingSet(all, KEYS, w);
    expect(mutationDetected).toBe(false);
    expect(training).toHaveLength(all.length);
  });

  it("变化点前段累计 ΔU 不足 10 点（整数百分比取整噪音主导）时，系数比值再大也不判突变", () => {
    // 前段 3 个小区间，旧规则系数下累计约 3 点——模拟 Antigravity 频繁重置留下的碎周期。
    const tinyHead = [iv(0, "2026-09-24", 2, 1.5e6, OLD), iv(0, "2026-09-24", 6, 1e6, OLD), iv(0, "2026-09-24", 9, 1.2e6, OLD)];
    const tail = cycle(1, ["2026-09-25", "2026-09-26", "2026-09-27"], NEW);
    const all = [...tinyHead, ...tail];
    expect(tinyHead.reduce((s, i) => s + i.deltaU, 0)).toBeLessThan(10);
    const { training, mutationDetected } = detectMutationAndSelectTrainingSet(all, KEYS, w);
    expect(mutationDetected).toBe(false);
    expect(training).toHaveLength(all.length);
  });
});

describe("规则突变：真实多族数据不误判（#206 评审回归）", () => {
  // 按小时重放 owner 导出的 fixture，下面的时刻在「只看比值、不与全量拟合比较」的实现下会把
  // Claude 误判成突变（训练集缩到 5 / 21–25 个区间，B 级降成 none）。Claude 这段时间规则没变。
  const FIXTURE_PATH = new URL("./calibration_fixture.json", import.meta.url);

  // Claude 9/24 14:00 与 9/26 20:00 缺「切分残差须 ≤ 全量拟合的一半」会误判；
  // Codex 两个时刻在 9/26 规则变化之前，缺「只比较两段都占 ≥20% 的族」会被小占比族的系数噪音触发。
  const cases: Array<[Provider, string]> = [
    ["claude", "2026-09-24T14:00:00Z"],
    ["claude", "2026-09-26T20:00:00Z"],
    ["claude", "2026-09-27T09:00:00Z"],
    ["codex", "2026-09-20T07:00:00Z"],
    ["codex", "2026-09-21T00:00:00Z"],
  ];
  for (const [provider, at] of cases) {
    it(`${provider} 截至 ${at}：不判突变，训练集 = 窗口内全部区间`, async () => {
      const fixture = JSON.parse(await readFile(FIXTURE_PATH, "utf8")) as {
        limit_observations: LimitObservation[];
        hourly_family_facts: HourlyFamilyFact[];
      };
      const nowMs = Date.parse(at);
      // 与 calibrate() 相同的近期加权（半衰期 7 天），误判依赖这个权重形态。
      const weightOf = (i: Interval) => Math.pow(0.5, Math.max(0, (nowMs - Date.parse(i.t1)) / (24 * 60 * 60 * 1000)) / 7);
      const windowStartMs = nowMs - 28 * 24 * 60 * 60 * 1000;
      const observations = fixture.limit_observations.filter(
        (o) => o.provider === provider && Date.parse(o.observed_at) <= nowMs && Date.parse(o.observed_at) >= windowStartMs,
      );
      const facts = fixture.hourly_family_facts.filter((f) => Date.parse(f.window_start) < nowMs);
      const intervals = buildIntervals(provider, "combined", withResetAnchors(splitCycles(observations)), facts).intervals
        .filter((i) => Date.parse(i.t0) >= windowStartMs);
      expect(new Set(intervals.map((i) => i.cycleIndex)).size).toBeGreaterThan(1); // 有周期边界可供误判，否则用例空转
      expect(intervals.length).toBeGreaterThan(10);
      const { training, mutationDetected } = detectMutationAndSelectTrainingSet(intervals, KNOWN_FAMILIES[provider], weightOf);
      expect(mutationDetected).toBe(false);
      expect(training).toHaveLength(intervals.length);
    });
  }
});
