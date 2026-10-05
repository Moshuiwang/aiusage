import { withWorker } from "./harness";
import { repoRoot } from "./paths";
import path from "node:path";

export const quotaUnavailableOwnerFixturePath = path.join(repoRoot,
  "clients/macos/Tests/AIUsageMenuBarCoreTests/Fixtures/quota-unavailable-owner.json");
export const quotaUnavailableNow = "2026-06-10T12:00:00+08:00";

/** 输入仅为 D1 事实；客户端 fixture 由完整认证路由产出。两日守住元数据不相加。 */
export async function collectQuotaUnavailableSummary(): Promise<Record<string, any>> {
  return withWorker({ now: quotaUnavailableNow }, async ({ fetchRaw, db }) => {
    await db.prepare(`INSERT INTO source_identities
      (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at)
      VALUES ('quota-owner', 'quota-host', 'quota-host', 'quota-user', 'darwin', ?, ?)`)
      .bind(quotaUnavailableNow, quotaUnavailableNow).run();
    for (const [provider, models] of [
      ["codex", ["gpt-6-sol", "gpt-5.6-sol", "unmapped-model"]],
      ["claude", ["claude-opus-5", "claude-sonnet-5", "claude-haiku-5", "claude-fable-5"]],
    ] as const) {
      for (const day of ["09", "10"]) {
        const fact = `${provider}-${day}`;
        const total = models.length * 500 + (provider === "codex" ? 100 : 0);
        await db.prepare(`INSERT INTO usage_hourly_facts (
          fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
          window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
          cache_read_tokens, total_tokens, attribution_confidence, provenance, first_seen_at, last_seen_at
        ) VALUES (?, 'quota-owner', 'quota-host', 'quota-user', ?, 'test-account', ?, 'cli',
          ?, ?, 'Asia/Shanghai', ?, 0, 0, 0, ?, 'observed', 'test', ?, ?)`)
          .bind(fact, provider, provider, `2026-06-${day}T02:00:00+08:00`,
            `2026-06-${day}T03:00:00+08:00`, total, total, quotaUnavailableNow, quotaUnavailableNow).run();
        for (const model of models) await db.prepare(`INSERT INTO usage_hourly_models (
          fact_id, model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
          total_tokens, first_seen_at, last_seen_at) VALUES (?, ?, 500, 0, 0, 0, 500, ?, ?)`)
          .bind(fact, model, quotaUnavailableNow, quotaUnavailableNow).run();
      }
    }
    for (const [provider, family, grade, error, sample, fittedAt, formula] of [
      ["codex", "gpt-6", "none", -2.306, 92, quotaUnavailableNow, "v1"],
      ["codex", "gpt-5.6", "none", null, 0, quotaUnavailableNow, "v1"],
      ["claude", "opus", "A", 0.05, 20, quotaUnavailableNow, "v1"],
      ["claude", "sonnet", "B", 0.2, 10, "2026-06-01T12:00:00+08:00", "v1"],
      ["claude", "fable", "B", 0.2, 10, quotaUnavailableNow, "v0"],
    ]) await db.prepare(`INSERT INTO quota_calibration (
      provider, model_family, coef, effective_delta_u, backtest_max_err, grade,
      sample_intervals, fitted_at, formula_version) VALUES (?, ?, 0.00001, 12.5, ?, ?, ?, ?, ?)`)
      .bind(provider, family, error, grade, sample, fittedAt, formula).run();
    const response = await fetchRaw({ method: "GET", path: "/api/mobile/summary?period=week", auth: true });
    if (response.status !== 200) throw new Error(`owner route failed: ${response.status}`);
    return JSON.parse(response.body.toString());
  });
}
