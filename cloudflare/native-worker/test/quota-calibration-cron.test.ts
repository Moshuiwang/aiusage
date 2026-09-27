/**
 * #183-b：每日 cron 接线（`runQuotaCalibration`）——SQL 聚合 → 族映射 → `calibrate()` →
 * 覆盖写 `quota_calibration`，以及账户冲突降级。
 */
import { describe, expect, it } from "vitest";
import { acquireWorker } from "./golden/harness";
import { fixedNow, timezone } from "./golden/paths";
import { runQuotaCalibration } from "../src/quota-calibration-cron";
import { calibrate } from "../src/calibration";
import type { HourlyFamilyFact, LimitObservation } from "../src/calibration";

const NOW = new Date("2026-06-10T03:17:00+08:00");
const sourceId = "cron-source";

async function seedIdentity(db: D1Database): Promise<void> {
  await db.batch([
    db.prepare(`
      INSERT INTO source_identities (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).bind(sourceId, "cron-host", "cron-host", "tester", "darwin", fixedNow, fixedNow),
    db.prepare(`
      INSERT INTO machines (machine_id, machine_name, host, platform, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `).bind("cron-host", "cron-host", "cron-host", "darwin", fixedNow, fixedNow),
  ]);
}

async function seedLimitReadings(db: D1Database, readings: LimitObservation[]): Promise<void> {
  await db.batch(readings.map((r) => db.prepare(`
    INSERT INTO limit_window_history (
      source_id, provider, window, used_percent, remaining_percent, reset_at,
      window_duration_minutes, source_type, confidence, status, observed_at, recorded_at
    ) VALUES (?, ?, 'week', ?, ?, ?, ?, 'official', 'observed', 'ok', ?, ?)
  `).bind(
    r.source_id, r.provider, r.used_percent, 100 - r.used_percent, r.reset_at,
    r.window_duration_minutes, r.observed_at, r.observed_at,
  )));
}

async function seedHourlyFact(
  db: D1Database,
  factId: string,
  agent: string,
  windowStart: string,
  windowEnd: string,
  models: Array<{ model: string; input: number; output: number }>,
): Promise<void> {
  const totalInput = models.reduce((s, m) => s + m.input, 0);
  const totalOutput = models.reduce((s, m) => s + m.output, 0);
  const statements = [
    db.prepare(`
      INSERT INTO usage_hourly_facts (
        fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, total_tokens, attribution_confidence, provenance, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, 'observed', 'live', ?, ?)
    `).bind(
      factId, sourceId, "cron-host", "tester", agent, `${agent}-main`, agent, "cli",
      windowStart, windowEnd, timezone, totalInput, totalOutput, totalInput + totalOutput,
      fixedNow, fixedNow,
    ),
  ];
  for (const m of models) {
    statements.push(db.prepare(`
      INSERT INTO usage_hourly_models (
        fact_id, model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        total_tokens, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, 0, 0, ?, ?, ?)
    `).bind(factId, m.model, m.input, m.output, m.input + m.output, fixedNow, fixedNow));
  }
  await db.batch(statements);
}

async function seedAccountObservation(db: D1Database, provider: string, fingerprint: string, observedAt: string): Promise<void> {
  await db.prepare(`
    INSERT INTO account_observations (source_id, provider, account_fingerprint, first_seen_at, last_seen_at)
    VALUES (?, ?, ?, ?, ?)
  `).bind(sourceId, provider, fingerprint, observedAt, observedAt).run();
}

describe("runQuotaCalibration", () => {
  it("对没有冲突的账户：SQL 聚合出的官方读数与小时事实喂给 calibrate()，结果整表覆盖写 quota_calibration", async () => {
    const { db } = await acquireWorker({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: timezone });
    await seedIdentity(db);

    const t0 = "2026-06-01T00:00:00Z";
    const t1 = "2026-06-01T04:00:00Z"; // 4 小时后，够 3 小时合并门槛
    const resetAt = "2026-06-08T00:00:00Z";
    const readings: LimitObservation[] = [
      { source_id: sourceId, provider: "claude", observed_at: t0, reset_at: resetAt, used_percent: 0, window_duration_minutes: 10080 },
      { source_id: sourceId, provider: "claude", observed_at: t1, reset_at: resetAt, used_percent: 20, window_duration_minutes: 10080 },
    ];
    await seedLimitReadings(db, readings);

    const factWindowStart = "2026-06-01T01:00:00Z";
    const factWindowEnd = "2026-06-01T02:00:00Z";
    await seedHourlyFact(db, "fact-1", "claude", factWindowStart, factWindowEnd, [
      { model: "claude-opus-4-8", input: 1000, output: 2_000_000 },
    ]);
    await seedAccountObservation(db, "claude", "fp:claude:aaaaaaaaaaaaaaaaaaaaaaaa", t0);

    await runQuotaCalibration(db, NOW);

    const rows = await db.prepare("SELECT * FROM quota_calibration WHERE provider = 'claude' ORDER BY model_family")
      .all<Record<string, unknown>>();
    expect(rows.results.map((r) => r.model_family).sort()).toEqual(["fable", "haiku", "opus", "sonnet"]);

    // 独立复算：直接用手写的 LimitObservation/HourlyFamilyFact（不是从 D1 再读一遍）调
    // 已经测过的 calibrate() 核心函数，跟 runQuotaCalibration 写进表里的结果比对——
    // 这条断言核实的是「SQL 抽取 + 族映射」这一层，不是 calibrate() 本身。
    const expectedFacts: HourlyFamilyFact[] = [{
      provider: "claude", model_family: "opus", window_start: factWindowStart, window_end: factWindowEnd,
      input_tokens: 1000, output_tokens: 2_000_000, cache_creation_tokens: 0, cache_read_tokens: 0,
    }];
    const expected = calibrate("claude", readings, expectedFacts, { now: NOW });
    const expectedOpus = expected.results.find((r) => r.model_family === "opus")!;
    const actualOpus = rows.results.find((r) => r.model_family === "opus")!;
    expect(Number(actualOpus.coef)).toBeCloseTo(expectedOpus.coef, 12);
    expect(Number(actualOpus.effective_delta_u)).toBeCloseTo(expectedOpus.effective_delta_u, 9);
    expect(Number(actualOpus.sample_intervals)).toBe(expectedOpus.sample_intervals);
    expect(String(actualOpus.fitted_at)).toBe(NOW.toISOString());
    expect(String(actualOpus.formula_version)).toBe(expectedOpus.formula_version);
  });

  it("整表覆盖写：第二次跑会先删掉这个 provider 的旧行，不会残留上一次的族", async () => {
    const { db } = await acquireWorker({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: timezone });
    await seedIdentity(db);
    await seedAccountObservation(db, "claude", "fp:claude:aaaaaaaaaaaaaaaaaaaaaaaa", fixedNow);
    await runQuotaCalibration(db, NOW);
    const firstCount = await db.prepare("SELECT COUNT(*) AS c FROM quota_calibration WHERE provider = 'claude'").first<{ c: number }>();
    expect(Number(firstCount?.c)).toBe(4); // 4 个已知族

    await runQuotaCalibration(db, NOW); // 再跑一次：不应该翻倍
    const secondCount = await db.prepare("SELECT COUNT(*) AS c FROM quota_calibration WHERE provider = 'claude'").first<{ c: number }>();
    expect(Number(secondCount?.c)).toBe(4);
  });

  it("最近 28 天同一 provider 出现 >1 个账户指纹：整个 provider 全部族降级成 none", async () => {
    const { db } = await acquireWorker({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: timezone });
    await seedIdentity(db);
    const t0 = "2026-06-01T00:00:00Z";
    const t1 = "2026-06-01T04:00:00Z";
    const resetAt = "2026-06-08T00:00:00Z";
    await seedLimitReadings(db, [
      { source_id: sourceId, provider: "claude", observed_at: t0, reset_at: resetAt, used_percent: 0, window_duration_minutes: 10080 },
      { source_id: sourceId, provider: "claude", observed_at: t1, reset_at: resetAt, used_percent: 20, window_duration_minutes: 10080 },
    ]);
    await seedHourlyFact(db, "fact-conflict", "claude", "2026-06-01T01:00:00Z", "2026-06-01T02:00:00Z", [
      { model: "claude-opus-4-8", input: 1000, output: 2_000_000 },
    ]);
    // 两个不同指纹：账户被切换过。
    await seedAccountObservation(db, "claude", "fp:claude:aaaaaaaaaaaaaaaaaaaaaaaa", t0);
    await seedAccountObservation(db, "claude", "fp:claude:bbbbbbbbbbbbbbbbbbbbbbbb", t1);

    await runQuotaCalibration(db, NOW);

    const rows = await db.prepare("SELECT * FROM quota_calibration WHERE provider = 'claude'").all<Record<string, unknown>>();
    expect(rows.results).toHaveLength(4);
    for (const row of rows.results) {
      expect(row.grade).toBe("none");
      expect(Number(row.coef)).toBe(0);
      expect(Number(row.effective_delta_u)).toBe(0);
      expect(row.backtest_max_err).toBeNull();
      expect(Number(row.sample_intervals)).toBe(0);
    }
  });
});
