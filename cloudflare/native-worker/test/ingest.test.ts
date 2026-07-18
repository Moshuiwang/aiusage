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

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const schemaPath = path.join(repoRoot, "cloudflare/migrations/0001_initial_schema.sql");
const workerEntry = path.join(repoRoot, "cloudflare/native-worker/src/index.ts");
const writeModelPath = path.join(repoRoot, "cloudflare/native-worker/src/write-model.ts");
const fixturePath = path.join(repoRoot, "tests/fixtures/native_worker_ingest_payloads.json");
const ingestGoldenPath = path.join(repoRoot, "cloudflare/native-worker/test/ingest_value_golden.json");
const token = "contract-test-token";

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

  it("writes ingest and limits payloads, then matches Python write-then-read value golden", async () => {
    await applyAllPayloads(fixture.ingest_payloads, fixture.limits_payloads);
    const counts = await tableCounts();
    expect(counts.limit_windows, "D1 limit_windows must be non-empty after /ingest-limits").toBeGreaterThan(0);

    const records = await readRecords(fixture.date);
    const golden = JSON.parse(await readFile(ingestGoldenPath, "utf8")) as ContractRecord[];
    expectSourceHealth(records);
    expectMobileLimitsWindows(records);
    expect(normalizeStoreMetadata(records)).toEqual(normalizeStoreMetadata(golden));
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

  it("recovers source health through HTTP ingest when report tables start empty", async () => {
    await applyAllPayloads(fixture.ingest_payloads, fixture.limits_payloads);
    await clearSourceHealthTables();

    const prodShapeCounts = await tableCounts();
    expect(prodShapeCounts.collection_runs).toBe(0);
    expect(prodShapeCounts.source_reports).toBe(0);
    expect(prodShapeCounts.source_identities).toBeGreaterThan(0);
    expect(prodShapeCounts.usage_daily).toBeGreaterThan(0);

    const emptyHealth = await recordValue("summary-today-empty-source-health", `/api/summary?date=${fixture.date}&period=today`);
    expect(((emptyHealth.response.body as Record<string, unknown>).source_status as unknown[]).length).toBe(0);

    await applyAllPayloads(fixture.ingest_payloads, fixture.limits_payloads);

    const records = await readRecords(fixture.date);
    const golden = JSON.parse(await readFile(ingestGoldenPath, "utf8")) as ContractRecord[];
    expectSourceHealth(records);
    expect(normalizeStoreMetadata(records)).toEqual(normalizeStoreMetadata(golden));

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
  });

  it("writes large historical ingest payloads through HTTP without dropping source health", async () => {
    const largePayloads = buildLargeIngestPayloads();

    for (const payload of largePayloads) {
      const rowsWritten = await postIngest(payload);
      expect(rowsWritten).toBeGreaterThan(150);
    }

    const counts = await tableCounts();
    expect(counts.usage_daily).toBeGreaterThanOrEqual(largePayloads.length * 120);
    expect(counts.usage_hourly).toBeGreaterThanOrEqual(largePayloads.length * 72);
    expect(counts.usage_blocks).toBeGreaterThanOrEqual(largePayloads.length * 36);
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

  it("replaces superseded Codex hourly rows and recovers provider_failed limit windows", async () => {
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
    expect((currentCodexHours.results ?? []).map((row) => row.hour)).toEqual([
      "2026-06-03T10:00:00+08:00",
      "2026-06-03T11:00:00+08:00",
    ]);
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

  async function clearSourceHealthTables(): Promise<void> {
    const db = await mf.getD1Database("AIUSAGE_DB");
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

function normalizeStoreMetadata(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => normalizeStoreMetadata(item));
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key,
        key === "backend_mode" || key === "canonical_store" ? "<store-specific>" : normalizeStoreMetadata(item),
      ]),
    );
  }
  return value;
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
    const blocks = Array.from({ length: 36 }, (_, index) => ({
      agent: "claude",
      startTime: `2026-06-${String(21 + Math.floor(index / 24)).padStart(2, "0")}T${String(index % 24).padStart(2, "0")}:00:00+08:00`,
      actualEndTime: `2026-06-${String(21 + Math.floor(index / 24)).padStart(2, "0")}T${String(index % 24).padStart(2, "0")}:59:00+08:00`,
      tokenCounts: {
        inputTokens: 200 + index,
        outputTokens: 80 + index,
        cacheCreationInputTokens: 6,
        cacheReadInputTokens: 9,
      },
      totalTokens: 295 + index * 2,
      costUSD: Number((0.35 + index / 300).toFixed(4)),
    }));
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
      ccusage_blocks_report: { blocks },
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
