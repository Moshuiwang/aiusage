import { readFile } from "node:fs/promises";
import { Miniflare } from "miniflare";
import { describe, expect, it } from "vitest";
import { applySqlText, bundleWorker, withWorker } from "./golden/harness";
import { collectModelPayloads } from "./golden/navigation-models";
import { schemaPath, token } from "./golden/paths";

describe.sequential("read consistency while display projection needs retry", () => {
  it("uses the actual instant for UTC facts and model rows across the Shanghai day boundary", async () => {
    await withWorker({ now: "2026-09-22T12:00:00+08:00" }, async ({ db, fetchRaw }) => {
      for (const payload of collectModelPayloads()) {
        payload.usage_ledger_runs = [];
        for (const fact of payload.usage_hourly_facts) {
          fact.window_start = "2026-09-21T17:00:00Z";
          fact.window_end = "2026-09-21T18:00:00Z";
        }
        expect((await fetchRaw({ method: "POST", path: "/ingest", auth: true, body: payload })).status).toBe(200);
      }
      await db.prepare("INSERT OR IGNORE INTO usage_rollup_dirty_days VALUES ('2026-09-22')").run();
      const response = await fetchRaw({ method: "GET", path: "/api/mobile/summary?period=today&offset=0", auth: true });
      expect(response.status).toBe(200);
      const body = JSON.parse(response.body.toString());
      expect(body.period.total_tokens).toBe(1000);
      expect(body.breakdown.by_source).toHaveLength(2);
      const models = body.breakdown.by_source.flatMap((source: any) => source.agents).flatMap((agent: any) => agent.models);
      expect(models).toHaveLength(7);
      expect(models.filter((model: any) => model.id === "gpt-6-sol").reduce((sum: number, model: any) => sum + model.tokens, 0)).toBe(200);
    });
  });
  it("preserves authoritative archived daily fallback while rebuilding other facts", async () => {
    await withWorker({ now: "2026-09-22T12:00:00+08:00" }, async ({ db, fetchRaw }) => {
      for (const payload of collectModelPayloads()) {
        expect((await fetchRaw({ method: "POST", path: "/ingest", auth: true, body: payload })).status).toBe(200);
      }
      await db.prepare("UPDATE usage_daily_rollups SET provenance='historical_ccusage_fallback_v1',total_tokens=700,input_tokens=700,output_tokens=0,cache_read_tokens=0 WHERE source_id='model-linux'").run();
      await db.prepare("DELETE FROM usage_hourly_facts WHERE source_id='model-linux'").run();
      expect(await db.prepare("SELECT sum(total_tokens) AS n FROM usage_hourly_facts").first("n")).toBe(650);
      expect(await db.prepare("SELECT sum(total_tokens) AS n FROM usage_daily_rollups WHERE provenance='historical_ccusage_fallback_v1'").first("n")).toBe(700);
      for (const period of ["week", "month"]) {
        const response = await fetchRaw({ method: "GET", path: `/api/mobile/summary?period=${period}&offset=0`, auth: true });
        expect(response.status).toBe(200);
        const body = JSON.parse(response.body.toString());
        expect(body.period.total_tokens).toBe(1350);
        expect(body.breakdown.by_source).toHaveLength(2);
        expect(body.breakdown.by_source.reduce((n: number, row: any) => n + row.tokens, 0)).toBe(1350);
      }
    });
  });
  it("reads canonical nonempty facts instead of incomplete hour and day projections", async () => {
    await withWorker({ now: "2026-09-22T12:00:00+08:00" }, async ({ db, fetchRaw }) => {
      await db.prepare("CREATE TABLE IF NOT EXISTS usage_rollup_dirty_days (date TEXT PRIMARY KEY)").run();
      for (const payload of collectModelPayloads()) {
        expect((await fetchRaw({ method: "POST", path: "/ingest", auth: true, body: payload })).status).toBe(200);
      }
      await db.prepare("UPDATE usage_hourly_rollups SET total_tokens = 1, input_tokens = 1, output_tokens = 0, cache_read_tokens = 0").run();
      await db.prepare("UPDATE usage_daily_rollups SET total_tokens = 1, input_tokens = 1, output_tokens = 0, cache_read_tokens = 0").run();
      await db.prepare("INSERT OR IGNORE INTO usage_rollup_dirty_days VALUES ('2026-09-22')").run();
      expect(await db.prepare("SELECT sum(total_tokens) AS n FROM usage_hourly_facts").first("n")).toBe(1000);
      let checked = 0;
      for (const period of ["today", "week", "month"]) {
        for (const endpoint of ["/api/summary", "/api/mobile/summary"]) {
          const response = await fetchRaw({ method: "GET", path: `${endpoint}?period=${period}&offset=0`, auth: true });
          expect(response.status).toBe(200);
          const body = JSON.parse(response.body.toString());
          expect((body.period ?? body.summary).total_tokens).toBe(1000);
          checked++;
        }
      }
      expect(checked).toBe(6);
    });
  });

  it("does not serve a cached projection while a newer canonical revision is pending", async () => {
    const mf = new Miniflare({ modules: true, script: await bundleWorker(), scriptPath: "index.mjs",
      compatibilityDate: "2026-06-21", d1Databases: ["AIUSAGE_DB"], bindings: {
        AIUSAGE_TOKEN: token, AIUSAGE_TIMEZONE: "Asia/Shanghai", AIUSAGE_NOW: "2026-09-22T12:00:00+08:00",
        AIUSAGE_CACHE_NAMESPACE: crypto.randomUUID(),
      } });
    try {
      const db = await mf.getD1Database("AIUSAGE_DB");
      await applySqlText(db, await readFile(schemaPath, "utf8"));
      await db.prepare("CREATE TABLE IF NOT EXISTS usage_rollup_dirty_days (date TEXT PRIMARY KEY)").run();
      const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
      for (const payload of collectModelPayloads()) {
        const response = await mf.dispatchFetch("http://native.test/ingest", { method: "POST", headers, body: JSON.stringify(payload) });
        expect(response.status).toBe(200);
      }
      const url = "http://native.test/api/mobile/summary?period=today&offset=0";
      const first = await mf.dispatchFetch(url, { headers });
      expect((await first.json() as any).period.total_tokens).toBe(1000);
      const cached = await mf.dispatchFetch(url, { headers });
      expect(cached.headers.get("X-AIUsage-Cache")).toBe("HIT");
      await db.prepare("UPDATE usage_hourly_facts SET input_tokens=input_tokens+100,total_tokens=total_tokens+100").run();
      await db.prepare("INSERT OR IGNORE INTO usage_rollup_dirty_days VALUES ('2026-09-22')").run();
      expect(await db.prepare("SELECT sum(total_tokens) AS n FROM usage_hourly_facts").first("n")).toBe(1300);
      const pending = await mf.dispatchFetch(url, { headers });
      expect((await pending.json() as any).period.total_tokens).toBe(1300);
      expect(pending.headers.get("X-AIUsage-Cache")).not.toBe("HIT");
    } finally { await mf.dispose(); }
  });
});
