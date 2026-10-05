/**
 * #183-b：`quota_estimate` 挂到 `/api/summary` 的 `items[].model_breakdowns[]` 和
 * `/api/mobile/summary` 的 `breakdown.by_source[].agents[].models[]`（`source-breakdown.ts`
 * 的 `sourceAgents()` 把同名模型的 percent 相加，只在 grade/basis 一致、status="available"
 * 时才带过去）。
 */
import { describe, expect, it } from "vitest";
import { withWorker } from "./golden/harness";

const sourceId = "qe-source";
const machineId = "qe-host";
const osUser = "qe-user";
const opusInput = 1000;
const opusOutput = 2_000_000;
const COEF = 0.00001; // percent per raw priced token

async function seedIdentity(db: D1Database, now: string): Promise<void> {
  await db.batch([
    db.prepare(`
      INSERT INTO source_identities (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).bind(sourceId, machineId, machineId, osUser, "darwin", now, now),
    db.prepare(`
      INSERT INTO machines (machine_id, machine_name, host, platform, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `).bind(machineId, machineId, machineId, "darwin", now, now),
    db.prepare(`
      INSERT OR IGNORE INTO ai_accounts (provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at)
      VALUES ('claude', 'claude-main', ?, ?, NULL, ?, ?)
    `).bind(osUser, osUser, now, now),
  ]);
}

async function seedOpusFact(db: D1Database, factId: string, windowStart: string, windowEnd: string, now: string): Promise<void> {
  const total = opusInput + opusOutput;
  await db.batch([
    db.prepare(`
      INSERT INTO usage_hourly_facts (
        fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, total_tokens, attribution_confidence, provenance, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, 'claude', 'claude-main', 'claude', 'cli', ?, ?, 'Asia/Shanghai', ?, ?, 0, 0, ?, 'observed', 'live', ?, ?)
    `).bind(factId, sourceId, machineId, osUser, windowStart, windowEnd, opusInput, opusOutput, total, now, now),
    db.prepare(`
      INSERT INTO usage_hourly_models (
        fact_id, model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        total_tokens, first_seen_at, last_seen_at
      ) VALUES (?, 'claude-opus-4-8', ?, ?, 0, 0, ?, ?, ?)
    `).bind(factId, opusInput, opusOutput, total, now, now),
  ]);
}

async function seedCalibration(
  db: D1Database,
  family: string,
  grade: string,
  fittedAt: string,
  coef = COEF,
  formulaVersion = "v1",
): Promise<void> {
  await db.prepare(`
    INSERT INTO quota_calibration (
      provider, model_family, coef, effective_delta_u, backtest_max_err, grade,
      sample_intervals, fitted_at, formula_version
    ) VALUES ('claude', ?, ?, 12.5, 0.2, ?, 10, ?, ?)
  `).bind(family, coef, grade, fittedAt, formulaVersion).run();
}

// 手算常数，不复用被测代码路径上的 priceWeightedTokens：Claude output 权重是 5，
// input 权重是 1（cache_creation/cache_read 都是 0，本测试没喂那两种 token）。
// 加权 token = 1000×1 + 2,000,000×5 = 1000 + 10,000,000 = 10,001,000。
const opusWeightedTokens = opusInput * 1 + opusOutput * 5;
const rawPercent = COEF * opusWeightedTokens; // 0.00001 × 10,001,000 = 100.01

describe("quota_estimate on /api/summary", () => {
  it("grade=B 且系数未过期：items[].model_breakdowns[] 附加 quota_estimate（today 期，basis=week）", async () => {
    const now = "2026-06-10T12:00:00+08:00";
    await withWorker({ now }, async ({ fetchRaw, db }) => {
      await seedIdentity(db, now);
      await seedOpusFact(db, "fact-qe-1", "2026-06-10T02:00:00+08:00", "2026-06-10T03:00:00+08:00", now);
      await seedCalibration(db, "opus", "B", now);

      const response = await fetchRaw({ method: "GET", path: "/api/summary?period=today", auth: true });
      expect(response.status).toBe(200);
      const body = JSON.parse(response.body.toString());
      const opusBreakdown = body.items.flatMap((item: any) => item.model_breakdowns)
        .find((m: any) => m.model_name === "claude-opus-4-8");
      expect(opusBreakdown).toBeDefined();
      expect(opusBreakdown.quota_estimate).toBeDefined();
      expect(opusBreakdown.quota_estimate.grade).toBe("B");
      expect(opusBreakdown.quota_estimate.basis).toBe("week");
      expect(opusBreakdown.quota_estimate.percent).toBeCloseTo(rawPercent, 6);
    });
  });

  it("同一份数据在 /api/mobile/summary 的 breakdown.by_source[]/by_machine[]/by_os_user[] 三处 agents[].models[] 都带着相同的 quota_estimate（#184 依赖 by_machine）", async () => {
    const now = "2026-06-10T12:00:00+08:00";
    await withWorker({ now }, async ({ fetchRaw, db }) => {
      await seedIdentity(db, now);
      await seedOpusFact(db, "fact-qe-2", "2026-06-10T02:00:00+08:00", "2026-06-10T03:00:00+08:00", now);
      await seedCalibration(db, "opus", "B", now);

      const response = await fetchRaw({ method: "GET", path: "/api/mobile/summary?period=today", auth: true });
      expect(response.status).toBe(200);
      const body = JSON.parse(response.body.toString());

      function opusModelIn(groups: any[]): any {
        const models = groups.flatMap((g: any) => g.agents).flatMap((a: any) => a.models);
        return models.find((m: any) => m.id === "claude-opus-4-8");
      }

      // 结构下限：三处分组都必须真的有数据（不是空数组），否则下面找不到 opus 模型行
      // 的断言对着一个恒为 undefined 的目标，测不出任何东西。
      expect(body.breakdown.by_source.length).toBeGreaterThan(0);
      expect(body.breakdown.by_machine.length).toBeGreaterThan(0);
      expect(body.breakdown.by_os_user.length).toBeGreaterThan(0);

      for (const [label, groups] of [
        ["by_source", body.breakdown.by_source],
        ["by_machine", body.breakdown.by_machine],
        ["by_os_user", body.breakdown.by_os_user],
      ] as const) {
        const opusModel = opusModelIn(groups);
        expect(opusModel, `${label} 里应该有 claude-opus-4-8 这一行`).toBeDefined();
        expect(opusModel.status, label).toBe("available");
        expect(opusModel.quota_estimate, label).toBeDefined();
        expect(opusModel.quota_estimate.grade, label).toBe("B");
        expect(opusModel.quota_estimate.basis, label).toBe("week");
        expect(opusModel.quota_estimate.percent, label).toBeCloseTo(rawPercent, 6);
      }
    });
  });

  it("grade=none：不附加 quota_estimate（缺省字段，不是 null）", async () => {
    const now = "2026-06-10T12:00:00+08:00";
    await withWorker({ now }, async ({ fetchRaw, db }) => {
      await seedIdentity(db, now);
      await seedOpusFact(db, "fact-qe-3", "2026-06-10T02:00:00+08:00", "2026-06-10T03:00:00+08:00", now);
      await seedCalibration(db, "opus", "none", now);

      const response = await fetchRaw({ method: "GET", path: "/api/summary?period=today", auth: true });
      const body = JSON.parse(response.body.toString());
      const opusBreakdown = body.items.flatMap((item: any) => item.model_breakdowns)
        .find((m: any) => m.model_name === "claude-opus-4-8");
      expect(opusBreakdown).toBeDefined();
      expect("quota_estimate" in opusBreakdown).toBe(false);
    });
  });

  it("fitted_at 超过 4 天：不附加 quota_estimate（过期降级）", async () => {
    const now = "2026-06-10T12:00:00+08:00";
    const staleFittedAt = "2026-06-06T00:00:00+08:00"; // 距 now 超过 4 天
    await withWorker({ now }, async ({ fetchRaw, db }) => {
      await seedIdentity(db, now);
      await seedOpusFact(db, "fact-qe-4", "2026-06-10T02:00:00+08:00", "2026-06-10T03:00:00+08:00", now);
      await seedCalibration(db, "opus", "B", staleFittedAt);

      const response = await fetchRaw({ method: "GET", path: "/api/summary?period=today", auth: true });
      const body = JSON.parse(response.body.toString());
      const opusBreakdown = body.items.flatMap((item: any) => item.model_breakdowns)
        .find((m: any) => m.model_name === "claude-opus-4-8");
      expect("quota_estimate" in opusBreakdown).toBe(false);
    });
  });

  it("系数的 formula_version 与当前公式不一致：不附加（避免新权重乘旧系数，Codex PR #189 审查 P2）", async () => {
    const now = "2026-06-10T12:00:00+08:00";
    await withWorker({ now }, async ({ fetchRaw, db }) => {
      await seedIdentity(db, now);
      await seedOpusFact(db, "fact-qe-fv", "2026-06-10T02:00:00+08:00", "2026-06-10T03:00:00+08:00", now);
      await seedCalibration(db, "opus", "B", "2026-06-10T03:17:00+08:00", COEF, "v0-old");

      const response = await fetchRaw({ method: "GET", path: "/api/summary?period=today", auth: true });
      const body = JSON.parse(response.body.toString());
      const opusBreakdown = body.items.flatMap((item: any) => item.model_breakdowns)
        .find((m: any) => m.model_name === "claude-opus-4-8");
      expect(opusBreakdown).toBeDefined();
      expect("quota_estimate" in opusBreakdown).toBe(false);
    });
  });

  it("没有 quota_calibration 行（族没算出来过）：不附加", async () => {
    const now = "2026-06-10T12:00:00+08:00";
    await withWorker({ now }, async ({ fetchRaw, db }) => {
      await seedIdentity(db, now);
      await seedOpusFact(db, "fact-qe-5", "2026-06-10T02:00:00+08:00", "2026-06-10T03:00:00+08:00", now);
      // 不 seed quota_calibration。

      const response = await fetchRaw({ method: "GET", path: "/api/summary?period=today", auth: true });
      const body = JSON.parse(response.body.toString());
      const opusBreakdown = body.items.flatMap((item: any) => item.model_breakdowns)
        .find((m: any) => m.model_name === "claude-opus-4-8");
      expect("quota_estimate" in opusBreakdown).toBe(false);
    });
  });

  it("月视图按周均折算（basis=weekly_average）：percent 除以已计天数/7", async () => {
    // now = 2026-06-10，不带 offset 的 "month" 是滚动 30 天窗口（periodBounds：
    // start = date - 29 天），起点到 min(end,今天) 含首尾共 30 天 → weeks = 30/7。
    const now = "2026-06-10T12:00:00+08:00";
    await withWorker({ now }, async ({ fetchRaw, db }) => {
      await seedIdentity(db, now);
      await seedOpusFact(db, "fact-qe-6", "2026-06-05T02:00:00+08:00", "2026-06-05T03:00:00+08:00", now);
      await seedCalibration(db, "opus", "B", now);

      const response = await fetchRaw({ method: "GET", path: "/api/summary?period=month", auth: true });
      const body = JSON.parse(response.body.toString());
      expect(body.summary.start_date).toBe("2026-05-12");
      expect(body.summary.end_date).toBe("2026-06-10");
      const opusBreakdown = body.items.flatMap((item: any) => item.model_breakdowns)
        .find((m: any) => m.model_name === "claude-opus-4-8");
      expect(opusBreakdown.quota_estimate.basis).toBe("weekly_average");
      const expectedWeeks = 30 / 7;
      expect(opusBreakdown.quota_estimate.percent).toBeCloseTo(rawPercent / expectedWeeks, 6);
    });
  });
});


describe("quota_estimate_unavailable truthful diagnosis", () => {
  it("same failed account backtest survives two days and all three mobile groups without summing error", async () => {
    const now = "2026-06-10T12:00:00+08:00";
    await withWorker({ now }, async ({ fetchRaw, db }) => {
      await seedIdentity(db, now);
      await seedOpusFact(db, "diag-day-1", "2026-06-09T02:00:00+08:00", "2026-06-09T03:00:00+08:00", now);
      await seedOpusFact(db, "diag-day-2", "2026-06-10T02:00:00+08:00", "2026-06-10T03:00:00+08:00", now);
      await seedCalibration(db, "opus", "none", now);
      await db.prepare("UPDATE quota_calibration SET backtest_max_err = -2.306, sample_intervals = 92").run();
      const response = await fetchRaw({ method: "GET", path: "/api/mobile/summary?period=week", auth: true });
      expect(response.status).toBe(200);
      const body = JSON.parse(response.body.toString());
      for (const key of ["by_source", "by_machine", "by_os_user"]) {
        expect(body.breakdown[key]).toHaveLength(1);
        const models = body.breakdown[key][0].agents.flatMap((a: any) => a.models);
        expect(models).toHaveLength(1);
        expect(models[0].tokens).toBe(2 * (opusInput + opusOutput));
        expect(models[0].quota_estimate).toBeUndefined();
        expect(models[0].quota_estimate_unavailable).toEqual({
          reason: "backtest_failed", sample_intervals: 92, backtest_max_error: 2.306,
        });
      }
      const raw = await fetchRaw({ method: "GET", path: "/api/summary?period=week", auth: true });
      const details = JSON.parse(raw.body.toString()).items.flatMap((i: any) => i.model_breakdowns);
      expect(details).toHaveLength(2);
      for (const model of details) expect(model.quota_estimate_unavailable).toEqual({
        reason: "backtest_failed", sample_intervals: 92, backtest_max_error: 2.306,
      });
    });
  });
});
