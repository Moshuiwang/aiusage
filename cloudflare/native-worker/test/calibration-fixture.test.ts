/**
 * #183-a：用真实（脱敏）D1 快照驱动的端到端覆盖。
 *
 * fixture 来源与重新生成方式见 `scripts/export_calibration_fixture.py` 头注释和
 * `test/calibration_fixture.json` 的 `_comment` 字段——这份 fixture 一个字节不许手写、
 * 不许手改。这份数据反映的是 2026-09-27 生产账户的真实使用形态，不是为了凑测试编的。
 *
 * 2026-09-27 二次导出（#183 数据完整性核查后的补扫）：Mac Codex 在 mac-local 9/14–9/20
 * 缺失的 model 行已通过 `--ledger-mode incremental --ledger-lookback-hours 323` 回填并回源
 * 核对（77 条 fact 全部带模型行，token 合计一致，见 Issue #183 评论）。二次导出后重跑本文件：
 * Codex 的 unattributed 完整性门禁不再剔除任何区间（`unattributedDroppedIntervals` 从 10
 * 变为 0，可用区间从 21 增到 34），但 Codex 逐日留出回测误差仍然巨大（约 5.5，即 550%，
 * 比补扫前的 5.78 只略微下降），全部族仍定级 none——backfill 解决的是「模型行缺失」这一项
 * 数据完整性问题，不能解决 Codex 账户读数本身漂移大、报告空洞多这些独立问题（详见 Issue
 * #183 数据完整性核查评论第 2、3、5 节）。
 *
 * 结论对照 #183 设计 v1 §0（数据依据）和数据完整性核查评论：Claude 现在能算出 B 档信号
 * （逐日留出最大误差落在 [10%,25%] 区间）；Codex 因账户读数漂移大、报告空洞多，定级 none
 * （不再是 unattributed 完整性门禁剔除的问题）；Antigravity 数据不足（3 天、频繁重置），
 * 定级 none。这些是从这份真实 fixture 跑出来的结果，不是预设结论。
 */
import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { splitCycles, withResetAnchors } from "../src/calibration/cycles";
import { calibrate } from "../src/calibration/index";
import { buildIntervals } from "../src/calibration/intervals";
import { priceWeightedTokens } from "../src/calibration/constants";
import type { HourlyFamilyFact, LimitObservation } from "../src/calibration/types";

const FIXTURE_PATH = new URL("./calibration_fixture.json", import.meta.url);
const NOW = new Date("2026-09-27T11:00:00Z"); // 快照导出时刻之后不久（补扫后重新导出），覆盖整段 28 天训练窗口。

async function loadFixture(): Promise<{ limit_observations: LimitObservation[]; hourly_family_facts: HourlyFamilyFact[] }> {
  const raw = await readFile(FIXTURE_PATH, "utf8");
  return JSON.parse(raw);
}

describe("calibration fixture：结构下限", () => {
  it("fixture 覆盖三个 provider、每个都有真实的官方读数与小时事实", async () => {
    const { limit_observations, hourly_family_facts } = await loadFixture();
    expect(limit_observations.length).toBeGreaterThan(1000);
    expect(hourly_family_facts.length).toBeGreaterThan(100);
    const providers = new Set(limit_observations.map((r) => r.provider));
    expect(providers).toEqual(new Set(["claude", "codex", "antigravity"]));
    // unattributed 伪族必须真的出现在 fixture 里——否则 unattributed 剔除规则的测试是空转的。
    const families = new Set(hourly_family_facts.map((f) => f.model_family));
    expect(families.has("unattributed")).toBe(true);
  });
});

describe("calibration fixture：周期与重置次数（精确值，对照 #183 数据完整性核查）", () => {
  it("Claude：4 个周期（1 次真实重置 + 2 个新到账来源各贡献 1 条历史孤立读数）", async () => {
    // 二次导出比首次多出 2 条：`linux-biai-wangzhipeng`（07-18 单条）、`claude-main`
    // （08-02 单条，reset_at 早于 observed_at，本身就是陈旧占位读数）——这两个来源在首次
    // 导出时刻还未在 limit_window_history 里出现过，是首次导出之后、二次导出之前新上报的。
    // 账户级周期切分不按 source_id 分组（见 src/calibration/index.ts 顶部注释），这两条孤立
    // 读数各自因为跟主时间线的 reset_at 差异 >2 分钟被切成独立周期，但每个周期只有 1 条读数，
    // 无法组成任何 ≥2 点区间，不参与拟合与回测（对照下面「Claude 定级」用例：sample_intervals
    // 从 55 增到 57，是主时间线新增的真实读数，不是这两条孤立点贡献的）。
    const { limit_observations } = await loadFixture();
    const rows = limit_observations.filter((r) => r.provider === "claude");
    const cycles = withResetAnchors(splitCycles(rows));
    expect(cycles).toHaveLength(4);
    const degenerate = cycles.filter((c) => c.readings.length === 1);
    expect(degenerate).toHaveLength(2);
  });

  it("Codex：4 个周期、3 次重置（9/19 一次自然 + 9/26 两次，含滚动噪音已被丢弃）", async () => {
    const { limit_observations } = await loadFixture();
    const rows = limit_observations.filter((r) => r.provider === "codex");
    const cycles = withResetAnchors(splitCycles(rows));
    expect(cycles).toHaveLength(4);
  });
});

describe("calibration fixture：Claude 定级（逐族）", () => {
  it("opus / sonnet / fable 因为有足够的价格加权 token 信号，定级 B；haiku 因量太少定级 none", async () => {
    const { limit_observations, hourly_family_facts } = await loadFixture();
    const out = calibrate("claude", limit_observations.filter((r) => r.provider === "claude"), hourly_family_facts, { now: NOW });
    expect(out.unattributedDroppedIntervals).toBe(0); // Claude 这份快照里模型行覆盖完整
    const byFamily = Object.fromEntries(out.results.map((r) => [r.model_family, r]));
    expect(Object.keys(byFamily).sort()).toEqual(["fable", "haiku", "opus", "sonnet"]);

    for (const family of ["opus", "sonnet", "fable"]) {
      expect(byFamily[family].grade).toBe("B");
      expect(byFamily[family].effective_delta_u).toBeGreaterThanOrEqual(4);
      expect(byFamily[family].backtest_max_err).not.toBeNull();
      expect(Math.abs(byFamily[family].backtest_max_err as number)).toBeLessThanOrEqual(0.25);
      expect(byFamily[family].coef).toBeGreaterThan(0);
      expect(byFamily[family].formula_version).toBe("v1");
      expect(byFamily[family].fitted_at).toBe(NOW.toISOString());
    }
    expect(byFamily.haiku.grade).toBe("none");
    expect(byFamily.haiku.effective_delta_u).toBe(0);

    // 同量级校验（对照可行性分析 calib.py 的 d2_fam_pricew 拟合结果，容差按数量级）：
    // opus≈0.1455、sonnet≈0.0451（该脚本用 /1e6 的 token 单位，这里换算回同一单位对比）。
    expect(byFamily.opus.coef * 1e6).toBeGreaterThan(0.05);
    expect(byFamily.opus.coef * 1e6).toBeLessThan(0.5);
    expect(byFamily.sonnet.coef * 1e6).toBeGreaterThan(0.01);
    expect(byFamily.sonnet.coef * 1e6).toBeLessThan(0.2);

    // 逐日留出最大误差同量级：分析结论中位 10%、最大 17%；本内核加了近期加权/突变检测，
    // 训练集构成不同，允许到设计给的 B 档上限（25%）以内，但必须显著优于「不可用」(>50%)。
    for (const family of ["opus", "sonnet", "fable"]) {
      expect(Math.abs(byFamily[family].backtest_max_err as number)).toBeLessThan(0.5);
    }
  });

  it("同一批区间下，所有已知族共享同一个 sample_intervals 与 backtest_max_err（账户级回测，不是逐族独立回测）", async () => {
    const { limit_observations, hourly_family_facts } = await loadFixture();
    const out = calibrate("claude", limit_observations.filter((r) => r.provider === "claude"), hourly_family_facts, { now: NOW });
    const sampleCounts = new Set(out.results.map((r) => r.sample_intervals));
    const errs = new Set(out.results.map((r) => r.backtest_max_err));
    expect(sampleCounts.size).toBe(1);
    expect(errs.size).toBe(1);
    expect(out.results[0].sample_intervals).toBeGreaterThan(0);
  });
});

describe("calibration fixture：Codex 定级（设计结论：现在不可用）", () => {
  it("mac-local 9/14–9/20 model 行补扫后，unattributed 门禁不再剔除任何区间，但账户读数漂移大、报告空洞多，全部族仍定级 none", async () => {
    // 补扫前（见本文件头注释）unattributedDroppedIntervals=10、sample_intervals=21、
    // backtest_max_err≈5.78；补扫后 0 / 34 / ≈5.50——可用区间变多了，但回测误差量级没有
    //实质改善（仍是「不可用」>50% 的量级好几倍），跟 Issue #183 数据完整性核查结论一致：
    // model 行缺失只是 Codex 数据问题的一部分，账户读数本身长时间空洞、饱和 plateau 才是
    // 主因，补扫不能单独解决。
    const { limit_observations, hourly_family_facts } = await loadFixture();
    const codexObs = limit_observations.filter((r) => r.provider === "codex");
    const out = calibrate("codex", codexObs, hourly_family_facts, { now: NOW });
    expect(out.unattributedDroppedIntervals).toBe(0);
    expect(Object.keys(Object.fromEntries(out.results.map((r) => [r.model_family, r]))).sort()).toEqual(["astra", "luna", "review", "sol", "terra"]);
    for (const r of out.results) {
      expect(r.grade).toBe("none");
      // 回测误差仍然巨大（远超「不可用」阈值 0.5），确认「剔除消失」不等于「数据变可用」。
      expect(Math.abs(r.backtest_max_err as number)).toBeGreaterThan(1);
    }
  });

  it("独立验证：fixture 里仍然存在 unattributed 事实（linux-biai-wangzp 等来源仍缺 model 行），只是量不足以在任一区间触发 5% 门禁", async () => {
    const { hourly_family_facts } = await loadFixture();
    const codexFacts = hourly_family_facts.filter((f) => f.provider === "codex");
    const unattributed = codexFacts.filter((f) => f.model_family === "unattributed");
    expect(unattributed.length).toBeGreaterThan(0);
    // 独立从原始 fixture 字段复算：这些 unattributed 行里，至少有一部分是「全额缺失」
    // （output_tokens 明显是完整小时用量的量级，不是零头）。
    const totalUnattributedOutput = unattributed.reduce((s, f) => s + f.output_tokens, 0);
    expect(totalUnattributedOutput).toBeGreaterThan(0);
  });
});

describe("calibration fixture：Antigravity（设计结论：数据不足）", () => {
  it("3 天、频繁重置、样本不足，全部族定级 none", async () => {
    const { limit_observations, hourly_family_facts } = await loadFixture();
    const out = calibrate("antigravity", limit_observations.filter((r) => r.provider === "antigravity"), hourly_family_facts, { now: NOW });
    for (const r of out.results) {
      expect(r.grade).toBe("none");
    }
  });
});

describe("calibration fixture：独立复算（不调用 buildIntervals，直接从原始字段算）", () => {
  it("从 Claude 原始官方读数与小时事实独立复算某个区间的 ΔU 与加权 ΔT，跟内核产出的区间一致", async () => {
    const { limit_observations, hourly_family_facts } = await loadFixture();
    const claudeObs = limit_observations.filter((r) => r.provider === "claude");
    const cycles = withResetAnchors(splitCycles(claudeObs));
    const { intervals } = buildIntervals("claude", "combined", cycles, hourly_family_facts);
    expect(intervals.length).toBeGreaterThan(10);

    // 挑一个有具体 family token 分摊的区间，独立复算（不用 buildIntervals 内部的分摊 helper）。
    const target = intervals.find((i) => (i.familyPricedTokens.opus ?? 0) > 0 && i.deltaU !== 0);
    expect(target).toBeDefined();
    if (!target) throw new Error("unreachable");

    // ΔU 独立复算：直接用区间自带的 u0/u1，不调用任何 helper。
    expect(target.u1 - target.u0).toBeCloseTo(target.deltaU, 9);

    // 加权 ΔT 独立复算：从原始小时事实按重叠比例手算 opus 的加权 token 总量，
    // 用跟 intervals.ts 完全独立的一段代码（这里直接用 priceWeightedTokens + 手写重叠区间交集）。
    const t0 = Date.parse(target.t0);
    const t1 = Date.parse(target.t1);
    let recomputedOpus = 0;
    for (const fact of hourly_family_facts) {
      if (fact.provider !== "claude" || fact.model_family !== "opus") continue;
      const ws = Date.parse(fact.window_start);
      const we = Date.parse(fact.window_end);
      const overlap = Math.min(we, t1) - Math.max(ws, t0);
      if (overlap <= 0) continue;
      const fraction = overlap / (we - ws);
      recomputedOpus += priceWeightedTokens("claude", fact) * fraction;
    }
    expect(recomputedOpus).toBeCloseTo(target.familyPricedTokens.opus, 3);
  });
});
