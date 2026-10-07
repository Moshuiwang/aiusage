/**
 * #271：校准公式 v2——API 价格先验 + 单一隐藏额度 + 已知变更日强制切分。
 *
 * 用 `calibration_fixture_2026-10-07.json`（生产只读导出，截点 2026-10-07T02:30Z，导出方式见
 * 其 `_comment` 与 `scripts/export_calibration_fixture.py`）驱动。期望值来自 #271 研究阶段的
 * 独立离线实验（同一批生产数据、独立特征构造脚本），不是从本实现跑出来再抄回来的：
 * - Claude「单一阀门 + 模型按 API 基础价比、族内 1/5/1.25/0.1」留出总偏差约 10%；
 * - Codex 09-29 之后按档位价（官方 credit 表比例）单一阀门，留出总偏差约 12%，混入 09-29 之前
 *   的数据则约 48%。
 */
import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { calibrate, FORMULA_VERSION } from "../src/calibration/index";
import { FAMILY_PRICE_RATIO, KNOWN_CHANGE_POINTS, trainingStartFor } from "../src/calibration/constants";
import { splitCycles, withResetAnchors } from "../src/calibration/cycles";
import { buildIntervals } from "../src/calibration/intervals";
import type { HourlyFamilyFact, LimitObservation } from "../src/calibration/types";

const FIXTURE_PATH = new URL("./calibration_fixture_2026-10-07.json", import.meta.url);
const NOW = new Date("2026-10-07T02:30:00Z");

async function loadFixture(): Promise<{ limit_observations: LimitObservation[]; hourly_family_facts: HourlyFamilyFact[] }> {
  return JSON.parse(await readFile(FIXTURE_PATH, "utf8"));
}

describe("v2：口径版本", () => {
  it("公式口径变化必须递增 FORMULA_VERSION，读侧据此把旧系数判为 formula_changed", () => {
    expect(FORMULA_VERSION).toBe("v2");
  });
});

describe("v2：已知变更日", () => {
  it("训练起点取 now 之前最近的一个已知变更日；未来的变更日不提前生效", () => {
    expect(KNOWN_CHANGE_POINTS.codex).toEqual(["2026-09-22T00:00:00Z", "2026-09-29T00:00:00Z", "2026-10-29T00:00:00Z"]);
    expect(trainingStartFor("codex", new Date("2026-09-25T00:00:00Z"))).toBe("2026-09-22T00:00:00Z");
    expect(trainingStartFor("codex", NOW)).toBe("2026-09-29T00:00:00Z");
    expect(trainingStartFor("codex", new Date("2026-10-30T00:00:00Z"))).toBe("2026-10-29T00:00:00Z");
    expect(trainingStartFor("codex", new Date("2026-09-01T00:00:00Z"))).toBeNull();
    expect(trainingStartFor("claude", NOW)).toBeNull();
  });
});

describe("v2：Claude（单一阀门 + API 基础价比）", () => {
  it("各族系数之比严格等于 API 基础价比，opus / sonnet / fable 定级至少 B，账户总偏差 ≤20%", async () => {
    const { limit_observations, hourly_family_facts } = await loadFixture();
    const out = calibrate("claude", limit_observations.filter((r) => r.provider === "claude"), hourly_family_facts, { now: NOW });
    const by = Object.fromEntries(out.results.map((r) => [r.model_family, r]));
    expect(Object.keys(by).sort()).toEqual(["fable", "haiku", "opus", "sonnet"]);
    const ratio = FAMILY_PRICE_RATIO.claude;
    expect(ratio).toEqual({ opus: 4, sonnet: 2, haiku: 1, fable: 10 });
    expect(by.opus.coef).toBeGreaterThan(0);
    for (const family of ["sonnet", "haiku", "fable"]) {
      expect(by[family].coef / by.opus.coef).toBeCloseTo(ratio[family] / ratio.opus, 9);
    }
    for (const family of ["opus", "sonnet", "fable"]) {
      expect(["A", "B"]).toContain(by[family].grade);
      expect(by[family].formula_version).toBe("v2");
    }
    // 账户级回测：所有族共享同一个偏差值，且落在 B 门槛内。
    expect(new Set(out.results.map((r) => r.backtest_max_err)).size).toBe(1);
    expect(by.opus.backtest_max_err as number).toBeGreaterThanOrEqual(0);
    expect(by.opus.backtest_max_err as number).toBeLessThanOrEqual(0.2);
    // 量级：100% 周额度约等于 API 价 $2,000–$4,000（研究阶段约 $2,760）。
    // coef 单位是「额度点 / 价格加权 token」；opus 价比 4（$4/MTok input）→ 每 µ$ 的额度点 = coef / 4。
    const dollarsPerWeek = 100 / ((by.opus.coef / ratio.opus) * 1e6);
    expect(dollarsPerWeek).toBeGreaterThan(2000);
    expect(dollarsPerWeek).toBeLessThan(4000);
  });

  it("冷启动：某个有价格的族在训练窗口里零用量，仍按价比拿到系数和降级的 B 档估算，而不是 none", async () => {
    const { limit_observations, hourly_family_facts } = await loadFixture();
    const withoutHaiku = hourly_family_facts.filter((f) => !(f.provider === "claude" && f.model_family === "haiku"));
    const out = calibrate("claude", limit_observations.filter((r) => r.provider === "claude"), withoutHaiku, { now: NOW });
    const by = Object.fromEntries(out.results.map((r) => [r.model_family, r]));
    expect(by.haiku.effective_delta_u).toBe(0);
    expect(by.haiku.coef).toBeCloseTo(by.opus.coef / 4, 15);
    expect(by.haiku.grade).toBe("B"); // 自身没有样本，最多 B，不能拿到 A
  });
});

describe("v2：Codex（官方 credit 表档位价 + 09-29 后强制切分）", () => {
  it("只用 09-29 之后的区间训练；档位系数之比等于官方 credit 表比例；有用量的档位定级至少 B", async () => {
    const { limit_observations, hourly_family_facts } = await loadFixture();
    const codexObs = limit_observations.filter((r) => r.provider === "codex");
    const out = calibrate("codex", codexObs, hourly_family_facts, { now: NOW });
    const by = Object.fromEntries(out.results.map((r) => [r.model_family, r]));
    expect(Object.keys(by).sort()).toEqual(["astra", "luna", "review", "sol", "terra"]);

    // 独立数出 09-29 之后（且在 28 天窗口内）的区间数：sample_intervals 不得超过它。
    const { intervals } = buildIntervals("codex", "combined", withResetAnchors(splitCycles(codexObs)), hourly_family_facts);
    const afterCut = intervals.filter((i) => Date.parse(i.t0) >= Date.parse("2026-09-29T00:00:00Z")).length;
    expect(afterCut).toBeGreaterThan(30);
    expect(by.sol.sample_intervals).toBeGreaterThan(0);
    expect(by.sol.sample_intervals).toBeLessThanOrEqual(afterCut);

    const ratio = FAMILY_PRICE_RATIO.codex;
    expect(ratio).toEqual({ astra: 250, sol: 50, terra: 50, luna: 2.5 });
    expect(by.astra.coef / by.sol.coef).toBeCloseTo(5, 9);
    expect(by.sol.coef / by.luna.coef).toBeCloseTo(20, 9);
    expect(by.terra.coef).toBeCloseTo(by.sol.coef, 15);
    for (const family of ["astra", "sol", "luna"]) expect(["A", "B"]).toContain(by[family].grade);
    expect(by.sol.backtest_max_err as number).toBeLessThanOrEqual(0.2);
  });
});

describe("v2：Antigravity（无公开价目，仍逐族各自拟合）", () => {
  it("没有价比先验的族互不共用系数：有用量的 flash 定级 B，无用量的族 none", async () => {
    const { limit_observations, hourly_family_facts } = await loadFixture();
    const out = calibrate("antigravity", limit_observations.filter((r) => r.provider === "antigravity"), hourly_family_facts, { now: NOW });
    const by = Object.fromEntries(out.results.map((r) => [r.model_family, r]));
    expect(Object.keys(by).sort()).toEqual(["claude-on-antigravity", "flash", "pro"]);
    expect(FAMILY_PRICE_RATIO.antigravity).toEqual({});
    expect(by.flash.grade).toBe("B");
    expect(by.flash.effective_delta_u).toBeGreaterThanOrEqual(4);
    expect(by.flash.backtest_max_err as number).toBeLessThanOrEqual(0.2);
    for (const family of ["pro", "claude-on-antigravity"]) {
      expect(by[family].grade).toBe("none");
      expect(by[family].effective_delta_u).toBe(0);
    }
  });
});

describe("v2：有价比的族自身样本不足时最多 B（合成数据，偏差≈0，组 ΔU 充足）", () => {
  // 一个 Codex 周期：10-01 起 6 天，每小时 sol 与 luna 都有用量，额度严格按「共用系数 × 价比 × 加权 token」
  // 线性增长（小数读数，无取整误差）→ 逐日留出总偏差≈0，有价比的组 ΔU 远超 10。
  // sol 自身 ΔU 约 100 点 → A；luna 价比只有 sol 的 1/20，自身 ΔU 约 3 点 → 只能 B。
  const C = 7e-9; // 额度点 / (价比 × 加权 token)
  const start = Date.parse("2026-10-01T00:00:00Z");
  const hours = 6 * 24;
  const facts: HourlyFamilyFact[] = [];
  const observations: LimitObservation[] = [];
  let used = 0;
  for (let h = 0; h < hours; h++) {
    const ws = new Date(start + h * 3600e3).toISOString();
    const we = new Date(start + (h + 1) * 3600e3).toISOString();
    const sol = h % 2 === 0 ? 1e6 : 2e6;
    const luna = h % 3 === 0 ? 3e6 : 1e6;
    for (const [family, input] of [["sol", sol], ["luna", luna]] as const) {
      facts.push({ provider: "codex", model_family: family, window_start: ws, window_end: we,
        input_tokens: input, output_tokens: 0, cache_creation_tokens: 0, cache_read_tokens: 0 });
    }
    for (const half of [0, 1]) {
      used += C * (50 * sol + 2.5 * luna) / 2;
      observations.push({ source_id: "s", provider: "codex", observed_at: new Date(start + h * 3600e3 + (half + 1) * 1800e3).toISOString(),
        reset_at: "2026-10-08T00:00:00Z", used_percent: used, window_duration_minutes: 10080 });
    }
  }
  observations.unshift({ ...observations[0], observed_at: new Date(start).toISOString(), used_percent: 0 });

  it("主力族 A、小族封顶 B；共用系数还原出真实值", () => {
    const out = calibrate("codex", observations, facts, { now: new Date("2026-10-07T00:00:00Z") });
    const by = Object.fromEntries(out.results.map((r) => [r.model_family, r]));
    expect(used).toBeGreaterThan(60);
    expect(used).toBeLessThan(95); // 不进入饱和剔除
    expect(by.sol.backtest_max_err as number).toBeLessThan(0.01);
    expect(by.sol.coef).toBeCloseTo(C * 50, 12);
    expect(by.sol.effective_delta_u).toBeGreaterThan(10);
    expect(by.luna.effective_delta_u).toBeGreaterThan(0);
    expect(by.luna.effective_delta_u).toBeLessThan(10);
    expect(by.sol.grade).toBe("A");
    expect(by.luna.grade).toBe("B");
    expect(by.terra.grade).toBe("B"); // 零样本、有价比：冷启动
    expect(by.review.grade).toBe("none"); // 无价比、无样本：不估算
  });
});
