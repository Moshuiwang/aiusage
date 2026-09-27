/**
 * #190 P1（Codex 审查发现）：`usage_rollup_dirty_update` 触发器的 WHEN 条件不含
 * `total_cost`，导致后续 ingest 只修正某条 fact 的 `total_cost`（其它列不变）时，
 * 当天不会被标脏（`usage_rollup_dirty_days`），rollup 的 `sum(total_cost)`
 * （migration 0014 补的那一列）永远不会重算——summary 里的费用会一直停在第一次
 * ingest 时的旧值，即使 `usage_hourly_facts.total_cost` 本身已经被 UPSERT 更新了。
 *
 * 复现路径：两次真实 `/ingest`，UPSERT 冲突键完全相同（source_id/agent/client/
 * window_start/window_end/ai_provider/ai_account_id/attribution_confidence/
 * provenance 九列不变），只改 `usage.total_cost`。
 */
import { describe, expect, it } from "vitest";
import { withWorker } from "./golden/harness";
import { fixedNow, timezone } from "./golden/paths";

type AnyRecord = Record<string, unknown>;

const SOURCE_ID = "cost-only-update-device";
const FACT_WINDOW_START = "2026-06-03T09:00:00+08:00";
const FACT_WINDOW_END = "2026-06-03T10:00:00+08:00";
const FACT_DATE = "2026-06-03"; // = fixedNow 的产品日

function ingestPayload(totalCost: number, factId: string): AnyRecord {
  return {
    schema_version: 1,
    source_id: SOURCE_ID,
    host: "cost-host",
    machine: "cost-host",
    os_user: "tester",
    platform: "darwin",
    timezone,
    observed_at: "2026-06-03T10:40:00+08:00",
    collection_window: "hourly",
    usage_hourly_facts: [{
      fact_id: factId,
      agent: "claude",
      window_start: FACT_WINDOW_START,
      window_end: FACT_WINDOW_END,
      attribution_confidence: "observed",
      provenance: "test",
      usage: { input_tokens: 100, output_tokens: 50, total_tokens: 150, total_cost: totalCost },
    }],
  };
}

describe.sequential("#190 P1：只改 total_cost 的 ingest 必须让当天重新标脏并重算 rollup", () => {
  it("先红：第二次 ingest 只改 total_cost，rollup 的 total_cost 和 /api/summary 都必须跟着更新", async () => {
    await withWorker({ now: fixedNow }, async ({ fetchRaw, db }) => {
      // 第一次 ingest：total_cost = 1.0，走完整的真实写路径（包括
      // handleIngestWrite -> refreshDisplayRollups），rollup 立即算出 1.0，
      // 当天不再是 dirty。
      const first = await fetchRaw({ method: "POST", path: "/ingest", auth: true, body: ingestPayload(1.0, "fact-cost-v1") });
      expect(first.status, "第一次 ingest 必须成功").toBe(200);

      const dirtyAfterFirst = await db.prepare(
        "SELECT count(*) AS n FROM usage_rollup_dirty_days WHERE date = ?",
      ).bind(FACT_DATE).first<{ n: number }>();
      expect(dirtyAfterFirst?.n, "第一次 ingest 后应该已经重算完，不再是 dirty").toBe(0);

      const rollupCostAfterFirst = await db.prepare(
        "SELECT total_cost FROM usage_daily_rollups WHERE source_id = ? AND date = ?",
      ).bind(SOURCE_ID, FACT_DATE).first<{ total_cost: number | null }>();
      expect(rollupCostAfterFirst?.total_cost).toBeCloseTo(1.0, 6);

      // 第二次 ingest：UPSERT 冲突键的九列一个不变，只把 total_cost 改成 99.0。
      // fact_id 故意也换一个，证明冲突键判定不依赖 fact_id（UPSERT 是按
      // source_id/agent/client/window_start/window_end/ai_provider/ai_account_id/
      // attribution_confidence/provenance 匹配，fact_id 本身会被 excluded.fact_id 覆盖）。
      const second = await fetchRaw({ method: "POST", path: "/ingest", auth: true, body: ingestPayload(99.0, "fact-cost-v2") });
      expect(second.status, "第二次 ingest 必须成功").toBe(200);

      const factRow = await db.prepare(
        "SELECT total_cost FROM usage_hourly_facts WHERE source_id = ?",
      ).bind(SOURCE_ID).first<{ total_cost: number | null }>();
      expect(factRow?.total_cost, "facts 表本身必须已经被 UPSERT 更新——这一步不该红，红了说明复现方式本身有问题").toBeCloseTo(99.0, 6);

      // 核心断言：rollup 的 total_cost 必须跟着变成 99.0，不能停在第一次的 1.0。
      // 触发器 WHEN 条件不含 total_cost 时，这条会红（rollup 停留在旧值，
      // usage_rollup_dirty_days 也不会有这一天）。
      const rollupCostAfterSecond = await db.prepare(
        "SELECT total_cost FROM usage_daily_rollups WHERE source_id = ? AND date = ?",
      ).bind(SOURCE_ID, FACT_DATE).first<{ total_cost: number | null }>();
      expect(rollupCostAfterSecond?.total_cost, "daily rollup 的 total_cost 必须跟着 fact 更新").toBeCloseTo(99.0, 6);

      const hourlyRollupCostAfterSecond = await db.prepare(
        "SELECT total_cost FROM usage_hourly_rollups WHERE source_id = ?",
      ).bind(SOURCE_ID).first<{ total_cost: number | null }>();
      expect(hourlyRollupCostAfterSecond?.total_cost, "hourly rollup 的 total_cost 必须跟着 fact 更新").toBeCloseTo(99.0, 6);

      // summary 是给用户看的最终产物：直接从 HTTP 合同拿 total_cost，不信任内部实现细节。
      const summaryResponse = await fetchRaw({
        method: "GET", path: `/api/summary?period=today&date=${FACT_DATE}&machine=cost-host`, auth: true,
      });
      expect(summaryResponse.status).toBe(200);
      const summaryBody = JSON.parse(summaryResponse.body.toString("utf8")) as { items: Array<{ total_cost: number | null }> };
      expect(summaryBody.items.length).toBeGreaterThan(0);
      for (const item of summaryBody.items) {
        expect(item.total_cost, "/api/summary 的费用不能停留在第一次 ingest 的旧值").toBeCloseTo(99.0, 6);
      }
    });
  });
});
