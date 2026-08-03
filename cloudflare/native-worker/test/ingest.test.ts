import { readFile } from "node:fs/promises";
import { mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { Miniflare } from "miniflare";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

type ContractRecord = {
  name: string;
  request: { method: string; path: string; auth: boolean };
  response: {
    status: number;
    content_type: string;
    location: string | null;
    body: unknown;
  };
};

type IngestFixture = {
  timezone: string;
  date: string;
  current_time: string;
  ingest_payloads: Record<string, unknown>[];
  limits_payloads: Record<string, unknown>[];
};

type CollectorPayloadRecord = {
  name: string;
  request: { method: string; path: string; auth: boolean };
  payload: Record<string, unknown>;
};

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const schemaPath = path.join(repoRoot, "cloudflare/migrations/0001_initial_schema.sql");
const sourceReportStatesMigrationPath = path.join(repoRoot, "cloudflare/migrations/0004_source_report_states.sql");
const auditIndexesMigrationPath = path.join(repoRoot, "cloudflare/migrations/0005_audit_retention_indexes.sql");
const workerEntry = path.join(repoRoot, "cloudflare/native-worker/src/index.ts");
const writeModelPath = path.join(repoRoot, "cloudflare/native-worker/src/write-model.ts");
const fixturePath = path.join(repoRoot, "tests/fixtures/native_worker_ingest_payloads.json");
// 采集端（Python `DevicePusher`）真实发出的 /ingest payload。由 owner 模块产出，不是手写的。
// 采集端永远是 Python、服务端是 TS，「采集端 payload ↔ 服务端 ingest」是一条消灭不掉的
// 跨语言 wire contract，只能靠这份 fixture 在 Worker 侧真实回放来治理。
const collectorPayloadFixturePath = path.join(repoRoot, "cloudflare/native-worker/test/collector_payload_fixture.json");
// #78 从采集端摘除的历史字段探针。Python 侧的 `tests/test_collector_payload_contract.py`
// 读**同一份**文件、断言**同一组可观测结果**（不报错 / 不解析 / 不落库），
// 两个实现对「老版本采集端还在发的字段」是否一致，就靠这一对用例。
const legacyDroppedFieldProbePath = path.join(
  repoRoot,
  "cloudflare/native-worker/test/legacy_collector_payload_ccusage_daily_status.json",
);
// #91 从采集端摘除的 ccusage_blocks_report 探针，结构与上面同构（Python 半边同样读它）。
const legacyBlocksProbePath = path.join(
  repoRoot,
  "cloudflare/native-worker/test/legacy_collector_payload_ccusage_blocks_report.json",
);
// fixture 为了确定性把顶层 observed_at 抹成 "<masked>"，直接发会因时间格式非法被拒。
// 只在测试里替换成这个固定的合法时间戳，fixture 文件本身不动。
const collectorObservedAt = "2026-06-05T09:05:00+08:00";
const maskedValue = "<masked>";
const token = "contract-test-token";
// 采集端当前上报的版本号。真值在 Python 侧的 `src/ai_usage_widget/version_contract.py`
// 的 `COLLECTOR_VERSION`，由 fixture 固定下来带到 Worker 侧。
// 常量一升，Python 的防陈旧测试和这里会一起红——正确动作是先重新生成 fixture：
//     PYTHONPATH=src python3 scripts/gen_collector_payload_fixture.py
// 再把这里的期望值改成新版本，而不是放宽断言。
const fixtureCollectorVersion = "0.3.0";

const volatileFields = new Set([
  "accepted_at",
  "generated_at",
  "mtime",
  "path",
  "size_bytes",
  "updated_at",
  "last_seen_at",
]);

describe.sequential("native TS Worker write API parity", () => {
  let mf: Miniflare;
  let fixture: IngestFixture;

  beforeEach(async () => {
    fixture = JSON.parse(await readFile(fixturePath, "utf8")) as IngestFixture;
    mf = await createMiniflare({
      AIUSAGE_NOW: fixture.current_time,
      AIUSAGE_TIMEZONE: fixture.timezone,
    });
    await applySchema(await mf.getD1Database("AIUSAGE_DB"));
  });

  afterEach(async () => {
    await mf.dispose();
  });

  it("writes canonical facts and limits for all cross-platform read variants", async () => {
    await applyAllPayloads(fixture.ingest_payloads, fixture.limits_payloads);
    const counts = await tableCounts();
    expect(counts.limit_windows, "D1 limit_windows must be non-empty after /ingest-limits").toBeGreaterThan(0);

    const records = await readRecords(fixture.date);
    expectSourceHealth(records);
    expectMobileLimitsWindows(records);
    expect(Object.values(totalTokensByRecord(records)).every((total) => total > 0)).toBe(true);
    expect(counts.usage_daily).toBe(0);
    expect(counts.usage_daily_models).toBe(0);
    expect(counts.usage_hourly).toBe(0);
    expect(counts.usage_blocks).toBe(0);
  });

  it("keeps repeated ingest payload batches idempotent without token or source health drift", async () => {
    await applyAllPayloads(fixture.ingest_payloads, fixture.limits_payloads);
    const before = await readRecords(fixture.date);
    const beforeCounts = await tableCounts();
    const beforeTotals = totalTokensByRecord(before);
    const beforeSourceHealth = sourceHealthByRecord(before);

    await applyAllPayloads(fixture.ingest_payloads, fixture.limits_payloads);
    const after = await readRecords(fixture.date);
    const afterCounts = await tableCounts();

    expectSourceHealth(after);
    expect(totalTokensByRecord(after)).toEqual(beforeTotals);
    expect(sourceHealthByRecord(after)).toEqual(beforeSourceHealth);
    expect(after).toEqual(before);
    expect(afterCounts).toEqual(beforeCounts);
  });

  it("maintains hourly and daily display rollups when real hourly facts change", async () => {
    await applyAllPayloads(fixture.ingest_payloads, fixture.limits_payloads);
    const db = await mf.getD1Database("AIUSAGE_DB");
    const hourly = await db.prepare("SELECT count(*) AS count FROM usage_hourly_rollups").first<{ count: number }>();
    const daily = await db.prepare("SELECT count(*) AS count FROM usage_daily_rollups").first<{ count: number }>();
    expect(hourly?.count).toBeGreaterThan(0);
    expect(daily?.count).toBeGreaterThan(0);
  });

  it("keeps legacy usage tables as read-only archives during ingest", async () => {
    const db = await mf.getD1Database("AIUSAGE_DB");
    await db.batch([
      db.prepare(`
        INSERT INTO usage_daily (
          source_id, date, agent, input_tokens, output_tokens, cache_creation_tokens,
          cache_read_tokens, total_tokens, total_cost, first_seen_at, last_seen_at
        ) VALUES ('archive-source', '2026-01-01', 'codex', 1, 2, 3, 4, 10, 0, '2026-01-01', '2026-01-01')
      `),
      db.prepare(`
        INSERT INTO usage_daily_models (
          source_id, date, agent, model_name, input_tokens, output_tokens,
          cache_creation_tokens, cache_read_tokens, total_tokens, cost, first_seen_at, last_seen_at
        ) VALUES ('archive-source', '2026-01-01', 'codex', 'archive-model', 1, 2, 3, 4, 10, 0, '2026-01-01', '2026-01-01')
      `),
      db.prepare(`
        INSERT INTO usage_hourly (
          source_id, hour, agent, input_tokens, output_tokens, cache_creation_tokens,
          cache_read_tokens, total_tokens, total_cost, first_seen_at, last_seen_at
        ) VALUES ('archive-source', '2026-01-01T00:00:00+08:00', 'codex', 1, 2, 3, 4, 10, 0, '2026-01-01', '2026-01-01')
      `),
      db.prepare(`
        INSERT INTO usage_blocks (
          source_id, start_time, end_time, agent, input_tokens, output_tokens,
          cache_creation_tokens, cache_read_tokens, total_tokens, total_cost, first_seen_at, last_seen_at
        ) VALUES ('archive-source', '2026-01-01T00:00:00+08:00', '2026-01-01T01:00:00+08:00', 'codex', 1, 2, 3, 4, 10, 0, '2026-01-01', '2026-01-01')
      `),
    ]);
    const before = await archivedLegacyRows(db);

    await postIngest(fixture.ingest_payloads[0]);

    expect(await archivedLegacyRows(db)).toEqual(before);
  });

  it("keeps the latest source-report decision in a per-source read model", async () => {
    await applyAllPayloads(fixture.ingest_payloads, fixture.limits_payloads);
    const db = await mf.getD1Database("AIUSAGE_DB");
    const sourceId = String(fixture.ingest_payloads[0].source_id);

    const state = await db.prepare(`
      SELECT source_id, collected_at, status
      FROM source_report_states
      WHERE source_id = ?
    `).bind(sourceId).first<{ source_id: string; collected_at: string; status: string }>();

    expect(state).toMatchObject({ source_id: sourceId, status: "ok" });
    expect(state?.collected_at).toBe(String(fixture.ingest_payloads[0].observed_at));
  });

  it("backfills the per-source read model from legacy audit history without changing the latest result", async () => {
    const db = await mf.getD1Database("AIUSAGE_DB");
    await db.prepare(`
      INSERT INTO collection_runs (id, collected_at, timezone, collector_version, status)
      VALUES (7001, '2026-07-01T01:00:00+00:00', 'UTC', 'test', 'ok'),
             (7002, '2026-07-01T02:00:00+00:00', 'UTC', 'test', 'ok'),
             (7003, '2026-07-01T02:00:00+00:00', 'UTC', 'test', 'ok')
    `).run();
    await db.prepare(`
      INSERT INTO source_reports (id, run_id, source_id, report_type, command, status)
      VALUES (7001, 7001, 'legacy-source', 'daily', 'test', 'failed'),
             (7002, 7002, 'legacy-source', 'daily', 'test', 'ok'),
             (7003, 7003, 'legacy-source', 'daily', 'test', 'partial')
    `).run();

    await applySqlText(db, await readFile(sourceReportStatesMigrationPath, "utf8"));
    const state = await db.prepare(`
      SELECT collected_at, status FROM source_report_states WHERE source_id = ?
    `).bind("legacy-source").first<{ collected_at: string; status: string }>();
    const plan = await db.prepare(`
      EXPLAIN QUERY PLAN
      SELECT collected_at FROM source_report_states WHERE source_id = 'legacy-source'
    `).all<{ detail: string }>();

    expect(state).toEqual({ collected_at: "2026-07-01T02:00:00+00:00", status: "partial" });
    expect((plan.results ?? []).map((row) => row.detail).join(" ")).toContain("SEARCH source_report_states");
    expect((plan.results ?? []).map((row) => row.detail).join(" ")).not.toContain("TEMP B-TREE");
  });

  it("reconciles a limits source type change by source provider and window", async () => {
    const base = fixture.limits_payloads[0] as Record<string, any>;
    const window = { ...base.windows[0], source_id: "linux-biai-wang", provider: "claude", window: "week" };
    for (const [sourceType, usedPercent] of [["official_cli", 20], ["oauth_usage_api", 21]] as const) {
      const response = await mf.dispatchFetch("http://native.test/ingest-limits", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          ...base,
          windows: [{ ...window, source_type: sourceType, used_percent: usedPercent, remaining_percent: 100 - usedPercent }],
        }),
      });
      expect(response.status).toBe(200);
    }
    const db = await mf.getD1Database("AIUSAGE_DB");
    const rows = await db.prepare(`
      SELECT source_type, used_percent FROM limit_windows
      WHERE source_id = ? AND provider = ? AND window = ?
    `).bind("linux-biai-wang", "claude", "week").all<{ source_type: string; used_percent: number }>();
    expect(rows.results).toEqual([{ source_type: "oauth_usage_api", used_percent: 21 }]);
  });

  it("does not let an older cross-timezone limits retry overwrite the latest window", async () => {
    const base = fixture.limits_payloads[0] as Record<string, any>;
    const window = { ...base.windows[0], source_id: "linux-biai-wang", provider: "claude", window: "week" };
    for (const [observedAt, sourceType, usedPercent] of [
      ["2026-07-18T03:00:00+00:00", "oauth_usage_api", 21],
      ["2026-07-18T10:00:00+08:00", "official_cli", 20],
    ] as const) {
      const response = await mf.dispatchFetch("http://native.test/ingest-limits", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({
          ...base,
          observed_at: observedAt,
          windows: [{ ...window, observed_at: observedAt, source_type: sourceType, used_percent: usedPercent, remaining_percent: 100 - usedPercent }],
        }),
      });
      expect(response.status).toBe(200);
    }
    const db = await mf.getD1Database("AIUSAGE_DB");
    const row = await db.prepare(`
      SELECT source_type, used_percent, observed_at FROM limit_windows
      WHERE source_id = ? AND provider = ? AND window = ?
    `).bind("linux-biai-wang", "claude", "week").first();
    expect(row).toEqual({
      source_type: "oauth_usage_api",
      used_percent: 21,
      observed_at: "2026-07-18T03:00:00+00:00",
    });
  });

  it("does not let an older success retry clear a newer provider failure", async () => {
    const base = fixture.limits_payloads[0] as Record<string, any>;
    const success = {
      ...base.windows[0], source_id: "linux-biai-wang", provider: "claude", window: "session",
      observed_at: "2026-07-18T10:00:00+08:00", reset_at: "2026-07-18T15:00:00+08:00",
      source_type: "oauth_usage_api", confidence: "observed", status: "ok",
    };
    const failure = {
      ...success, window: "unknown", used_percent: 0, remaining_percent: 0,
      observed_at: "2026-07-18T10:30:00+08:00", reset_at: "2026-07-18T10:30:00+08:00",
      window_duration_minutes: 0, source_type: "provider_runtime", confidence: "missing", status: "provider_failed",
    };
    for (const window of [success, failure, success]) {
      const response = await mf.dispatchFetch("http://native.test/ingest-limits", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ ...base, observed_at: window.observed_at, windows: [window] }),
      });
      expect(response.status).toBe(200);
    }
    const db = await mf.getD1Database("AIUSAGE_DB");
    const rows = await db.prepare(`
      SELECT window, status, observed_at FROM limit_windows
      WHERE source_id = ? AND provider = ? ORDER BY window
    `).bind("linux-biai-wang", "claude").all();
    expect(rows.results).toEqual([
      { window: "session", status: "ok", observed_at: "2026-07-18T10:00:00+08:00" },
      { window: "unknown", status: "provider_failed", observed_at: "2026-07-18T10:30:00+08:00" },
    ]);
  });

  it("recovers source health through HTTP ingest when report tables start empty", async () => {
    await applyAllPayloads(fixture.ingest_payloads, fixture.limits_payloads);
    const expectedRecords = await readRecords(fixture.date);
    await clearSourceHealthTables();

    const prodShapeCounts = await tableCounts();
    expect(prodShapeCounts.collection_runs).toBe(0);
    expect(prodShapeCounts.source_reports).toBe(0);
    expect(prodShapeCounts.source_identities).toBeGreaterThan(0);
    expect(prodShapeCounts.usage_hourly_facts).toBeGreaterThan(0);
    expect(prodShapeCounts.usage_daily).toBe(0);

    const emptyHealth = await recordValue("summary-today-empty-source-health", `/api/summary?date=${fixture.date}&period=today`);
    expect(((emptyHealth.response.body as Record<string, unknown>).source_status as unknown[]).length).toBe(0);

    await applyAllPayloads(fixture.ingest_payloads, fixture.limits_payloads);

    const records = await readRecords(fixture.date);
    expectSourceHealth(records);
    expect(totalTokensByRecord(records)).toEqual(totalTokensByRecord(expectedRecords));

    const restoredCounts = await tableCounts();
    expect(restoredCounts.collection_runs).toBeGreaterThan(0);
    expect(restoredCounts.source_reports).toBeGreaterThan(0);

    await applyAllPayloads(fixture.ingest_payloads, fixture.limits_payloads);
    const repeatedCounts = await tableCounts();
    expect(repeatedCounts.collection_runs).toBe(restoredCounts.collection_runs);
    expect(repeatedCounts.source_reports).toBe(restoredCounts.source_reports);
  });

  it("prunes audit tables older than seven days on the scheduled retention job", async () => {
    const db = await mf.getD1Database("AIUSAGE_DB");
    await db.prepare(`
      INSERT INTO collection_runs (id, collected_at, timezone, collector_version, status)
      VALUES
        (9001, '2026-06-15T02:59:00+00:00', 'Asia/Shanghai', 'test', 'ok'),
        (9002, '2026-06-22T02:59:00+00:00', 'Asia/Shanghai', 'test', 'ok')
    `).run();
    await db.prepare(`
      INSERT INTO source_reports (run_id, source_id, report_type, command, status)
      VALUES
        (9001, 'old-source', 'daily', 'test', 'ok'),
        (9002, 'fresh-source', 'daily', 'test', 'ok')
    `).run();
    await db.prepare(`
      INSERT INTO usage_daily (
        source_id, date, agent, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, total_tokens, total_cost, first_seen_at, last_seen_at
      )
      VALUES (
        'old-source', '2026-06-15', 'claude', 1, 2, 3, 4, 10, 0,
        '2026-06-15T02:59:00+00:00', '2026-06-15T02:59:00+00:00'
      )
    `).run();
    await db.prepare(`
      INSERT INTO usage_hourly_rollups (
        bucket_start, bucket_end, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        attribution_confidence, provenance, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        reasoning_output_tokens, total_tokens, event_count, session_count, fact_count
      ) VALUES
        ('2026-05-01T01:00:00+08:00', '2026-05-01T01:59:59+08:00', 'old-source', 'old', 'alice', 'openai', 'old', 'codex', 'codex', 'observed', 'test', 1, 0, 0, 0, 0, 1, 1, 1, 1),
        ('2026-06-23T01:00:00+08:00', '2026-06-23T01:59:59+08:00', 'fresh-source', 'fresh', 'alice', 'openai', 'fresh', 'codex', 'codex', 'observed', 'test', 1, 0, 0, 0, 0, 1, 1, 1, 1)
    `).run();

    const worker = await mf.getWorker();
    const scheduled = await worker.scheduled({
      cron: "0 3 * * *",
      scheduledTime: new Date("2026-06-24T03:00:00+00:00"),
    });
    expect(scheduled.outcome).toBe("ok");

    expect(await auditRowCount("collection_runs")).toBe(1);
    expect(await auditRowCount("source_reports")).toBe(1);
    const remainingRun = await db.prepare("SELECT collected_at FROM collection_runs").first<{ collected_at: string }>();
    const remainingReport = await db.prepare("SELECT source_id FROM source_reports").first<{ source_id: string }>();
    const usageRows = await db.prepare("SELECT count(*) AS count FROM usage_daily WHERE source_id = ?")
      .bind("old-source").first<{ count: number }>();
    expect(remainingRun?.collected_at).toBe("2026-06-22T02:59:00+00:00");
    expect(remainingReport?.source_id).toBe("fresh-source");
    expect(usageRows?.count).toBe(1);
    const rollups = await db.prepare("SELECT count(*) AS count FROM usage_hourly_rollups").first<{ count: number }>();
    expect(rollups?.count).toBe(1);
  });

  it("uses indexes for the bounded audit-retention lookup", async () => {
    const db = await mf.getD1Database("AIUSAGE_DB");
    await applySqlText(db, await readFile(auditIndexesMigrationPath, "utf8"));
    const runs = await db.prepare(`
      EXPLAIN QUERY PLAN SELECT id FROM collection_runs WHERE collected_at < ?
    `).bind("2026-06-17T03:00:00.000Z").all<{ detail: string }>();
    const reports = await db.prepare(`
      EXPLAIN QUERY PLAN DELETE FROM source_reports WHERE run_id IN (
        SELECT id FROM collection_runs WHERE collected_at < ?
      )
    `).bind("2026-06-17T03:00:00.000Z").all<{ detail: string }>();

    expect((runs.results ?? []).map((row) => row.detail).join(" ")).toContain("SEARCH collection_runs");
    expect((reports.results ?? []).map((row) => row.detail).join(" ")).toContain("SEARCH source_reports");
  });

  it("writes large historical ingest payloads through HTTP without dropping source health", async () => {
    const largePayloads = buildLargeIngestPayloads();

    for (const payload of largePayloads) {
      const rowsWritten = await postIngest(payload);
      expect(rowsWritten).toBeGreaterThan(70);
    }

    const counts = await tableCounts();
    expect(counts.usage_daily).toBe(0);
    expect(counts.usage_daily_models).toBe(0);
    expect(counts.usage_hourly).toBe(0);
    expect(counts.usage_blocks).toBe(0);
    expect(counts.usage_hourly_facts).toBeGreaterThanOrEqual(largePayloads.length * 72);
    expect(counts.collection_runs).toBe(largePayloads.length);
    expect(counts.source_reports).toBe(largePayloads.length);

    const summary = await recordValue("summary-all-large-ingest", "/api/summary?date=2026-06-22&period=all");
    const mobile = await recordValue("mobile-summary-all-large-ingest", "/api/mobile/summary?date=2026-06-22&period=all");
    expectLargeSourceHealth(summary, mobile, largePayloads.map((payload) => String(payload.source_id)));

    const beforeReplayCounts = await tableCounts();
    for (const payload of largePayloads) {
      const rowsWritten = await postIngest(payload);
      expect(rowsWritten).toBe(0);
    }
    expect(await tableCounts()).toEqual(beforeReplayCounts);
    // This high-row HTTP regression case is only useful if write-model keeps remote
    // D1 work batched instead of awaiting one write round trip per normalized row.
  });

  it("guards large ingest and limits writes against per-row remote D1 write awaits", async () => {
    const source = await readFile(writeModelPath, "utf8");
    expect(source).toContain("db.batch(");
    expect(source).not.toMatch(/for \(const item of dailyItems\)\s+rowsWritten \+= await upsertDailyItem/);
    expect(source).not.toMatch(/for \(const item of hourlyItems\)\s+rowsWritten \+= await upsertHourlyItem/);
    expect(source).not.toMatch(/for \(const item of blockItems\)\s+rowsWritten \+= await upsertBlockItem/);
    expect(source).not.toMatch(/for \(const fact of hourlyFacts\)\s+rowsWritten \+= await upsertHourlyFact/);
    expect(source).not.toMatch(/for \(const window of windows\)\s+rowsWritten \+= await upsertLimitWindow/);
  });

  it("leaves archived Codex hourly rows empty and recovers provider_failed limit windows", async () => {
    await applyAllPayloads(fixture.ingest_payloads, fixture.limits_payloads);
    const db = await mf.getD1Database("AIUSAGE_DB");

    const oldCodexHour = await db.prepare(`
      SELECT count(*) AS count
      FROM usage_hourly
      WHERE source_id = ? AND hour = ? AND agent = ?
    `).bind("linux-dev-bob", "2026-06-03T09:00:00+08:00", "codex").first<{ count: number }>();
    const currentCodexHours = await db.prepare(`
      SELECT hour
      FROM usage_hourly
      WHERE source_id = ? AND substr(hour, 1, 10) = ? AND agent = ?
      ORDER BY hour
    `).bind("linux-dev-bob", "2026-06-03", "codex").all<{ hour: string }>();
    const failedProviderRows = await db.prepare(`
      SELECT count(*) AS count
      FROM limit_windows
      WHERE source_id = ? AND provider = ? AND source_type = ? AND status = ?
    `).bind("codex-main", "codex", "provider_runtime", "provider_failed").first<{ count: number }>();

    expect(oldCodexHour?.count).toBe(0);
    expect(currentCodexHours.results ?? []).toEqual([]);
    expect(failedProviderRows?.count).toBe(0);
  });

  it("rejects sensitive ingest and limits fields", async () => {
    const ingestResponse = await mf.dispatchFetch("http://native.test/ingest", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...fixture.ingest_payloads[0],
        metadata: { path: "/Users/alice/.codex/sessions/raw.jsonl" },
      }),
    });
    const limitsResponse = await mf.dispatchFetch("http://native.test/ingest-limits", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ...fixture.limits_payloads[0],
        windows: [{ ...(fixture.limits_payloads[0].windows as Record<string, unknown>[])[0], raw: { token: "nope" } }],
      }),
    });

    expect(ingestResponse.status).toBe(400);
    expect(await ingestResponse.json()).toMatchObject({ status: "error", error_type: "http_schema_invalid" });
    expect(limitsResponse.status).toBe(400);
    expect(await limitsResponse.json()).toMatchObject({ status: "error", error_type: "limit_schema_invalid" });
  });

  it("rejects cached or expired limits pretending to be current", async () => {
    const base = fixture.limits_payloads[0] as Record<string, any>;
    const common = {
      source_id: "claude-main",
      provider: "claude",
      window: "week",
      used_percent: 40,
      remaining_percent: 60,
      window_duration_minutes: 10080,
      observed_at: "2026-08-01T13:20:00+08:00",
      reset_at: "2026-08-08T00:00:00+08:00",
      source_type: "oauth_usage_api",
      confidence: "observed",
      status: "ok",
    };
    const invalidWindows = [
      { ...common, source_type: "active_limits_cache" },
      { ...common, reset_at: "2026-07-31T00:00:00+08:00" },
    ];

    for (const window of invalidWindows) {
      const response = await mf.dispatchFetch("http://native.test/ingest-limits", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
        body: JSON.stringify({ ...base, observed_at: window.observed_at, windows: [window] }),
      });

      expect(response.status).toBe(400);
      expect(await response.json()).toMatchObject({ status: "error", error_type: "limit_schema_invalid" });
    }
  });

  it("requires two complete matching scans before verification and authoritative deletion", async () => {
    const db = await mf.getD1Database("AIUSAGE_DB");
    const fact = (hour: string, total: number) => ({
      fact_id: `codex:codex:linux-test:${hour}:${total}`,
      agent: "codex",
      client: "codex",
      window_start: hour,
      window_end: hour.replace(":00:00+08:00", ":59:59+08:00"),
      usage: { input_tokens: total, output_tokens: 0, cache_creation_tokens: 0, cache_read_tokens: 0, total_tokens: total },
      event_count: 0,
      session_count: 0,
      attribution_confidence: "unconfirmed_local_source",
      provenance: "mswusage_codex_token_count",
    });
    const payload = (
      observedAt: string,
      facts: Record<string, unknown>[],
      collector?: Record<string, unknown>,
      factsDigestOverride?: string,
    ) => ({
      schema_version: 1,
      source_id: "linux-test",
      host: "linux-test",
      machine: "linux-test",
      os_user: "tester",
      platform: "linux",
      timezone: "Asia/Shanghai",
      observed_at: observedAt,
      collection_status: "ok",
      usage_daily: [],
      usage_hourly_facts: facts,
      ...(collector ? { usage_ledger_runs: [{
        agent: "codex",
        provenance: "mswusage_codex_token_count",
        collector,
        facts_digest: factsDigestOverride ?? (facts.length === 1
          ? "d9c627d7edbe00fbc52a01c7fd7354314a398605145c27d4042c730c05875bf6"
          : "16178fac046144750b52d17aee362c8ed3684d8af4d12112cc2f8c5833008f38"),
      }] } : {}),
    });
    const completeCollector = {
      version: "0.1.0",
      parser_schema_version: 2,
      mode: "full-rescan",
      coverage: { start: "2026-07-12T00:00:00+08:00", end: "2026-07-13T00:00:00+08:00" },
      counts: { read_errors: 0, unresolved_mismatch: 0 },
      scan_complete: true,
      report_digest: "reduced-safe-digest",
    };

    await postIngest(payload("2026-07-18T01:00:00+00:00", [
      fact("2026-07-12T08:00:00+08:00", 100),
      fact("2026-07-12T09:00:00+08:00", 200),
    ]));
    await postIngest(payload("2026-07-18T01:00:30+00:00", [
      fact("2026-07-12T08:00:00+08:00", 100),
      fact("2026-07-12T09:00:00+08:00", 200),
    ], completeCollector));
    await postIngest(payload("2026-07-18T01:00:30+00:00", [
      fact("2026-07-12T08:00:00+08:00", 100),
      fact("2026-07-12T09:00:00+08:00", 200),
    ], completeCollector));
    let replayRow = await db.prepare("SELECT accuracy_status, matching_full_scans FROM source_accuracy WHERE source_id = ? AND agent = ?")
      .bind("linux-test", "codex").first<{ accuracy_status: string; matching_full_scans: number }>();
    expect(replayRow).toMatchObject({ accuracy_status: "unverified", matching_full_scans: 1 });
    expect(await factCount(db, "linux-test")).toBe(2);
    await postIngest(payload(
      "2026-07-18T01:00:40+00:00",
      [fact("2026-07-12T08:00:00+08:00", 100)],
      completeCollector,
      "16178fac046144750b52d17aee362c8ed3684d8af4d12112cc2f8c5833008f38",
    ));
    expect(await factCount(db, "linux-test")).toBe(2);
    for (const observedAt of ["2026-07-18T01:01:00+00:00", "2026-07-18T01:02:00+00:00"]) {
      await postIngest(payload(observedAt, [fact("2026-07-12T08:00:00+08:00", 100)], {
        ...completeCollector,
        scan_complete: false,
        counts: { read_errors: 1, unresolved_mismatch: 0 },
      }));
    }

    let row: { accuracy_status: string; matching_full_scans?: number } | null = await db.prepare("SELECT accuracy_status, matching_full_scans FROM source_accuracy WHERE source_id = ? AND agent = ?")
      .bind("linux-test", "codex").first<{ accuracy_status: string; matching_full_scans: number }>();
    expect(row).toMatchObject({ accuracy_status: "unverified" });
    expect(await factCount(db, "linux-test")).toBe(2);

    await postIngest(payload(
      "2026-07-18T01:03:00+00:00",
      [fact("2026-07-12T08:00:00+08:00", 100), fact("2026-07-11T08:00:00+08:00", 999)],
      completeCollector,
      "d9c627d7edbe00fbc52a01c7fd7354314a398605145c27d4042c730c05875bf6",
    ));
    expect(await factCount(db, "linux-test")).toBe(2);
    await postIngest(payload("2026-07-18T01:04:00+00:00", [fact("2026-07-12T08:00:00+08:00", 100)], completeCollector));

    row = await db.prepare("SELECT accuracy_status, matching_full_scans FROM source_accuracy WHERE source_id = ? AND agent = ?")
      .bind("linux-test", "codex").first<{ accuracy_status: string; matching_full_scans: number }>();
    expect(row).toMatchObject({ accuracy_status: "verified", matching_full_scans: 2 });
    expect(await factCount(db, "linux-test")).toBe(1);
    const summaryResponse = await mf.dispatchFetch("http://native.test/api/summary?date=2026-07-12&period=today", {
      headers: { Authorization: `Bearer ${token}` },
    });
    const summary = await summaryResponse.json() as Record<string, unknown>;
    const status = (summary.source_status as Record<string, unknown>[]).find((item) => item.source_id === "linux-test");
    expect(status?.accuracy).toMatchObject({ status: "verified", collector_version: "0.1.0", matching_full_scans: 2 });

    await postIngest(payload("2026-07-18T01:05:00+00:00", [fact("2026-07-12T08:00:00+08:00", 100)]));
    row = await db.prepare("SELECT accuracy_status FROM source_accuracy WHERE source_id = ? AND agent = ?")
      .bind("linux-test", "codex").first<{ accuracy_status: string }>();
    expect(row?.accuracy_status).toBe("unknown");

    const zeroCollector = { ...completeCollector, report_digest: "zero-safe-digest" };
    const emptyDigest = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945";
    await postIngest(payload("2026-07-18T01:06:00+00:00", [], zeroCollector, emptyDigest));
    await postIngest(payload("2026-07-18T01:07:00+00:00", [], zeroCollector, emptyDigest));
    row = await db.prepare("SELECT accuracy_status FROM source_accuracy WHERE source_id = ? AND agent = ?")
      .bind("linux-test", "codex").first<{ accuracy_status: string }>();
    expect(row?.accuracy_status).toBe("verified");
    expect(await factCount(db, "linux-test")).toBe(0);

    const provenanceSource = "linux-provenance";
    const firstProvenance = payload("2026-07-18T01:08:00+00:00", [], completeCollector, emptyDigest);
    firstProvenance.source_id = provenanceSource;
    await postIngest(firstProvenance);
    const secondProvenance = payload("2026-07-18T01:09:00+00:00", [], completeCollector, emptyDigest);
    secondProvenance.source_id = provenanceSource;
    (secondProvenance.usage_ledger_runs as Record<string, unknown>[])[0].provenance = "different_provenance";
    await postIngest(secondProvenance);
    const provenanceRow = await db.prepare("SELECT accuracy_status, matching_full_scans FROM source_accuracy WHERE source_id = ? AND agent = ?")
      .bind(provenanceSource, "codex").first<{ accuracy_status: string; matching_full_scans: number }>();
    expect(provenanceRow).toMatchObject({ accuracy_status: "unverified", matching_full_scans: 1 });
  });

  it("refreshes the recorded collector version when a stalled source repeats an unchanged report", async () => {
    const db = await mf.getD1Database("AIUSAGE_DB");
    // 持续失败、没有任何新事实的设备：报告内容一字不变，只有采集端自己升级了。
    // 这类设备恰恰最需要在汇聚端看到真实版本。
    const observedAt = "2026-07-18T02:00:00+00:00";
    const payload = (collectorVersion: string) => ({
      schema_version: 1,
      source_id: "linux-stalled",
      host: "linux-stalled",
      machine: "linux-stalled",
      os_user: "tester",
      platform: "linux",
      timezone: "Asia/Shanghai",
      observed_at: observedAt,
      collection_status: "failed",
      error_type: "collector_error",
      error_message: "local usage ledger unavailable",
      usage_daily: [],
      usage_hourly_facts: [],
      collector_release: { collector_version: collectorVersion },
    });

    expect(await postIngest(payload("0.1.0"))).toBeGreaterThan(0);
    // 路径证据：完全相同的重放既不改报告状态也不产生新事实行，写入行数必须是 0。
    // 这一条与采集端版本无关，缺陷修好后依然成立，用来证明下一次上报确实落在
    // 「报告未变 且 rowsWritten == 0」这条分支上，而不是别的分支。
    expect(await postIngest(payload("0.1.0"))).toBe(0);
    expect(await auditRowCount("collection_runs")).toBe(1);

    await postIngest(payload("0.2.0"));

    const latestRun = await db.prepare(
      "SELECT collector_version FROM collection_runs ORDER BY id DESC LIMIT 1",
    ).first<{ collector_version: string | null }>();
    expect(latestRun?.collector_version).toBe("0.2.0");
    // 版本变化必须被识别成报告状态变化后才写，而不是靠无条件写 collection_runs 补上；
    // 无条件写会让上面那条重放断言先失败，也会回归 D1 写入量优化。
    expect(await auditRowCount("collection_runs")).toBe(2);
  });

  it("收下采集端真实发出的完整上报，并把事实、身份与采集端版本都落库", async () => {
    const record = await collectorPayload("ok-full-collection");
    const facts = record.payload.usage_hourly_facts as Record<string, unknown>[];

    const { body, rowsWritten } = await postCollectorPayload(record);

    expect(rowsWritten).toBeGreaterThan(0);
    expect(body).toMatchObject({
      status: "accepted",
      source_id: "fixture-macbook-pro",
      accepted_at: collectorObservedAt,
      facts_accepted: facts.length,
    });
    // collector_release 真的被解析了，而不是被当成未知字段丢掉。
    expect(body.version).toMatchObject({
      state: "current",
      collector_version: fixtureCollectorVersion,
      release_channel: "stable",
      parser_schema_version: 2,
      compatible: true,
    });

    const db = await mf.getD1Database("AIUSAGE_DB");
    const storedFacts = await db.prepare(`
      SELECT agent, client, window_start, window_end, timezone, machine_id, os_user,
             ai_provider, ai_account_id, input_tokens, output_tokens, cache_creation_tokens,
             cache_read_tokens, reasoning_output_tokens, total_tokens, event_count, session_count,
             attribution_confidence, provenance
      FROM usage_hourly_facts WHERE source_id = ? ORDER BY agent, window_start
    `).bind("fixture-macbook-pro").all<Record<string, unknown>>();
    expect(storedFacts.results).toEqual([
      {
        agent: "claude", client: "claude",
        window_start: "2026-06-04T09:00:00+08:00", window_end: "2026-06-04T10:00:00+08:00",
        timezone: "Asia/Shanghai", machine_id: "macbook-pro", os_user: "wangzhipeng",
        ai_provider: "claude", ai_account_id: "unconfirmed_local_source:fixture-macbook-pro:claude",
        input_tokens: 1000, output_tokens: 300, cache_creation_tokens: 90, cache_read_tokens: 4000,
        reasoning_output_tokens: 0, total_tokens: 5390, event_count: 20, session_count: 3,
        attribution_confidence: "unconfirmed_local_source", provenance: "mswusage_claude_assistant_usage",
      },
      {
        agent: "codex", client: "codex",
        window_start: "2026-06-04T09:00:00+08:00", window_end: "2026-06-04T10:00:00+08:00",
        timezone: "Asia/Shanghai", machine_id: "macbook-pro", os_user: "wangzhipeng",
        ai_provider: "openai", ai_account_id: "openai:fixture-work",
        input_tokens: 600, output_tokens: 180, cache_creation_tokens: 0, cache_read_tokens: 900,
        reasoning_output_tokens: 60, total_tokens: 1680, event_count: 12, session_count: 2,
        attribution_confidence: "account_confirmed", provenance: "mswusage_codex_token_count",
      },
      {
        agent: "codex", client: "codex",
        window_start: "2026-06-04T10:00:00+08:00", window_end: "2026-06-04T11:00:00+08:00",
        timezone: "Asia/Shanghai", machine_id: "macbook-pro", os_user: "wangzhipeng",
        ai_provider: "openai", ai_account_id: "openai:fixture-work",
        input_tokens: 200, output_tokens: 80, cache_creation_tokens: 0, cache_read_tokens: 600,
        reasoning_output_tokens: 20, total_tokens: 880, event_count: 5, session_count: 1,
        attribution_confidence: "account_confirmed", provenance: "mswusage_codex_token_count",
      },
    ]);

    // 身份：source_id / machine / os_user 三层都必须落库，否则读模型无法按设备和账户归属。
    const identity = await db.prepare(`
      SELECT source_id, host, machine, os_user, platform FROM source_identities WHERE source_id = ?
    `).bind("fixture-macbook-pro").first();
    expect(identity).toEqual({
      source_id: "fixture-macbook-pro", host: "macbook-pro.local", machine: "macbook-pro",
      os_user: "wangzhipeng", platform: "darwin",
    });
    const machine = await db.prepare(`
      SELECT machine_id, machine_name, host, platform FROM machines WHERE machine_id = ?
    `).bind("macbook-pro").first();
    expect(machine).toEqual({
      machine_id: "macbook-pro", machine_name: "macbook-pro", host: "macbook-pro.local", platform: "darwin",
    });
    const osIdentity = await db.prepare(`
      SELECT display_name FROM os_identities WHERE machine_id = ? AND os_user = ?
    `).bind("macbook-pro", "wangzhipeng").first<{ display_name: string }>();
    expect(osIdentity?.display_name).toBe("macbook-pro · wangzhipeng");

    // collector_release.collector_version 必须同时落进审计运行和来源健康读模型。
    const run = await db.prepare(`
      SELECT collected_at, timezone, collector_version, status FROM collection_runs ORDER BY id DESC LIMIT 1
    `).first();
    expect(run).toEqual({
      collected_at: collectorObservedAt, timezone: "Asia/Shanghai", collector_version: fixtureCollectorVersion, status: "ok",
    });
    const state = await db.prepare(`
      SELECT collected_at, status, collector_version, first_period, last_period, error_type, error_message
      FROM source_report_states WHERE source_id = ?
    `).bind("fixture-macbook-pro").first();
    expect(state).toEqual({
      collected_at: collectorObservedAt, status: "ok", collector_version: fixtureCollectorVersion,
      first_period: "2026-06-04", last_period: "2026-06-04", error_type: null, error_message: null,
    });

    // usage_ledger_runs 也必须被消费成账本运行，而不是静默丢掉。
    const accuracy = await db.prepare(`
      SELECT agent, provenance, mode, coverage_start, coverage_end, facts_digest, accuracy_status
      FROM source_accuracy WHERE source_id = ? ORDER BY agent
    `).bind("fixture-macbook-pro").all<Record<string, unknown>>();
    expect(accuracy.results).toEqual([
      {
        agent: "claude", provenance: "mswusage_claude_assistant_usage", mode: "incremental",
        coverage_start: "2026-06-04T00:00:00+08:00", coverage_end: "2026-06-05T00:00:00+08:00",
        facts_digest: "5d3444e95c979d26868d49f56c9912c64e9aaf617dd963ff0c21b35295af2afc",
        accuracy_status: "unverified",
      },
      {
        agent: "codex", provenance: "mswusage_codex_token_count", mode: "incremental",
        coverage_start: "2026-06-04T00:00:00+08:00", coverage_end: "2026-06-05T00:00:00+08:00",
        facts_digest: "54f9b145479f49ca63799f64f57de4b08358c73565d4819e480db2f4176072bc",
        accuracy_status: "unverified",
      },
    ]);

    // ccusage_* 报告只是来源材料，不得回流进 legacy 归档表。
    const counts = await tableCounts();
    expect(counts.usage_daily).toBe(0);
    expect(counts.usage_daily_models).toBe(0);
    expect(counts.usage_hourly).toBe(0);
    expect(counts.usage_blocks).toBe(0);
  });

  it("收下采集端上报的采集失败 payload，并把失败原因记进来源健康", async () => {
    const record = await collectorPayload("error-ccusage-missing-tool");
    expect(record.payload.usage_daily, "该场景的 usage_daily 必须为空").toEqual([]);

    const { body, rowsWritten } = await postCollectorPayload(record);

    // usage_daily 为空不等于报错：采集失败也必须被服务端收下并记录，否则设备会「静默消失」。
    expect(rowsWritten).toBeGreaterThan(0);
    expect(body).toMatchObject({
      status: "accepted",
      source_id: "fixture-linux-dev",
      accepted_at: collectorObservedAt,
      facts_accepted: 0,
    });
    expect(body.version).toMatchObject({ state: "current", collector_version: fixtureCollectorVersion, release_channel: "beta" });

    const db = await mf.getD1Database("AIUSAGE_DB");
    const state = await db.prepare(`
      SELECT collected_at, status, collector_version, first_period, last_period, error_type, error_message
      FROM source_report_states WHERE source_id = ?
    `).bind("fixture-linux-dev").first();
    expect(state).toEqual({
      collected_at: collectorObservedAt,
      status: "missing_tool",
      collector_version: fixtureCollectorVersion,
      first_period: null,
      last_period: null,
      error_type: "missing_tool",
      error_message: "[Errno 2] No such file or directory: 'ccusage'",
    });
    const report = await db.prepare(`
      SELECT status, error_type, error_message FROM source_reports WHERE source_id = ?
    `).bind("fixture-linux-dev").first();
    expect(report).toEqual({
      status: "missing_tool",
      error_type: "missing_tool",
      error_message: "[Errno 2] No such file or directory: 'ccusage'",
    });

    const identity = await db.prepare(`
      SELECT source_id, host, machine, os_user, platform FROM source_identities WHERE source_id = ?
    `).bind("fixture-linux-dev").first();
    expect(identity).toEqual({
      source_id: "fixture-linux-dev", host: "linux-dev.internal", machine: "linux-dev",
      os_user: "wangzp", platform: "linux",
    });

    const counts = await tableCounts();
    expect(counts.usage_hourly_facts).toBe(0);
    expect(counts.usage_daily).toBe(0);
    expect(counts.collection_runs).toBe(1);
  });

  it("ccusage 挂了但账本仍可用时，账本用量照常落库；ccusage 的失败原因不再有承载字段", async () => {
    const record = await collectorPayload("partial-ccusage-missing-tool-ledger-ok");
    expect(record.payload.usage_daily, "该场景 ccusage 没跑起来，usage_daily 必须为空").toEqual([]);
    expect(record.payload.ccusage_daily_report, "ccusage 没跑起来就不该有报告").toBeUndefined();

    const { body } = await postCollectorPayload(record);
    expect(body).toMatchObject({
      status: "accepted",
      source_id: "fixture-desktop-partial",
      accepted_at: collectorObservedAt,
      facts_accepted: 3,
    });

    const db = await mf.getD1Database("AIUSAGE_DB");
    // 关键不变量：ccusage 挂掉不许连带丢掉账本采到的真实用量。
    const facts = await db.prepare(`
      SELECT agent, window_start, total_tokens FROM usage_hourly_facts WHERE source_id = ? ORDER BY agent, window_start
    `).bind("fixture-desktop-partial").all<Record<string, unknown>>();
    expect(facts.results).toEqual([
      { agent: "claude", window_start: "2026-06-04T09:00:00+08:00", total_tokens: 5390 },
      { agent: "codex", window_start: "2026-06-04T09:00:00+08:00", total_tokens: 1680 },
      { agent: "codex", window_start: "2026-06-04T10:00:00+08:00", total_tokens: 880 },
    ]);

    // #78 的**已知代价**，在生产实现上钉死：这条路径的来源健康是 ok 且没有任何错误信息，
    // 所以「ccusage 在这台设备上装挂了」不会被任何人看见。此前由 ccusage_daily_status
    // 携带，但那个字段在这里从来就没被解析过——摘除只是让代价变得诚实，不是新造出来的。
    // 哪天补了两侧都实现的替代承载字段，这条会红，届时必须显式复核。
    const state = await db.prepare(`
      SELECT status, first_period, last_period, error_type, error_message
      FROM source_report_states WHERE source_id = ?
    `).bind("fixture-desktop-partial").first();
    expect(state).toEqual({
      status: "ok",
      // 周期取自账本小时事实（不是 usage_daily）——ccusage 挂了也仍有覆盖周期。
      first_period: "2026-06-04",
      last_period: "2026-06-04",
      error_type: null,
      error_message: null,
    });
  });

  it("老版本采集端仍在发的 ccusage_daily_status 被当未知字段忽略：不报错、不落库", async () => {
    // 跨实现一致性的 Worker 半边。Python 半边是
    // `tests/test_collector_payload_contract.py::TestDroppedLegacyFieldIsIgnoredByBothImplementations`，
    // 读的是同一份探针文件、断言同一组可观测结果。
    //
    // 证明方式不是「返回了 200 就算忽略」——那太弱：字段完全可能被解析后写进某张表。
    // 这里比对的是**同一份 payload 加不加这个字段，D1 的可观测结果是否逐行相等**。
    const probe = JSON.parse(await readFile(legacyDroppedFieldProbePath, "utf8")) as {
      field: string;
      scenario: string;
      value: unknown;
      bypass_values: unknown[];
    };
    const clean = await collectorPayload(probe.scenario);
    expect(clean.payload[probe.field], "基座 payload 不该已经带着这个历史字段").toBeUndefined();

    const { body: cleanBody } = await postCollectorPayload(clean);
    const cleanState = await readLegacyProbeState();

    // 每一个形状都要过，不只老采集端正常发出的那个：Worker 对未知顶层字段是「无论什么
    // 形状都忽略」，只覆盖正面形状的话，Python 侧把当年那个必填校验加回来照样绿。
    const shapes = [probe.value, ...probe.bypass_values];
    expect(shapes.length, "绕过形状清单不能为空，否则只覆盖了正面路径").toBeGreaterThan(1);

    for (const shape of shapes) {
      const legacy: CollectorPayloadRecord = {
        ...clean,
        payload: { ...clean.payload, [probe.field]: shape },
      };
      // 探针不能是空的，否则下面几条比对什么都没验证。
      expect(Object.keys(legacy.payload)).toContain(probe.field);

      // 1. 不报错：postCollectorPayload 内部已断言 200，非 2xx 会在这里直接失败。
      const { body: legacyBody } = await postCollectorPayload(legacy);

      // 2. 响应完全一致：字段没有影响任何计数或版本判定。
      expect(legacyBody, `形状 ${JSON.stringify(shape)} 改变了响应`).toEqual(cleanBody);

      // 3. 不落库：库里的可观测结果逐行相等，字段内容一个字都没进 D1。
      expect(await readLegacyProbeState(), `形状 ${JSON.stringify(shape)} 改变了落库结果`).toEqual(cleanState);
    }

    // 4. 字段的内容不许以任何形式出现在来源健康里（上面那条已覆盖，这条写明口径）。
    const db = await mf.getD1Database("AIUSAGE_DB");
    const state = await db.prepare(`
      SELECT error_type, error_message FROM source_report_states WHERE source_id = ?
    `).bind(clean.payload.source_id as string).first();
    expect(state).toEqual({ error_type: null, error_message: null });
  });

  it("老版本采集端仍在发的 ccusage_blocks_report 被当未知字段忽略：不报错、不解析、不落库", async () => {
    // #91 停采 blocks 后的跨实现一致性，Worker 半边。Python 半边是
    // `tests/test_collector_payload_contract.py::TestDroppedLegacyFieldIsIgnoredByBothImplementations`，
    // 读的是同一份探针文件、断言同一组可观测结果。结构与上面 #78 那条同构，
    // 区别只在场景：blocks 子进程只有 ccusage daily 成功后才会跑，所以探针钉在 ok 场景。
    const probe = JSON.parse(await readFile(legacyBlocksProbePath, "utf8")) as {
      field: string;
      scenario: string;
      value: unknown;
      bypass_values: unknown[];
    };
    expect(probe.field).toBe("ccusage_blocks_report");
    expect(probe.scenario).toBe("ok-full-collection");

    // 「不解析」的静态半边：字段不得出现在 IngestRequest 的声明里——声明了就等于
    // validateIngestPayload 会把它取出来，那不是「未知字段忽略」。
    // 对照组（防恒真）：同一套提取机制必须仍能看到邻位字段 ccusage_session_report，
    // 证明「看不到 blocks」是因为它真的不在声明里，不是提取正则失灵。
    const contract = await ingestRequestFieldContract();
    expect(contract.declared).toContain("ccusage_session_report");
    expect(
      contract.declared,
      "ccusage_blocks_report 重新出现在 Worker 的 IngestRequest 声明里——#91 已把它摘出「已声明解析」清单，它必须走未知字段忽略路径",
    ).not.toContain(probe.field);

    const clean = await collectorPayload(probe.scenario);
    expect(clean.payload[probe.field], "基座 payload 不该已经带着这个历史字段").toBeUndefined();

    const { body: cleanBody } = await postCollectorPayload(clean);
    const cleanState = await readLegacyProbeState();
    // 结构下限：ok 场景必须真的写入了账本事实，否则「逐行相等」比的是两个空库。
    expect((cleanState.facts as unknown[]).length).toBeGreaterThan(0);

    // 每一个形状都要过，不只老采集端正常发出的那个。非 object 形状正是 #91 删掉的
    // isRecord 校验当年会以 400 拒收的——校验被加回来时只有它们会露馅。
    const shapes = [probe.value, ...probe.bypass_values];
    expect(shapes.length, "绕过形状清单不能为空，否则只覆盖了正面路径").toBeGreaterThan(1);

    for (const shape of shapes) {
      const legacy: CollectorPayloadRecord = {
        ...clean,
        payload: { ...clean.payload, [probe.field]: shape },
      };
      expect(Object.keys(legacy.payload)).toContain(probe.field);

      // 1. 不报错：postCollectorPayload 内部已断言 200，非 2xx 会在这里直接失败。
      const { body: legacyBody } = await postCollectorPayload(legacy);

      // 2. 响应完全一致：字段没有影响任何计数或版本判定。
      expect(legacyBody, `形状 ${JSON.stringify(shape)} 改变了响应`).toEqual(cleanBody);

      // 3. 不落库：库里的可观测结果逐行相等。
      expect(await readLegacyProbeState(), `形状 ${JSON.stringify(shape)} 改变了落库结果`).toEqual(cleanState);
    }

    // 4. usage_blocks 表为空。据实说明这条的强度：write-model.ts 从来就没有写入
    //    usage_blocks 的代码路径，所以它对本次摘除是恒真的，单独不构成证据；
    //    真正会红的守卫是上面的 declared 断言（重新声明即红）与形状回放（恢复
    //    isRecord 校验即 400 红）。留着它只为把「该表是只读归档」的口径写成可执行的。
    const counts = await tableCounts();
    expect(counts.usage_blocks).toBe(0);
  });

  it("采集端发出的每个顶层字段都必须是 Worker 已声明并解析的 ingest 字段", async () => {
    // 覆盖范围（据实写，别把它读成更大的保证）：
    //   覆盖：字段压根不在 `type IngestRequest` 里 —— validateIngestPayload 既不报错也不解析，
    //         采集端发了、服务端 200 收了、字段消失，两端都没有信号。
    //   **这条断言已经抓到过一次真实 bug**：ccusage_daily_status（pusher 会发、Python 服务端
    //         校验、Worker 全文零命中，见 #78）。它只在「ccusage 挂了而 ledger 仍可用」时出现，
    //         而 fixture 原先只有成功与全失败两个场景，都不触发，所以这条断言碰不到它。
    //         #78 补上了 partial-ccusage-missing-tool-ledger-ok 这个场景，本用例当场变红，
    //         随后 PM 拍板把该字段从采集端摘除（不补进 Worker），现在重新变绿。
    //         教训：这条断言的覆盖力受限于 fixture 的**场景覆盖**，场景缺一条它就有一个盲区。
    //   覆盖：声明了却不从 payload 里取（declared 与 parsed 不相等）。
    //   **不覆盖**：已声明、已解析、但下游零消费。此刻就有两个字段处在这个状态——
    //         ccusage_session_report / codex_hourly_status 在 write-model.ts 里除类型声明
    //         与 return 外没有任何持久化消费方，而这条用例是绿的（第三个同状态的
    //         ccusage_blocks_report 已由 #91 从两侧摘除，走未知字段忽略路径）。
    //         所以本用例证明的是「Worker 认识这个字段」，不是「这个字段最终被用上了」。
    //   为什么不补：要覆盖它得做「字段是否被下游消费」的静态检查，而字段可以经由解构、
    //         别名、整体透传等形式被消费，静态检查会大量误报，很快会被当噪音关掉——
    //         那就制造了一个新的假门禁。这条缺口应当靠**针对具体字段的落库断言**来补
    //         （本文件上面那两条真实回放用例就是这么做的），不靠这里的正则。
    const contract = await ingestRequestFieldContract();
    expect(contract.declared, "write-model.ts 的 IngestRequest 声明解析失败").toContain("usage_hourly_facts");
    expect(contract.declared.length, "解析出的已知字段数量异常，正则很可能没匹配到真正的声明").toBeGreaterThan(10);
    // 声明了却不从 payload 里取同样等于静默丢弃，所以两个集合必须逐字相等。
    expect([...contract.parsed].sort()).toEqual([...contract.declared].sort());

    const records = await readCollectorPayloads();
    // fixture 新增场景时必须同时补 Worker 侧回放，不允许只加 fixture 不加覆盖。
    expect(records.map((item) => item.name).sort()).toEqual([
      "error-ccusage-missing-tool",
      "ok-full-collection",
      "partial-ccusage-missing-tool-ledger-ok",
    ]);
    for (const record of records) {
      // fixture 的 request 块由 Python 侧从 pusher 真正发出的那次请求推导（path 取自实际
      // POST 的 URL，auth 取自实际 headers 有没有 Authorization），不是手写的常量，
      // 所以这条 toEqual 是在核对采集端的真实上报形态，而不是两处字面量互相比对。
      expect(record.request, record.name).toEqual({ method: "POST", path: "/ingest", auth: true });
      const unknownFields = Object.keys(record.payload).filter((key) => !contract.declared.includes(key));
      expect(
        unknownFields,
        `${record.name}: 采集端发出的顶层字段没出现在 Worker 的 IngestRequest 声明里，会被静默丢弃`,
      ).toEqual([]);
    }
  });

  /** 历史字段探针的落库快照：只取「这个字段真要是被解析了就会变」的那些表。 */
  async function readLegacyProbeState(): Promise<Record<string, unknown[]>> {
    const db = await mf.getD1Database("AIUSAGE_DB");
    const read = async (sql: string): Promise<unknown[]> =>
      (await db.prepare(sql).all<Record<string, unknown>>()).results;
    return {
      facts: await read(`
        SELECT source_id, agent, window_start, total_tokens, provenance, attribution_confidence
        FROM usage_hourly_facts ORDER BY source_id, agent, window_start
      `),
      reportStates: await read(`
        SELECT source_id, collected_at, status, collector_version, first_period, last_period, error_type, error_message
        FROM source_report_states ORDER BY source_id
      `),
      // source_reports 是**追加**表：同一份 payload 上报两次会留两行，所以这里取 DISTINCT。
      // 只要历史字段真被解析进 error_type / error_message，第二次上报就会产生一个**不同**的
      // 内容行，DISTINCT 收不掉，比对照样红——去重去掉的只是「上报次数」，不是「内容差异」。
      reports: await read("SELECT DISTINCT source_id, status, error_type, error_message FROM source_reports ORDER BY source_id"),
      accuracy: await read("SELECT source_id, agent, provenance, facts_digest, accuracy_status FROM source_accuracy ORDER BY source_id, agent"),
      identities: await read("SELECT source_id, host, machine, os_user, platform FROM source_identities ORDER BY source_id"),
      // #91：blocks 快照的天然落点。字段真被重新解析并持久化，第一个变的就是这张表。
      usageBlocks: await read("SELECT source_id, start_time, end_time, agent, total_tokens FROM usage_blocks ORDER BY source_id, start_time"),
    };
  }

  async function collectorPayload(name: string): Promise<CollectorPayloadRecord> {
    const record = (await readCollectorPayloads()).find((item) => item.name === name);
    expect(record, `采集端 payload fixture 必须仍然包含场景 ${name}`).toBeDefined();
    return record as CollectorPayloadRecord;
  }

  /**
   * 按 fixture 记录的 `request` 块真实回放一次采集端上报。
   *
   * method / path / auth 都**取自 fixture**，而 fixture 那一块是 Python 侧从 pusher 真正
   * 发出的那次请求推导出来的（`tests/test_collector_payload_contract.py` 的
   * `_request_descriptor`：path 来自实际 POST 的 URL，auth 来自实际 headers 里有没有
   * Authorization）。所以这里不是「两处字面量互相比对」：采集端哪天改了上报路径、或不再
   * 带认证，重新生成 fixture 后这里会真的打到别的 path / 不带 Authorization，
   * 拿到 404 / 401 而变红。
   */
  async function postCollectorPayload(
    record: CollectorPayloadRecord,
  ): Promise<{ body: Record<string, unknown>; rowsWritten: number }> {
    const response = await mf.dispatchFetch(`http://native.test${record.request.path}`, {
      method: record.request.method,
      headers: {
        ...(record.request.auth ? { Authorization: `Bearer ${token}` } : {}),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(record.payload),
    });
    const text = await response.text();
    // 采集端真实产出的 payload，生产服务端必须收得下；任何 4xx/5xx 都等于这条 wire contract 破了。
    expect(response.status, `采集端 payload 未被接受: ${response.status} ${text}`).toBe(200);
    return {
      body: JSON.parse(text) as Record<string, unknown>,
      rowsWritten: Number(response.headers.get("X-AIUsage-Rows-Written") ?? "NaN"),
    };
  }

  async function applyAllPayloads(
    ingestPayloads: Record<string, unknown>[],
    limitsPayloads: Record<string, unknown>[],
  ): Promise<number> {
    let changedRows = 0;
    for (const payload of ingestPayloads) changedRows += await postIngest(payload);
    for (const payload of limitsPayloads) changedRows += await postLimits(payload);
    return changedRows;
  }

  async function postIngest(payload: Record<string, unknown>): Promise<number> {
    const response = await mf.dispatchFetch("http://native.test/ingest", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    expect(response.status).toBe(200);
    return Number(response.headers.get("X-AIUsage-Rows-Written") ?? "NaN");
  }

  async function postLimits(payload: Record<string, unknown>): Promise<number> {
    const response = await mf.dispatchFetch("http://native.test/ingest-limits", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    expect(response.status).toBe(200);
    return Number(response.headers.get("X-AIUsage-Rows-Written") ?? "NaN");
  }

  async function readRecords(date: string): Promise<ContractRecord[]> {
    const records: ContractRecord[] = [];
    for (const period of ["today", "week", "month", "all"]) {
      records.push(await recordValue(`summary-${period}`, `/api/summary?date=${date}&period=${period}`));
      records.push(await recordValue(`mobile-summary-${period}`, `/api/mobile/summary?date=${date}&period=${period}`));
    }
    records.push(await recordValue("summary-week-machine-filter", `/api/summary?date=${date}&period=week&machine=macbook-pro`));
    records.push(await recordValue("mobile-summary-week-machine-filter", `/api/mobile/summary?date=${date}&period=week&machine=linux-dev`));
    records.push(await recordValue("summary-week-account-filter", `/api/summary?date=${date}&period=week&account=alice`));
    records.push(await recordValue("mobile-summary-week-account-filter", `/api/mobile/summary?date=${date}&period=week&account=bob`));
    return records;
  }

  async function recordValue(name: string, requestPath: string): Promise<ContractRecord> {
    const response = await mf.dispatchFetch(`http://native.test${requestPath}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const contentType = response.headers.get("Content-Type") ?? "";
    const body = await response.arrayBuffer();
    return {
      name,
      request: {
        method: "GET",
        path: requestPath,
        auth: true,
      },
      response: {
        status: response.status,
        content_type: contentType.split(";")[0],
        location: response.headers.get("Location"),
        body: maskVolatile(JSON.parse(Buffer.from(body).toString("utf8"))),
      },
    };
  }

  async function tableCounts(): Promise<Record<string, number>> {
    const db = await mf.getD1Database("AIUSAGE_DB");
    const tables = [
      "collection_runs",
      "source_reports",
      "usage_daily",
      "usage_daily_models",
      "usage_hourly",
      "usage_blocks",
      "source_identities",
      "machines",
      "os_identities",
      "ai_accounts",
      "usage_hourly_facts",
      "usage_hourly_models",
      "source_accuracy",
      "limit_windows",
    ];
    const counts: Record<string, number> = {};
    for (const table of tables) {
      const row = await db.prepare(`SELECT count(*) AS count FROM ${table}`).first<{ count: number }>();
      counts[table] = Number(row?.count ?? 0);
    }
    return counts;
  }

  async function archivedLegacyRows(db: D1Database): Promise<Record<string, unknown[]>> {
    const rows: Record<string, unknown[]> = {};
    for (const table of ["usage_daily", "usage_daily_models", "usage_hourly", "usage_blocks"]) {
      const result = await db.prepare(`SELECT * FROM ${table} ORDER BY 1, 2, 3, 4`).all();
      rows[table] = result.results ?? [];
    }
    return rows;
  }

  async function clearSourceHealthTables(): Promise<void> {
    const db = await mf.getD1Database("AIUSAGE_DB");
    await db.prepare("DELETE FROM source_report_states").run();
    await db.prepare("DELETE FROM source_reports").run();
    await db.prepare("DELETE FROM collection_runs").run();
  }

  async function auditRowCount(table: "collection_runs" | "source_reports"): Promise<number> {
    const db = await mf.getD1Database("AIUSAGE_DB");
    const row = await db.prepare(`SELECT count(*) AS count FROM ${table}`).first<{ count: number }>();
    return Number(row?.count ?? 0);
  }

  async function factCount(db: D1Database, sourceId: string): Promise<number> {
    const row = await db.prepare("SELECT count(*) AS count FROM usage_hourly_facts WHERE source_id = ?")
      .bind(sourceId).first<{ count: number }>();
    return Number(row?.count ?? 0);
  }
});

/**
 * 读取采集端 payload fixture，并把顶层被掩码的 observed_at 换成固定合法时间戳。
 * 只改内存里的副本，fixture 文件保持原样。
 */
async function readCollectorPayloads(): Promise<CollectorPayloadRecord[]> {
  const records = JSON.parse(await readFile(collectorPayloadFixturePath, "utf8")) as CollectorPayloadRecord[];
  expect(records.length, "采集端 payload fixture 不能为空").toBeGreaterThan(0);
  return records.map((record) => {
    const payload = { ...record.payload };
    if (payload.observed_at === maskedValue) payload.observed_at = collectorObservedAt;
    // fixture 将来多掩码一个字段时，必须在这里显式处理，不能带着 "<masked>" 发给 Worker。
    expect(
      maskedFieldPaths(payload),
      `${record.name}: 出现未处理的掩码字段，测试会把 "<masked>" 原样发给 Worker`,
    ).toEqual([]);
    return { ...record, payload };
  });
}

function maskedFieldPaths(value: unknown, trail = "$"): string[] {
  if (value === maskedValue) return [trail];
  if (Array.isArray(value)) return value.flatMap((item, index) => maskedFieldPaths(item, `${trail}[${index}]`));
  if (value !== null && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .flatMap(([key, item]) => maskedFieldPaths(item, `${trail}.${key}`));
  }
  return [];
}

/**
 * 从 write-model.ts 源码里静态取出 Worker 认识的 ingest 顶层字段：
 * `declared` 是 `type IngestRequest` 的声明，`parsed` 是 `validateIngestPayload` 真正取出的字段。
 */
async function ingestRequestFieldContract(): Promise<{ declared: string[]; parsed: string[] }> {
  const source = await readFile(writeModelPath, "utf8");
  const declaration = source.match(/type IngestRequest = \{([\s\S]*?)\n\};/);
  expect(declaration, "write-model.ts 必须仍然声明 type IngestRequest").not.toBeNull();
  // 先断言锚点存在再 slice：indexOf 找不到会返回 -1，slice(-1) 拿到的是源码最后一个字符，
  // 后续正则必然失配。那样虽然也会红，但红在莫名其妙的地方，排查要绕一圈。
  expect(source, "write-model.ts 必须仍然有 function validateIngestPayload").toContain(
    "function validateIngestPayload",
  );
  const validate = source.slice(source.indexOf("function validateIngestPayload"));
  const returned = validate.match(/\n {2}return \{([\s\S]*?)\n {2}\};/);
  expect(returned, "validateIngestPayload 必须仍然返回一个 IngestRequest 对象字面量").not.toBeNull();
  return {
    declared: Array.from((declaration as RegExpMatchArray)[1].matchAll(/^ {2}(\w+)\??:/gm)).map((match) => match[1]),
    parsed: Array.from((returned as RegExpMatchArray)[1].matchAll(/^ {4}(\w+):/gm)).map((match) => match[1]),
  };
}

async function bundleWorker(): Promise<string> {
  const outdir = path.join(tmpdir(), `aiusage-native-worker-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  await mkdir(outdir, { recursive: true });
  const outfile = path.join(outdir, "index.mjs");
  await build({
    entryPoints: [workerEntry],
    outfile,
    bundle: true,
    format: "esm",
    platform: "browser",
    target: "es2022",
    sourcemap: false,
  });
  return readFile(outfile, "utf8");
}

async function createMiniflare(extraBindings: Record<string, string> = {}): Promise<Miniflare> {
  const bundleScript = await bundleWorker();
  return new Miniflare({
    modules: true,
    script: bundleScript,
    scriptPath: "index.mjs",
    compatibilityDate: "2026-06-21",
    d1Databases: ["AIUSAGE_DB"],
    bindings: {
      AIUSAGE_TOKEN: token,
      AIUSAGE_CACHE_NAMESPACE: crypto.randomUUID(),
      AIUSAGE_DISABLE_SUMMARY_CACHE: "true",
      ...extraBindings,
    },
  });
}

async function applySchema(db: D1Database): Promise<void> {
  await applySqlText(db, await readFile(schemaPath, "utf8"));
  await resetDatabase(db);
}

async function applySqlText(db: D1Database, sqlText: string): Promise<void> {
  const sql = sqlText
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("--"))
    .join("\n");
  for (const statement of sql.split(";")) {
    const trimmed = statement.trim();
    if (trimmed) {
      await db.prepare(trimmed).run();
    }
  }
}

async function resetDatabase(db: D1Database): Promise<void> {
  const tables = [
    "usage_hourly_models",
    "usage_hourly_facts",
    "source_accuracy",
    "ai_accounts",
    "os_identities",
    "machines",
    "limit_windows",
    "source_identities",
    "usage_blocks",
    "usage_hourly",
    "usage_daily_models",
    "usage_daily",
    "source_report_states",
    "source_reports",
    "collection_runs",
  ];
  for (const table of tables) {
    await db.prepare(`DELETE FROM ${table}`).run();
  }
}

function maskVolatile(value: unknown, fieldName = "", parentName = ""): unknown {
  if (volatileFields.has(fieldName) || fieldName.endsWith("_path")) {
    return "<masked>";
  }
  if ((parentName === "source_status" || parentName === "sources") &&
      ["observed_at", "last_observed_at", "last_pushed_at"].includes(fieldName)) {
    return "<masked>";
  }
  if (Array.isArray(value)) {
    return value.map((item) => maskVolatile(item, parentName, fieldName));
  }
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, maskVolatile(item, key, parentName)]),
    );
  }
  return value;
}

function expectSourceHealth(records: ContractRecord[]): void {
  for (const record of records) {
    const body = record.response.body as Record<string, unknown>;
    const filtered = record.request.path.includes("machine=") || record.request.path.includes("account=");
    if (record.name.startsWith("summary-")) {
      const statuses = body.source_status as Array<Record<string, unknown>>;
      expect(Array.isArray(statuses), record.name).toBe(true);
      expect(statuses.length, record.name).toBeGreaterThan(0);
      if (!filtered) {
        expect(statuses.some((row) => row.source_id === "mac-local" && row.status === "ok"), record.name).toBe(true);
        expect(statuses.some((row) => row.source_id === "linux-stale-eve" && row.status === "stale"), record.name).toBe(true);
      }
    }
    if (record.name.startsWith("mobile-summary-")) {
      const sources = body.sources as Array<Record<string, unknown>>;
      expect(Array.isArray(sources), record.name).toBe(true);
      expect(sources.length, record.name).toBeGreaterThan(0);
      if (!filtered) {
        expect(sources.some((row) => row.source_id === "mac-local" && row.status === "ok"), record.name).toBe(true);
        expect(sources.some((row) => row.source_id === "linux-stale-eve" && row.status === "stale"), record.name).toBe(true);
      }
    }
  }
}

function normalizeStoreMetadata(value: unknown, fieldName = ""): unknown {
  if (Array.isArray(value)) {
    const normalized = value.map((item) => normalizeStoreMetadata(item));
    return fieldName === "source_status" || fieldName === "sources" ? sortedSourceRows(normalized) : normalized;
  }
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key, key === "backend_mode" || key === "canonical_store" ? "<store-specific>" : normalizeStoreMetadata(item, key),
      ]),
    );
  }
  return value;
}

function sortedSourceRows(value: unknown): unknown[] {
  return Array.isArray(value)
    ? [...value].sort((left, right) => String((left as Record<string, unknown>).source_id ?? "").localeCompare(String((right as Record<string, unknown>).source_id ?? "")))
    : [];
}

function expectMobileLimitsWindows(records: ContractRecord[]): void {
  for (const record of records.filter((item) => item.name.startsWith("mobile-summary-"))) {
    const body = record.response.body as Record<string, unknown>;
    const limits = body.limits as Record<string, unknown>;
    const windows = limits.windows as Array<Record<string, unknown>>;
    expect(Array.isArray(windows), record.name).toBe(true);
    expect(windows.length, record.name).toBeGreaterThan(0);
    expect(windows.every((row) => row.official === true && row.confidence === "observed" && row.status === "ok"), record.name).toBe(true);
  }
}

function totalTokensByRecord(records: ContractRecord[]): Record<string, number> {
  const totals: Record<string, number> = {};
  for (const record of records) {
    const body = record.response.body as Record<string, unknown>;
    const summary = body.summary as Record<string, unknown> | undefined;
    const period = body.period as Record<string, unknown> | undefined;
    totals[record.name] = Number(summary?.total_tokens ?? period?.total_tokens ?? 0);
  }
  return totals;
}

function sourceHealthByRecord(records: ContractRecord[]): Record<string, unknown> {
  const statuses: Record<string, unknown> = {};
  for (const record of records) {
    const body = record.response.body as Record<string, unknown>;
    statuses[record.name] = body.source_status ?? body.sources ?? [];
  }
  return statuses;
}

function expectLargeSourceHealth(summary: ContractRecord, mobile: ContractRecord, sourceIds: string[]): void {
  const statuses = (summary.response.body as Record<string, unknown>).source_status as Array<Record<string, unknown>>;
  const sources = (mobile.response.body as Record<string, unknown>).sources as Array<Record<string, unknown>>;
  expect(statuses.length).toBe(sourceIds.length);
  expect(sources.length).toBe(sourceIds.length);
  for (const sourceId of sourceIds) {
    expect(statuses.some((row) => row.source_id === sourceId && row.status === "ok"), sourceId).toBe(true);
    expect(sources.some((row) => row.source_id === sourceId && row.status === "ok"), sourceId).toBe(true);
  }
}

function buildLargeIngestPayloads(): Record<string, unknown>[] {
  return ["mac-local-large", "linux-dev-large", "windows-lab-large"].map((sourceId, sourceIndex) => {
    const host = ["macbook-pro", "linux-dev", "windows-lab"][sourceIndex];
    const user = ["alice", "bob", "carol"][sourceIndex];
    const usageDaily = Array.from({ length: 120 }, (_, index) => {
      const date = dateOffset("2026-02-23", index);
      const agent = index % 3 === 0 ? "codex" : "claude";
      const inputTokens = 1000 + sourceIndex * 100 + index * 3;
      const outputTokens = 400 + index;
      return {
        period: date,
        agent,
        inputTokens,
        outputTokens,
        cacheCreationTokens: 20 + (index % 5),
        cacheReadTokens: 30 + (index % 7),
        totalTokens: inputTokens + outputTokens + 20 + (index % 5) + 30 + (index % 7),
        totalCost: Number((1.25 + index / 100).toFixed(4)),
        modelBreakdowns: [{
          modelName: agent === "codex" ? "gpt-5-codex" : "claude-sonnet",
          inputTokens,
          outputTokens,
          cacheCreationTokens: 20 + (index % 5),
          cacheReadTokens: 30 + (index % 7),
          totalTokens: inputTokens + outputTokens + 20 + (index % 5) + 30 + (index % 7),
          cost: Number((1.25 + index / 100).toFixed(4)),
        }],
      };
    });
    const codexHourly = Array.from({ length: 36 }, (_, index) => ({
      hour: `2026-06-${String(21 + Math.floor(index / 24)).padStart(2, "0")}T${String(index % 24).padStart(2, "0")}:00:00+08:00`,
      input_tokens: 300 + index,
      output_tokens: 120 + index,
      cache_creation_tokens: 10,
      cache_read_tokens: 12,
      reasoning_output_tokens: 20,
      total_tokens: 462 + index * 2,
      event_count: 2,
      session_count: 1,
      provenance: "mswusage_codex_token_count",
    }));
    const sessions = Array.from({ length: 36 }, (_, index) => ({
      agent: "claude",
      inputTokens: 250 + index,
      outputTokens: 90 + index,
      cacheCreationTokens: 8,
      cacheReadTokens: 10,
      totalTokens: 358 + index * 2,
      totalCost: Number((0.5 + index / 200).toFixed(4)),
      metadata: {
        lastActivity: `2026-06-${String(21 + Math.floor(index / 24)).padStart(2, "0")}T${String(index % 24).padStart(2, "0")}:17:00+08:00`,
      },
    }));
    // #91：采集端已停采 ccusage blocks，「当前采集端」的模拟 payload 不再携带
    // ccusage_blocks_report（老采集端仍在发的形态由上面的探针用例专门守）。
    const facts = Array.from({ length: 72 }, (_, index) => {
      const agent = index % 2 === 0 ? "codex" : "claude";
      const day = 20 + Math.floor(index / 24);
      const hour = index % 24;
      const totalTokens = 600 + index * 4;
      return {
        fact_id: `${sourceId}-${agent}-${index}`,
        device: {
          machine_id: host,
          machine_name: host,
          host,
          os_user: user,
          platform: sourceIndex === 0 ? "darwin" : sourceIndex === 1 ? "linux" : "windows",
        },
        ai_account: {
          provider: agent === "codex" ? "openai" : "anthropic",
          account_id: `${agent}-${user}`,
          label: `${agent} ${user}`,
          subscription: "pro",
        },
        agent,
        client: agent,
        window_start: `2026-06-${String(day).padStart(2, "0")}T${String(hour).padStart(2, "0")}:00:00+08:00`,
        window_end: `2026-06-${String(day).padStart(2, "0")}T${String(hour).padStart(2, "0")}:59:59+08:00`,
        usage: {
          input_tokens: 350 + index,
          output_tokens: 170 + index,
          cache_creation_tokens: 14,
          cache_read_tokens: 18,
          reasoning_output_tokens: agent === "codex" ? 30 : 0,
          total_tokens: totalTokens,
          total_cost: Number((0.8 + index / 180).toFixed(4)),
        },
        event_count: 3,
        session_count: 1,
        attribution_confidence: "account_exact",
        provenance: agent === "codex" ? "mswusage_codex_token_count" : "ccusage_blocks",
        account_evidence: { source: "fixture" },
        metadata: { batch: "large-ingest" },
        model_breakdowns: [{
          model: agent === "codex" ? "gpt-5-codex" : "claude-sonnet",
          input_tokens: 350 + index,
          output_tokens: 170 + index,
          cache_creation_tokens: 14,
          cache_read_tokens: 18,
          reasoning_output_tokens: agent === "codex" ? 30 : 0,
          total_tokens: totalTokens,
          total_cost: Number((0.8 + index / 180).toFixed(4)),
        }],
      };
    });
    return {
      schema_version: 1,
      source_id: sourceId,
      host,
      machine: host,
      os_user: user,
      platform: sourceIndex === 0 ? "darwin" : sourceIndex === 1 ? "linux" : "windows",
      timezone: "Asia/Shanghai",
      observed_at: `2026-06-22T1${sourceIndex}:30:00+08:00`,
      collection_window: "daily",
      usage_daily: usageDaily,
      ccusage_daily_report: { daily: usageDaily, totals: { totalTokens: 500000 + sourceIndex } },
      ccusage_session_report: { session: sessions },
      mswusage_codex_hourly_report: {
        hourly: codexHourly,
        provenance: "mswusage_codex_token_count",
      },
      usage_hourly_facts: facts,
      collection_status: "ok",
      error_type: null,
      error_message: null,
    };
  });
}

function dateOffset(start: string, offset: number): string {
  const date = new Date(`${start}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + offset);
  return date.toISOString().slice(0, 10);
}
