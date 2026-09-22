import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";
import type { Miniflare } from "miniflare";
import { beforeEach, describe, expect, it } from "vitest";
import { acquireWorker, applySqlText } from "./golden/harness";
import { repoRoot, token } from "./golden/paths";
import { accuracyWriteStatements, buildAccuracyPlans } from "../src/write-model/accuracy";
import { validateIngestPayload } from "../src/write-model/validate";

type RecordValue = Record<string, any>;
const bridge = path.join(repoRoot, "cloudflare/native-worker/test/ingest-reliability-bridge.py");
const day = "2026-07-12";
const hour = (date: string, h: number) => `${date}T${String(h).padStart(2, "0")}:00:00+08:00`;
const observed = (minute: number) => `2026-07-18T01:${String(minute).padStart(2, "0")}:00+00:00`;
const scan = (start: string, end: string, complete = true) => ({
  version: "0.1.0", parser_schema_version: 2, mode: "full-rescan",
  coverage: { start, end }, counts: { read_errors: complete ? 0 : 1, unresolved_mismatch: 0 },
  scan_complete: complete, report_digest: "controlled-full-scan",
});

async function python(args: string[], input: unknown): Promise<any> {
  return new Promise((resolve, reject) => {
    const child = spawn("python3", [bridge, ...args], { cwd: repoRoot, env: { ...process.env, TZ: "UTC" } });
    let output = "";
    let error = "";
    child.stdout.on("data", (chunk) => { output += chunk; });
    child.stderr.on("data", (chunk) => { error += chunk; });
    child.on("error", reject);
    child.on("close", (code) => code === 0 ? resolve(JSON.parse(output)) : reject(new Error(error || `Python exit ${code}`)));
    child.stdin.end(JSON.stringify(input));
  });
}

describe.sequential("history ACK and authoritative projection reliability", () => {
  let mf: Miniflare;
  let db: D1Database;
  let lastRowsWritten = 0;
  beforeEach(async () => {
    ({ mf, db } = await acquireWorker({ AIUSAGE_NOW: "2026-07-18T12:00:00+08:00", AIUSAGE_TIMEZONE: "Asia/Shanghai" }));
  });

  async function post(payload: RecordValue): Promise<RecordValue> {
    const response = await mf.dispatchFetch("http://native.test/ingest", {
      method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json() as RecordValue;
    expect(response.status, JSON.stringify(result)).toBe(200);
    expect(result.status).toBe("accepted");
    lastRowsWritten = Number(response.headers.get("X-AIUsage-Rows-Written"));
    return result;
  }
  async function totals(table: string, source = "retry-device") {
    const rows = await db.prepare(`SELECT total_tokens FROM ${table} WHERE source_id = ?`).bind(source).all<{total_tokens: number}>();
    return { count: rows.results.length, tokens: rows.results.reduce((sum, row) => sum + row.total_tokens, 0) };
  }
  async function assertSummary(date: string, tokens: number, machine = "test-machine") {
    for (const route of ["summary", "mobile/summary"]) {
      const response = await mf.dispatchFetch(`http://native.test/api/${route}?date=${date}&period=today&machine=${machine}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(response.status).toBe(200);
      const result = await response.json() as RecordValue;
      const summary = route === "summary" ? result.summary : result.period;
      expect(summary).toHaveProperty("total_tokens");
      expect(summary.total_tokens, route).toBe(tokens);
    }
  }

  it("keeps every ACKed hour after real Python pusher HTTP batches arrive B then A", async () => {
    const attempts: RecordValue[] = [];
    let count = 0;
    const server = createServer(async (request, response) => {
      try {
        const chunks = [];
        for await (const chunk of request) chunks.push(chunk);
        const body = Buffer.concat(chunks).toString();
        attempts.push(JSON.parse(body));
        if (++count === 1) {
          response.writeHead(503, { "Content-Type": "application/json" });
          response.end(JSON.stringify({ message: "controlled outage before acceptance" }));
          return;
        }
        const workerResponse = await mf.dispatchFetch("http://native.test/ingest", {
          method: "POST", headers: { Authorization: String(request.headers.authorization), "Content-Type": "application/json" }, body,
        });
        response.writeHead(workerResponse.status, { "Content-Type": "application/json" });
        response.end(await workerResponse.text());
      } catch (error) { response.writeHead(500); response.end(JSON.stringify({ message: String(error) })); }
    });
    await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
    try {
      const address = server.address();
      if (!address || typeof address === "string") throw new Error("HTTP listener missing");
      const result = await python(["deliver", `http://127.0.0.1:${address.port}/ingest`], [
        { observed_at: observed(0), hours: [[hour(day, 10), 100]] },
        { observed_at: observed(1), hours: [[hour(day, 11), 200]] },
      ]);
      expect(attempts).toHaveLength(3);
      expect(attempts.map((p) => p.usage_hourly_facts[0].usage.total_tokens)).toEqual([100, 200, 100]);
      expect(result.attempts).toEqual([{ success: false, pending: 1 }, { success: true, pending: 1 }]);
      expect(result.replay).toHaveLength(1);
      expect(result.replay[0].success).toBe(true);
      expect(result.stats).toMatchObject({ pending: 0, dead_letters: 0, delivered_total: 2 });
      expect(result.acknowledged).toHaveLength(2);
      const facts = (await db.prepare("SELECT window_start, total_tokens FROM usage_hourly_facts ORDER BY window_start").all()).results;
      expect(facts).toEqual([{ window_start: hour(day, 10), total_tokens: 100 }, { window_start: hour(day, 11), total_tokens: 200 }]);
      // Recompute from final DB rows and from the Python ACKed payloads independently.
      const ackedTotal = result.acknowledged.flatMap((p: RecordValue) => p.usage_hourly_facts).reduce((sum: number, f: RecordValue) => sum + f.usage.total_tokens, 0);
      expect(ackedTotal).toBe(300);
      for (const table of ["usage_hourly_facts", "usage_hourly_rollups", "usage_daily_rollups"]) expect((await totals(table)).tokens).toBe(ackedTotal);
      const state = await db.prepare("SELECT collected_at, status FROM source_report_states WHERE source_id = 'retry-device'").first();
      expect(state).toEqual({ collected_at: observed(1), status: "ok" });
      await post(result.acknowledged[1]);
      expect(await totals("usage_hourly_facts")).toEqual({ count: 2, tokens: 300 });
      await assertSummary(day, 300);
    } finally { await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve())); }
  });

  it("does not let older same-key revisions or scans replace newer facts and source health", async () => {
    const payloads = await python(["generate"], [
      { observed_at: observed(3), hours: [[hour(day, 10), 300]] },
      { observed_at: observed(1), hours: [[hour(day, 10), 100], [hour(day, 11), 200]], collector: scan(hour(day, 0), hour("2026-07-13", 0)) },
      { observed_at: observed(2), hours: [[hour(day, 10), 100], [hour(day, 11), 200]], collector: scan(hour(day, 0), hour("2026-07-13", 0)) },
    ]);
    for (const payload of payloads) await post(payload);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 2, tokens: 500 });
    expect((await db.prepare("SELECT collected_at FROM source_report_states WHERE source_id = 'retry-device'").first())?.collected_at).toBe(observed(3));
    expect((await db.prepare("SELECT count(*) AS n FROM source_accuracy WHERE source_id = 'retry-device' AND accuracy_status = 'verified'").first())?.n).toBe(0);
  });

  it("retains revision ordering after a newer unchanged report without rewriting usage rows", async () => {
    const payloads = await python(["generate"], [
      { observed_at: observed(0), hours: [[hour(day, 10), 100]] },
      { observed_at: observed(3), hours: [[hour(day, 10), 100]] },
      { observed_at: observed(2), hours: [[hour(day, 10), 200]] },
      { observed_at: observed(4), hours: [[hour(day, 10), 400]] },
    ]);
    await post(payloads[0]);
    const snapshot = await db.prepare("SELECT * FROM usage_hourly_facts").all();
    await post(payloads[1]);
    expect((await db.prepare("SELECT * FROM usage_hourly_facts").all()).results).toEqual(snapshot.results);
    await post(payloads[2]);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 1, tokens: 100 });
    await post(payloads[3]);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 1, tokens: 400 });
    const replay = await post(payloads[3]);
    expect(replay.facts_accepted).toBe(1);
    expect((await db.prepare("SELECT observed_at FROM usage_fact_revisions").all()).results).toEqual([{ observed_at: observed(4) }]);
    expect(await totals("usage_daily_rollups")).toEqual({ count: 1, tokens: 400 });
  });

  it("does not resurrect an authoritatively deleted fact from a delayed older batch", async () => {
    const collector = scan(hour(day, 0), hour("2026-07-13", 0));
    const payloads = await python(["generate"], [
      { observed_at: observed(0), hours: [[hour(day, 10), 100]] },
      { observed_at: observed(3), hours: [], collector },
      { observed_at: observed(4), hours: [], collector },
      { observed_at: observed(2), hours: [[hour(day, 10), 200]] },
    ]);
    for (const payload of payloads.slice(0, 3)) await post(payload);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 0, tokens: 0 });
    await post(payloads[3]);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 0, tokens: 0 });
  });

  it("protects model children on both stable and changed fact IDs during older retries", async () => {
    const payloads = await python(["generate"], [
      { observed_at: observed(3), hours: [[hour(day, 10), 300]], models: [{model: "current", input_tokens: 300, total_tokens: 300}] },
      { observed_at: observed(1), hours: [[hour(day, 10), 100]], models: [{model: "old", input_tokens: 100, total_tokens: 100}] },
    ]);
    await post(payloads[0]);
    expect((await db.prepare("SELECT model, total_tokens FROM usage_hourly_models").all()).results).toEqual([{model: "current", total_tokens: 300}]);
    await post(payloads[1]);
    expect((await db.prepare("SELECT model, total_tokens FROM usage_hourly_models").all()).results).toEqual([{model: "current", total_tokens: 300}]);
    // Exercise the alternate child-deletion route when a stored fact ID was revised,
    // while its complete stable key is unchanged. This is DB state, not a fake wire fixture.
    await db.batch([
      db.prepare("UPDATE usage_hourly_facts SET fact_id = 'revised-fact-id'"),
      db.prepare("UPDATE usage_hourly_models SET fact_id = 'revised-fact-id'"),
    ]);
    await post(payloads[1]);
    expect((await db.prepare("SELECT fact_id, model, total_tokens FROM usage_hourly_models").all()).results).toEqual([{fact_id: "revised-fact-id", model: "current", total_tokens: 300}]);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 1, tokens: 300 });
  });

  it("backfills existing stable-key revision watermarks idempotently through migration 0010", async () => {
    const payloads = await python(["generate"], [
      { observed_at: observed(3), hours: [[hour(day, 10), 300], [hour(day, 11), 200]] },
      { observed_at: observed(1), hours: [[hour(day, 10), 100]] },
    ]);
    await post(payloads[0]);
    await db.prepare("DROP TABLE usage_fact_revisions").run();
    const migration = await readFile(path.join(repoRoot, "cloudflare/migrations/0010_fact_revisions.sql"), "utf8");
    await applySqlText(db, migration);
    await applySqlText(db, migration);
    expect((await db.prepare("SELECT observed_at FROM usage_fact_revisions").all()).results).toEqual([{observed_at: observed(3)}, {observed_at: observed(3)}]);
    await post(payloads[1]);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 2, tokens: 500 });
  });

  it("rolls back the revision watermark together with a failed fact write, then accepts the retry", async () => {
    const payloads = await python(["generate"], [
      { observed_at: observed(0), hours: [[hour(day, 10), 100]] },
      { observed_at: observed(4), hours: [[hour(day, 10), 999]] },
    ]);
    await post(payloads[0]);
    await db.prepare("CREATE TRIGGER fail_fact_write BEFORE UPDATE ON usage_hourly_facts WHEN NEW.total_tokens = 999 BEGIN SELECT RAISE(ABORT, 'controlled fact write failure'); END").run();
    const failed = await mf.dispatchFetch("http://native.test/ingest", {
      method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(payloads[1]),
    });
    expect(failed.status).toBe(500);
    await failed.text();
    expect((await db.prepare("SELECT observed_at FROM usage_fact_revisions").all()).results).toEqual([{observed_at: observed(0)}]);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 1, tokens: 100 });
    await db.prepare("DROP TRIGGER fail_fact_write").run();
    await post(payloads[1]);
    expect((await db.prepare("SELECT observed_at FROM usage_fact_revisions").all()).results).toEqual([{observed_at: observed(4)}]);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 1, tokens: 999 });
  });

  it("keeps newer per-key revisions safe from stale reconciliation when source health is rebuilt", async () => {
    const collector = scan(hour(day, 0), hour("2026-07-13", 0));
    const payloads = await python(["generate"], [
      { observed_at: observed(0), hours: [[hour(day, 10), 100]] },
      { observed_at: observed(6), hours: [[hour(day, 10), 100]] },
      { observed_at: observed(3), hours: [], collector },
      { observed_at: observed(4), hours: [], collector },
    ]);
    await post(payloads[0]);
    await post(payloads[1]);
    // Health is a recoverable projection; its absence must not bypass the canonical revision guard.
    await db.prepare("DELETE FROM source_report_states").run();
    for (const payload of payloads.slice(2)) await post(payload);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 1, tokens: 100 });
    expect((await db.prepare("SELECT observed_at FROM usage_fact_revisions").all()).results).toEqual([{observed_at: observed(6)}]);
    expect((await db.prepare("SELECT accuracy_status FROM source_accuracy").first())?.accuracy_status).toBe("unverified");
    await assertSummary(day, 100);
  });

  it("rechecks fact and scan revisions inside the transaction after a concurrent newer ingest", async () => {
    const collector = scan(hour(day, 0), hour("2026-07-13", 0));
    const payloads = await python(["generate"], [
      { observed_at: observed(0), hours: [[hour(day, 10), 100]], models: [{model: "current", input_tokens: 100, total_tokens: 100}] },
      { observed_at: observed(3), hours: [], collector },
      { observed_at: observed(4), hours: [], collector },
      { observed_at: observed(6), hours: [[hour(day, 10), 200]], models: [{model: "current", input_tokens: 200, total_tokens: 200}] },
    ]);
    await post(payloads[0]);
    await post(payloads[1]);
    const request = validateIngestPayload(payloads[2]);
    const plans = await buildAccuracyPlans(db, request, observed(4));
    expect(plans).toHaveLength(1);
    expect(plans[0].can_reconcile).toBe(true);
    // Deterministic interleaving at the real planner/transaction boundary.
    await post(payloads[3]);
    await db.batch(accuracyWriteStatements(db, plans, [], observed(4), "retry-device"));
    expect(await totals("usage_hourly_facts")).toEqual({ count: 1, tokens: 200 });
    expect((await db.prepare("SELECT model, total_tokens FROM usage_hourly_models").all()).results).toEqual([{model: "current", total_tokens: 200}]);
    expect((await db.prepare("SELECT observed_at, accuracy_status FROM source_accuracy").first())).toEqual({observed_at: observed(6), accuracy_status: "unknown"});
    await db.batch(accuracyWriteStatements(db, [], [], observed(2), "retry-device"));
    expect((await db.prepare("SELECT observed_at, accuracy_status FROM source_accuracy").first())).toEqual({observed_at: observed(6), accuracy_status: "unknown"});
  });

  it.each(["usage_hourly_rollups", "usage_daily_rollups"])("repairs %s after a refresh failure and keeps the next successful replay write-free", async (table) => {
    const payloads = await python(["generate"], [
      { observed_at: observed(0), hours: [[hour(day, 10), 100]] },
      { observed_at: observed(4), hours: [[hour(day, 10), 200]] },
    ]);
    await post(payloads[0]);
    await db.prepare(`CREATE TRIGGER fail_rollup BEFORE INSERT ON ${table} WHEN NEW.total_tokens = 200 BEGIN SELECT RAISE(ABORT, 'controlled rollup failure'); END`).run();
    try {
      const failed = await mf.dispatchFetch("http://native.test/ingest", {
        method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(payloads[1]),
      });
      expect(failed.status).toBe(500);
      await failed.text();
      expect(await totals("usage_hourly_facts")).toEqual({ count: 1, tokens: 200 });
      expect(await totals(table)).toEqual({ count: 1, tokens: 100 });
      expect(await totals("usage_hourly_rollups")).toEqual({ count: 1, tokens: 100 });
      expect(await totals("usage_daily_rollups")).toEqual({ count: 1, tokens: 100 });
      expect((await db.prepare("SELECT date FROM usage_rollup_dirty_days").all()).results).toEqual([{ date: day }]);
    } finally { await db.prepare("DROP TRIGGER fail_rollup").run(); }
    await post(payloads[1]);
    for (const layer of ["usage_hourly_facts", "usage_hourly_rollups", "usage_daily_rollups"]) {
      expect(await totals(layer), layer).toEqual({ count: 1, tokens: 200 });
    }
    await assertSummary(day, 200);
    await post(payloads[1]);
    expect(lastRowsWritten).toBe(0);
  });

  it("repairs all remaining dates after a later refresh chunk fails", async () => {
    const dates = Array.from({ length: 26 }, (_, index) => `2026-06-${String(index + 1).padStart(2, "0")}`);
    const makeHours = (tokens: number) => dates.flatMap((date) => [[hour(date, 10), tokens], [hour(date, 11), tokens]]);
    const payloads = await python(["generate"], [
      { observed_at: observed(0), hours: makeHours(100) },
      { observed_at: observed(4), hours: makeHours(200) },
    ]);
    expect(payloads[0].usage_hourly_facts).toHaveLength(52);
    // More than one bounded invocation is required to initialize 26 independent days.
    let initializationAttempts = 0;
    for (let attempt = 0; attempt < 3; attempt += 1) {
      initializationAttempts += 1;
      const response = await mf.dispatchFetch("http://native.test/ingest", {
        method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(payloads[0]),
      });
      await response.text();
      if (response.status === 200) break;
      expect(response.status).toBe(500);
      expect((await db.prepare("SELECT count(*) AS n FROM usage_rollup_dirty_days").first())?.n).toBe(6);
      expect(await totals("usage_daily_rollups")).toEqual({ count: 20, tokens: 4000 });
      expect(attempt).toBeLessThan(2);
    }
    expect(initializationAttempts).toBe(2);
    expect(await totals("usage_daily_rollups")).toEqual({ count: 26, tokens: 5200 });
    await db.prepare(`CREATE TRIGGER fail_late_rollup BEFORE INSERT ON usage_hourly_rollups WHEN NEW.bucket_start = '${hour(dates[15], 11)}' AND NEW.total_tokens = 200 BEGIN SELECT RAISE(ABORT, 'controlled late chunk failure'); END`).run();
    try {
      const failed = await mf.dispatchFetch("http://native.test/ingest", {
        method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(payloads[1]),
      });
      expect(failed.status).toBe(500);
      await failed.text();
      expect(await totals("usage_hourly_facts")).toEqual({ count: 52, tokens: 10400 });
      const partial = await totals("usage_hourly_rollups");
      expect(partial.tokens).toBeGreaterThan(5200);
      expect(partial.tokens).toBeLessThan(10400);
    } finally { await db.prepare("DROP TRIGGER fail_late_rollup").run(); }
    await post(payloads[1]);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 52, tokens: 10400 });
    expect(await totals("usage_hourly_rollups")).toEqual({ count: 52, tokens: 10400 });
    expect(await totals("usage_daily_rollups")).toEqual({ count: 26, tokens: 10400 });
    for (const date of [dates[0], dates[25]]) await assertSummary(date, 400);
    await post(payloads[1]);
    expect(lastRowsWritten).toBe(0);
  });

  it("keeps authoritative empty coverage against never-seen older keys after incremental updates", async () => {
    const collector = scan(hour(day, 0), hour("2026-07-13", 0));
    const payloads = await python(["generate"], [
      { observed_at: observed(3), hours: [], collector },
      { observed_at: observed(4), hours: [], collector },
      { observed_at: observed(6), hours: [[hour("2026-07-14", 10), 50]] },
      { observed_at: observed(2), hours: [[hour(day, 11), 900]], models: [{model: "old", total_tokens: 900}] },
      { observed_at: observed(2), hours: [[hour("2026-07-13", 0), 80]] },
      { observed_at: observed(7), hours: [[hour(day, 11), 100]] },
    ]);
    await post(payloads[0]);
    await post(payloads[1]);
    expect((await db.prepare("SELECT accuracy_status FROM source_accuracy").first())?.accuracy_status).toBe("verified");
    expect(await totals("usage_hourly_facts")).toEqual({ count: 0, tokens: 0 });
    await post(payloads[2]);
    expect((await db.prepare("SELECT accuracy_status FROM source_accuracy").first())?.accuracy_status).toBe("unknown");
    await post(payloads[3]);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 1, tokens: 50 });
    expect((await db.prepare("SELECT count(*) AS n FROM usage_hourly_models").first())?.n).toBe(0);
    await assertSummary(day, 0);
    // The exact end is outside the authoritative half-open range.
    await post(payloads[4]);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 2, tokens: 130 });
    // A truly newer observation can correct this range.
    await post(payloads[5]);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 3, tokens: 230 });
    await assertSummary(day, 100);
  });

  it("preserves owner-generated daily-only historical fallback while repairing another source on that day", async () => {
    const operations = await python(["legacy-daily"], [{ date: day, source_id: "legacy-only", tokens: 301 }]);
    expect(operations).toHaveLength(1);
    await db.prepare(operations[0][0]).bind(...operations[0][1]).run();
    expect(await totals("usage_hourly_facts", "legacy-only")).toEqual({ count: 0, tokens: 0 });
    const before = (await db.prepare("SELECT * FROM usage_daily_rollups WHERE source_id = 'legacy-only'").all()).results;
    expect(before).toHaveLength(1);
    const payloads = await python(["generate"], [{ observed_at: observed(0), hours: [[hour(day, 10), 100]] }]);
    await post(payloads[0]);
    expect((await db.prepare("SELECT * FROM usage_daily_rollups WHERE source_id = 'legacy-only'").all()).results).toEqual(before);
    expect(await totals("usage_daily_rollups")).toEqual({ count: 1, tokens: 100 });
  });

  it("marks and rebuilds the Shanghai day when the incoming ISO offset crosses midnight", async () => {
    const payloads = await python(["generate"], [{ observed_at: observed(0), hours: [["2026-07-11T17:00:00+00:00", 100]] }]);
    await db.prepare("CREATE TRIGGER fail_timezone_rollup BEFORE INSERT ON usage_hourly_rollups BEGIN SELECT RAISE(ABORT, 'inspect canonical dirty day'); END").run();
    try {
      const response = await mf.dispatchFetch("http://native.test/ingest", {
        method: "POST", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify(payloads[0]),
      });
      expect(response.status).toBe(500);
      await response.text();
      expect((await db.prepare("SELECT date FROM usage_rollup_dirty_days").all()).results).toEqual([{ date: day }]);
    } finally { await db.prepare("DROP TRIGGER fail_timezone_rollup").run(); }
    await post(payloads[0]);
    expect((await db.prepare("SELECT bucket_start, total_tokens FROM usage_hourly_rollups").all()).results).toEqual([{ bucket_start: hour(day, 1), total_tokens: 100 }]);
    expect((await db.prepare("SELECT date, total_tokens FROM usage_daily_rollups").all()).results).toEqual([{ date: day, total_tokens: 100 }]);
    expect((await db.prepare("SELECT count(*) AS n FROM usage_rollup_dirty_days").first())?.n).toBe(0);
    await assertSummary(day, 100);
  });

  it("clears hourly daily and both summaries after two complete empty scans without clearing other sources", async () => {
    const collector = scan(hour(day, 0), hour("2026-07-13", 0));
    const payloads = await python(["generate"], [
      { observed_at: observed(0), hours: [[hour(day, 10), 100]] },
      { source_id: "unrelated", machine: "other-machine", observed_at: observed(0), hours: [[hour(day, 10), 70]] },
      { observed_at: observed(1), hours: [], collector: { ...collector, scan_complete: false } },
      { observed_at: observed(2), hours: [], collector: { ...collector, scan_complete: false } },
      { observed_at: observed(3), hours: [], collector },
      { observed_at: observed(4), hours: [], collector },
    ]);
    for (const payload of payloads.slice(0, 4)) await post(payload);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 1, tokens: 100 });
    await assertSummary(day, 100);
    await post(payloads[4]);
    expect(await totals("usage_hourly_facts")).toEqual({ count: 1, tokens: 100 });
    await post(payloads[5]);
    for (const table of ["usage_hourly_facts", "usage_hourly_rollups", "usage_daily_rollups"]) {
      expect(await totals(table), table).toEqual({ count: 0, tokens: 0 });
      expect(await totals(table, "unrelated"), table).toEqual({ count: 1, tokens: 70 });
    }
    await assertSummary(day, 0);
    await assertSummary(day, 70, "other-machine");
  });

  it.each([
    ["midday start and midnight exclusive end", hour(day, 12), hour("2026-07-13", 0), [[hour(day, 13), 60]]],
    ["cross-day partial coverage", hour(day, 12), hour("2026-07-13", 12), [[hour(day, 13), 60], [hour("2026-07-13", 1), 80]]],
  ])("rebuilds whole affected days for %s", async (_name, start, end, hours) => {
    const baseHours = [[hour(day, 1), 40], [hour(day, 13), 60], [hour("2026-07-13", 1), 80]];
    const collector = scan(start as string, end as string);
    const payloads = await python(["generate"], [
      { observed_at: observed(0), hours: baseHours },
      { source_id: "unrelated", observed_at: observed(0), hours: [[hour(day, 13), 7]] },
      { agent: "claude", observed_at: observed(0), hours: [[hour(day, 13), 11]] },
      { provenance: "separate-provenance", observed_at: observed(0), hours: [[hour(day, 13), 13]] },
      { observed_at: observed(1), hours, collector }, { observed_at: observed(2), hours, collector },
    ]);
    for (const payload of payloads) await post(payload);
    const facts = (await db.prepare("SELECT window_start, total_tokens FROM usage_hourly_facts").all<{window_start: string; total_tokens: number}>()).results;
    expect(facts).toHaveLength(6);
    const independentlySummed: Record<string, number> = {};
    for (const fact of facts) independentlySummed[fact.window_start.slice(0, 10)] = (independentlySummed[fact.window_start.slice(0, 10)] ?? 0) + fact.total_tokens;
    expect(independentlySummed).toEqual({ "2026-07-12": 131, "2026-07-13": 80 });
    const daily = (await db.prepare("SELECT date, total_tokens FROM usage_daily_rollups").all<{date: string; total_tokens: number}>()).results;
    expect(daily).toHaveLength(5);
    const dailyTotals: Record<string, number> = {};
    for (const row of daily) dailyTotals[row.date] = (dailyTotals[row.date] ?? 0) + row.total_tokens;
    expect(dailyTotals).toEqual(independentlySummed);
    const ownDaily = (await db.prepare("SELECT date, total_tokens FROM usage_daily_rollups WHERE source_id = 'retry-device' AND agent = 'codex' AND provenance = 'mswusage_codex_token_count' ORDER BY date").all()).results;
    expect(ownDaily).toEqual([{date: day, total_tokens: 100}, {date: "2026-07-13", total_tokens: 80}]);
    await assertSummary(day, 131);
    await assertSummary("2026-07-13", 80);
  });
});
