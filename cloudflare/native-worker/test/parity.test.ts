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

type Shape = Record<string, unknown>;

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const goldenPath = path.join(repoRoot, "tests/fixtures/contract/api_contract_golden.json");
const valueGoldenPath = path.join(repoRoot, "cloudflare/native-worker/test/value_golden.json");
const schemaPath = path.join(repoRoot, "cloudflare/migrations/0001_initial_schema.sql");
const seedSqlPath = path.join(repoRoot, "cloudflare/native-worker/test/seed.sql");
const workerEntry = path.join(repoRoot, "cloudflare/native-worker/src/index.ts");
const token = "contract-test-token";
const fixedNow = "2026-06-03T12:00:00+08:00";

const volatileFields = new Set([
  "accepted_at",
  "generated_at",
  "mtime",
  "path",
  "size_bytes",
  "updated_at",
]);
const enumFields = new Set([
  "client",
  "confidence",
  "error_type",
  "exists",
  "granularity",
  "id",
  "official",
  "period",
  "provider",
  "schema_version",
  "status",
  "success",
  "window",
]);
const floatFields = new Set(["used_percent", "remaining_percent"]);

describe.sequential("native TS Worker read-only API parity", () => {
  let mf: Miniflare;

  beforeEach(async () => {
    mf = await createMiniflare();
    const db = await mf.getD1Database("AIUSAGE_DB");
    await applySchema(db);
    await seedUsageFixture(db);
  });

  afterEach(async () => {
    await mf.dispose();
  });

  it("matches Python golden for summary and mobile summary read paths", async () => {
    const golden = JSON.parse(await readFile(goldenPath, "utf8")) as ContractRecord[];
    const expected = new Map(golden.map((record) => [record.name, record]));
    const records: ContractRecord[] = [];

    records.push(await record("summary-requires-auth", "/api/summary?date=2026-06-03", false));
    records.push(await record("mobile-summary-requires-auth", "/api/mobile/summary?date=2026-06-03", false));

    for (const period of ["today", "week", "month", "all"]) {
      records.push(await record(`summary-${period}-missing-limits`, `/api/summary?date=2026-06-03&period=${period}`, true));
      records.push(await record(`mobile-summary-${period}-missing-limits`, `/api/mobile/summary?date=2026-06-03&period=${period}`, true));
    }

    records.push(await record("summary-week-machine-filter", "/api/summary?date=2026-06-03&period=week&machine=macbook-pro", true));
    records.push(await record("summary-week-account-filter", "/api/summary?date=2026-06-03&period=week&account=alice", true));
    records.push(await record("mobile-summary-week-machine-filter", "/api/mobile/summary?date=2026-06-03&period=week&machine=linux-dev", true));
    records.push(await record("mobile-summary-week-account-filter", "/api/mobile/summary?date=2026-06-03&period=week&account=bob", true));

    const db = await mf.getD1Database("AIUSAGE_DB");
    await seedLimitsFixture(db);
    records.push(await record("summary-week-observed-limits", "/api/summary?date=2026-06-03&period=week", true));
    records.push(await record("mobile-summary-week-observed-limits", "/api/mobile/summary?date=2026-06-03&period=week", true));

    for (const actual of records) {
      const wanted = expected.get(actual.name);
      expect(wanted, `${actual.name} exists in Python golden`).toBeTruthy();
      expect(actual).toEqual(wanted);
    }
  });

  it("matches Python value golden for summary and mobile summary read paths", async () => {
    const golden = JSON.parse(await readFile(valueGoldenPath, "utf8")) as ContractRecord[];
    await mf.dispose();
    mf = await createMiniflare({ AIUSAGE_NOW: fixedNow });
    const db = await mf.getD1Database("AIUSAGE_DB");
    await applySchema(db);
    await applySqlFile(db, seedSqlPath);

    const records: ContractRecord[] = [];
    for (const period of ["today", "week", "month", "all"]) {
      records.push(await recordValue(`summary-${period}`, `/api/summary?date=2026-06-03&period=${period}`));
      records.push(await recordValue(`mobile-summary-${period}`, `/api/mobile/summary?date=2026-06-03&period=${period}`));
    }
    records.push(await recordValue("summary-week-machine-filter", "/api/summary?date=2026-06-03&period=week&machine=macbook-pro"));
    records.push(await recordValue("mobile-summary-week-machine-filter", "/api/mobile/summary?date=2026-06-03&period=week&machine=linux-dev"));
    records.push(await recordValue("summary-week-account-filter", "/api/summary?date=2026-06-03&period=week&account=alice"));
    records.push(await recordValue("mobile-summary-week-account-filter", "/api/mobile/summary?date=2026-06-03&period=week&account=bob"));
    records.push(await recordValue("summary-week-observed-limits", "/api/summary?date=2026-06-03&period=week"));
    records.push(await recordValue("mobile-summary-week-observed-limits", "/api/mobile/summary?date=2026-06-03&period=week"));

    expect(normalizeStoreMetadata(records)).toEqual(normalizeStoreMetadata(golden));

    const summaryWeek = bodyFor(records, "summary-week");
    const mobileSummaryWeek = bodyFor(records, "mobile-summary-week");
    const dbCounts = await tableCounts(db);
    expect(summaryWeek.source_status, "Native source_status must be covered by value parity").toEqual(
      bodyFor(golden, "summary-week").source_status,
    );
    expect(mobileSummaryWeek.sources, "Native mobile sources must be covered by value parity").toEqual(
      bodyFor(golden, "mobile-summary-week").sources,
    );
    expect((summaryWeek.source_status as unknown[]).length, "source_status must be non-empty").toBeGreaterThan(0);
    expect((mobileSummaryWeek.sources as unknown[]).length, "mobile sources must be non-empty").toBeGreaterThan(0);
    expect((summaryWeek.source_status as Shape[]).map((row) => row.status), "source_status covers ok sources").toContain("ok");
    expect((summaryWeek.source_status as Shape[]).map((row) => row.status), "source_status covers stale sources").toContain("stale");
    expect((mobileSummaryWeek.sources as Shape[]).map((row) => row.status), "mobile sources covers stale sources").toContain("stale");
    expect(dbCounts.limit_windows, "D1 limit_windows must be non-empty for limits parity").toBeGreaterThan(0);
    expect(((mobileSummaryWeek.limits as Shape).windows as Shape[]).length, "mobile limits windows must be covered").toBeGreaterThan(0);
    expect(((mobileSummaryWeek.limits as Shape).windows as Shape[]).every((row) =>
      row.official === true && row.confidence === "observed" && row.status === "ok",
    ), "mobile limits windows are effective only").toBe(true);
    for (const row of ((summaryWeek.groups as Shape).by_machine as Shape[])) {
      expect(row.source_ids, `groups.by_machine ${String(row.name)} must expose source_ids`).toEqual(
        expect.arrayContaining(
          ((row.users as Shape[]) ?? []).flatMap((user) => (user.source_ids as string[]) ?? []),
        ),
      );
      expect((row.source_ids as unknown[]).length, `groups.by_machine ${String(row.name)} source_ids must be non-empty`).toBeGreaterThan(0);
    }
  });

  it("fails closed immediately when a provider failure follows a successful quota read", async () => {
    await mf.dispose();
    mf = await createMiniflare({ AIUSAGE_NOW: "2026-06-03T10:31:00+08:00" });
    const db = await mf.getD1Database("AIUSAGE_DB");
    await applySchema(db);
    await seedUsageFixture(db);
    await db.batch([
      db.prepare(`
        INSERT INTO limit_windows (
          source_id, provider, window, used_percent, remaining_percent, reset_at,
          window_duration_minutes, source_type, confidence, status, observed_at, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind("linux-biai-wangzhipeng", "claude", "session", 76, 24, "2026-06-03T15:00:00+08:00", 300, "oauth_usage_api", "observed", "ok", "2026-06-03T10:00:00+08:00", "2026-06-03T10:00:00+08:00", "2026-06-03T10:00:00+08:00"),
      db.prepare(`
        INSERT INTO limit_windows (
          source_id, provider, window, used_percent, remaining_percent, reset_at,
          window_duration_minutes, source_type, confidence, status, observed_at, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind("linux-biai-wangzhipeng", "claude", "unknown", 0, 0, "2026-06-03T10:30:00+08:00", 0, "provider_runtime", "missing", "provider_failed", "2026-06-03T10:30:00+08:00", "2026-06-03T10:30:00+08:00", "2026-06-03T10:30:00+08:00"),
    ]);

    const summary = bodyFor(
      [await recordValue("summary-after-provider-failure", "/api/summary?date=2026-06-03&period=today")],
      "summary-after-provider-failure",
    );
    const mobile = bodyFor(
      [await recordValue("mobile-after-provider-failure", "/api/mobile/summary?date=2026-06-03&period=today")],
      "mobile-after-provider-failure",
    );
    expect(summary.limit_status).toEqual([{
      provider: "claude", source_id: "linux-biai-wangzhipeng",
      observed_at: "2026-06-03T10:00:00+08:00", source_type: "oauth_usage_api", status: "unavailable",
    }]);
    expect((mobile.limits as Shape).windows).toEqual([]);
  });

  it("uses usage_hourly_facts as the mobile summary period total when stale daily rows disagree", async () => {
    const db = await mf.getD1Database("AIUSAGE_DB");
    for (const table of [
      "usage_hourly_models",
      "usage_hourly_facts",
      "usage_blocks",
      "usage_hourly",
      "usage_daily_models",
      "usage_daily",
      "ai_accounts",
      "os_identities",
      "machines",
      "source_identities",
    ]) {
      await db.prepare(`DELETE FROM ${table}`).run();
    }
    await db.prepare(`
      INSERT INTO source_identities (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "mac-local", "macbook-pro.local", "MacBook Pro", "wangzhipeng", "darwin",
      "2026-06-11T14:30:00+08:00", "2026-06-11T14:30:00+08:00",
    ).run();
    await db.prepare(`
      INSERT INTO usage_daily (
        source_id, date, agent, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, total_tokens, total_cost, metadata_json, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "mac-local", "2026-06-11", "codex", 10, 5, 0, 5, 20, null,
      JSON.stringify({ machine: "MacBook Pro", account: "wangzhipeng" }),
      "2026-06-11T14:30:00+08:00", "2026-06-11T14:30:00+08:00",
    ).run();
    await db.prepare(`
      INSERT INTO machines (machine_id, machine_name, host, platform, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `).bind(
      "macbook-pro-local", "MacBook Pro", "macbook-pro.local", "darwin",
      "2026-06-11T14:30:00+08:00", "2026-06-11T14:30:00+08:00",
    ).run();
    await db.prepare(`
      INSERT INTO ai_accounts (provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "openai", "unconfirmed_local_source:mac-local:codex", "本机来源 / 未确认账号",
      null, null, "2026-06-11T14:30:00+08:00", "2026-06-11T14:30:00+08:00",
    ).run();
    await db.prepare(`
      INSERT INTO usage_hourly_facts (
        fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
        session_count, attribution_confidence, provenance, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "codex:codex:mac-local:2026-06-11T13:00:00+08:00:2026-06-11T14:00:00+08:00:unconfirmed_local_source:openai:unconfirmed_local_source:mac-local:codex:mswusage_codex_token_count",
      "mac-local", "macbook-pro-local", "wangzhipeng", "openai", "unconfirmed_local_source:mac-local:codex",
      "codex", "codex", "2026-06-11T13:00:00+08:00", "2026-06-11T14:00:00+08:00",
      "Asia/Shanghai", 100, 20, 0, 30, 5, 155, null, 2, 1,
      "unconfirmed_local_source", "mswusage_codex_token_count",
      "2026-06-11T14:30:00+08:00", "2026-06-11T14:30:00+08:00",
    ).run();

    const mobile = bodyFor(
      [await recordValue("mobile-summary-ledger-total", "/api/mobile/summary?date=2026-06-11&period=today")],
      "mobile-summary-ledger-total",
    );

    expect((mobile.period as Shape).total_tokens).toBe(155);
    expect(((mobile.breakdown as Shape).by_agent as Shape[])).toEqual([
      expect.objectContaining({ id: "codex", tokens: 155 }),
    ]);
    const trendTotal = (((mobile.trend as Shape).points as Shape[]) ?? [])
      .reduce((sum, point) => sum + Number(point.tokens ?? 0), 0);
    expect(trendTotal).toBe(155);
    for (const point of (((mobile.trend as Shape).points as Shape[]) ?? [])) {
      expect(
        Number(point.claude_tokens ?? 0) +
        Number(point.codex_tokens ?? 0) +
        Number(point.unknown_tokens ?? 0),
      ).toBe(Number(point.tokens ?? 0));
    }
  });

  it("keeps the all-agent daily residual when ledger only covers one agent", async () => {
    const db = await mf.getD1Database("AIUSAGE_DB");
    for (const table of [
      "usage_hourly_models",
      "usage_hourly_facts",
      "usage_blocks",
      "usage_hourly",
      "usage_daily_models",
      "usage_daily",
      "ai_accounts",
      "os_identities",
      "machines",
      "source_identities",
    ]) {
      await db.prepare(`DELETE FROM ${table}`).run();
    }
    await db.prepare(`
      INSERT INTO source_identities (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "mac-local", "macbook-pro.local", "MacBook Pro", "wangzhipeng", "darwin",
      "2026-06-12T14:30:00+08:00", "2026-06-12T14:30:00+08:00",
    ).run();
    await db.prepare(`
      INSERT INTO usage_daily (
        source_id, date, agent, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, total_tokens, total_cost, metadata_json, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "mac-local", "2026-06-12", "all", 1000, 0, 0, 0, 1000, null,
      JSON.stringify({ machine: "MacBook Pro", account: "wangzhipeng" }),
      "2026-06-12T14:30:00+08:00", "2026-06-12T14:30:00+08:00",
    ).run();
    await db.prepare(`
      INSERT INTO machines (machine_id, machine_name, host, platform, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `).bind(
      "macbook-pro-local", "MacBook Pro", "macbook-pro.local", "darwin",
      "2026-06-12T14:30:00+08:00", "2026-06-12T14:30:00+08:00",
    ).run();
    await db.prepare(`
      INSERT INTO ai_accounts (provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "openai", "unconfirmed_local_source:mac-local:codex", "本机来源 / 未确认账号",
      null, null, "2026-06-12T14:30:00+08:00", "2026-06-12T14:30:00+08:00",
    ).run();
    await db.prepare(`
      INSERT INTO usage_hourly_facts (
        fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
        session_count, attribution_confidence, provenance, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "codex:codex:mac-local:2026-06-12T13:00:00+08:00:2026-06-12T14:00:00+08:00:unconfirmed_local_source:openai:unconfirmed_local_source:mac-local:codex:mswusage_codex_token_count",
      "mac-local", "macbook-pro-local", "wangzhipeng", "openai", "unconfirmed_local_source:mac-local:codex",
      "codex", "codex", "2026-06-12T13:00:00+08:00", "2026-06-12T14:00:00+08:00",
      "Asia/Shanghai", 400, 0, 0, 0, 0, 400, null, 1, 1,
      "unconfirmed_local_source", "mswusage_codex_token_count",
      "2026-06-12T14:30:00+08:00", "2026-06-12T14:30:00+08:00",
    ).run();

    const mobile = bodyFor(
      [await recordValue("mobile-summary-ledger-residual", "/api/mobile/summary?date=2026-06-12&period=today")],
      "mobile-summary-ledger-residual",
    );

    expect((mobile.period as Shape).total_tokens).toBe(1000);
    expect(((mobile.breakdown as Shape).by_agent as Shape[])).toEqual([
      expect.objectContaining({ id: "all", tokens: 600 }),
      expect.objectContaining({ id: "codex", tokens: 400 }),
    ]);
  });

  it("dedupes cumulative ccusage block snapshots before building today's hourly trend", async () => {
    const db = await mf.getD1Database("AIUSAGE_DB");
    for (const table of [
      "usage_hourly_models",
      "usage_hourly_facts",
      "usage_blocks",
      "usage_hourly",
      "usage_daily_models",
      "usage_daily",
      "ai_accounts",
      "os_identities",
      "machines",
      "source_identities",
    ]) {
      await db.prepare(`DELETE FROM ${table}`).run();
    }
    await db.prepare(`
      INSERT INTO source_identities (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "mac-local", "macbook-pro.local", "MacBook Pro", "wangzhipeng", "darwin",
      "2026-06-28T09:45:00+08:00", "2026-06-28T09:45:00+08:00",
    ).run();
    await db.prepare(`
      INSERT INTO usage_daily (
        source_id, date, agent, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, total_tokens, total_cost, metadata_json, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "mac-local", "2026-06-28", "all", 1000, 500, 0, 20000, 21500, null,
      JSON.stringify({ machine: "MacBook Pro", account: "wangzhipeng" }),
      "2026-06-28T09:45:00+08:00", "2026-06-28T09:45:00+08:00",
    ).run();
    await db.prepare(`
      INSERT INTO usage_hourly (
        source_id, hour, agent, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, total_tokens, total_cost, metadata_json, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "mac-local", "2026-06-28T08:00:00+08:00", "codex", 100, 50, 0, 3350, 3500, null,
      JSON.stringify({ machine: "MacBook Pro", account: "wangzhipeng" }),
      "2026-06-28T09:45:00+08:00", "2026-06-28T09:45:00+08:00",
    ).run();
    for (const block of [
      {
        end: "2026-06-28T08:12:00+08:00",
        total: 5000,
        input: 200,
        output: 100,
        cache: 4700,
        actualEndTime: "2026-06-28T00:12:00.000Z",
      },
      {
        end: "2026-06-28T08:48:00+08:00",
        total: 10000,
        input: 300,
        output: 200,
        cache: 9500,
        actualEndTime: "2026-06-28T00:48:00.000Z",
      },
    ]) {
      await db.prepare(`
        INSERT INTO usage_blocks (
          source_id, start_time, end_time, agent, input_tokens, output_tokens,
          cache_creation_tokens, cache_read_tokens, total_tokens, total_cost,
          metadata_json, raw_json, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind(
        "mac-local", "2026-06-28T08:00:00+08:00", block.end, "claude",
        block.input, block.output, 0, block.cache, block.total, null,
        JSON.stringify({
          machine: "MacBook Pro",
          account: "wangzhipeng",
          ccusage_block_row: {
            id: "2026-06-28T00:00:00.000Z",
            actualEndTime: block.actualEndTime,
          },
        }),
        null, "2026-06-28T09:45:00+08:00", "2026-06-28T09:45:00+08:00",
      ).run();
    }

    const mobile = bodyFor(
      [await recordValue("mobile-summary-deduped-block-trend", "/api/mobile/summary?date=2026-06-28&period=today")],
      "mobile-summary-deduped-block-trend",
    );

    const points = ((mobile.trend as Shape).points as Shape[]) ?? [];
    const eight = points.find((point) => point.label === "08:00");
    expect(eight).toEqual(expect.objectContaining({ tokens: 13500 }));
  });

  async function record(name: string, requestPath: string, auth: boolean): Promise<ContractRecord> {
    const headers = auth ? { Authorization: `Bearer ${token}` } : undefined;
    const response = await mf.dispatchFetch(`http://native.test${requestPath}`, { headers });
    const contentType = response.headers.get("Content-Type") ?? "";
    const body = await response.arrayBuffer();
    return {
      name,
      request: {
        method: "GET",
        path: requestPath,
        auth,
      },
      response: {
        status: response.status,
        content_type: contentType.split(";")[0],
        location: response.headers.get("Location"),
        body: bodyContract(contentType, Buffer.from(body)),
      },
    };
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
});

function bodyFor(records: ContractRecord[], name: string): Shape {
  const record = records.find((item) => item.name === name);
  expect(record, `${name} record exists`).toBeTruthy();
  return record?.response.body as Shape;
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
      AIUSAGE_TIMEZONE: "Asia/Shanghai",
      ...extraBindings,
    },
  });
}

async function seedUsageFixture(db: D1Database): Promise<void> {
  const now = new Date().toISOString();
  await insertUsagePayload(db, {
    runId: 1,
    now,
    sourceId: "mac-local",
    host: "macbook-pro",
    machine: "macbook-pro",
    osUser: "alice",
    platform: "darwin",
    agent: "claude",
    period: "2026-06-01",
    model: "claude-sonnet",
    inputTokens: 1200,
    outputTokens: 500,
    cacheTokens: 300,
  });
  await insertUsagePayload(db, {
    runId: 2,
    now,
    sourceId: "linux-dev-bob",
    host: "linux-dev",
    machine: "linux-dev",
    osUser: "bob",
    platform: "linux",
    agent: "codex",
    period: "2026-06-02",
    model: "gpt-5",
    inputTokens: 1600,
    outputTokens: 900,
    cacheTokens: 500,
  });
  await insertUsagePayload(db, {
    runId: 3,
    now,
    sourceId: "mac-local",
    host: "macbook-pro",
    machine: "macbook-pro",
    osUser: "alice",
    platform: "darwin",
    agent: "claude",
    period: "2026-06-03",
    model: "claude-sonnet",
    inputTokens: 2200,
    outputTokens: 600,
    cacheTokens: 200,
  });
}

async function insertUsagePayload(
  db: D1Database,
  row: {
    runId: number;
    now: string;
    sourceId: string;
    host: string;
    machine: string;
    osUser: string;
    platform: string;
    agent: string;
    period: string;
    model: string;
    inputTokens: number;
    outputTokens: number;
    cacheTokens: number;
  },
): Promise<void> {
  const totalTokens = row.inputTokens + row.outputTokens + row.cacheTokens;
  const dailyRaw = {
    agent: row.agent,
    period: row.period,
    inputTokens: row.inputTokens,
    outputTokens: row.outputTokens,
    cacheCreationTokens: row.cacheTokens,
    cacheReadTokens: 0,
    totalTokens,
    modelBreakdowns: [
      {
        modelName: row.model,
        inputTokens: row.inputTokens,
        outputTokens: row.outputTokens,
        cacheCreationTokens: row.cacheTokens,
        cacheReadTokens: 0,
        totalTokens,
      },
    ],
  };
  const metadata = {
    ccusage_row: dailyRaw,
    machine: row.machine,
    host: row.host,
    account: row.osUser,
    platform: row.platform,
  };

  await db.batch([
    db.prepare("INSERT INTO collection_runs (id, collected_at, timezone, collector_version, status) VALUES (?, ?, ?, ?, ?)")
      .bind(row.runId, row.now, "Asia/Shanghai", "0.1.0", "ok"),
    db.prepare(`
      INSERT INTO source_reports (
        id, run_id, source_id, report_type, command, status, ccusage_version,
        first_period, last_period, error_type, error_message
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(row.runId, row.runId, row.sourceId, "daily", "HTTP Ingest", "ok", null, row.period, row.period, null, null),
    db.prepare(`
      INSERT INTO source_identities (
        source_id, host, machine, os_user, platform, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(source_id) DO UPDATE SET
        host=excluded.host,
        machine=excluded.machine,
        os_user=excluded.os_user,
        platform=excluded.platform,
        last_seen_at=excluded.last_seen_at
    `).bind(row.sourceId, row.host, row.machine, row.osUser, row.platform, row.now, row.now),
    db.prepare(`
      INSERT INTO usage_daily (
        source_id, date, agent, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, total_tokens, total_cost, metadata_json, raw_json,
        first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      row.sourceId,
      row.period,
      row.agent,
      row.inputTokens,
      row.outputTokens,
      row.cacheTokens,
      0,
      totalTokens,
      null,
      JSON.stringify(metadata),
      JSON.stringify(dailyRaw),
      row.now,
      row.now,
    ),
    db.prepare(`
      INSERT INTO usage_daily_models (
        source_id, date, agent, model_name, input_tokens, output_tokens,
        cache_creation_tokens, cache_read_tokens, total_tokens, cost, raw_json,
        first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      row.sourceId,
      row.period,
      row.agent,
      row.model,
      row.inputTokens,
      row.outputTokens,
      row.cacheTokens,
      0,
      totalTokens,
      null,
      JSON.stringify(dailyRaw.modelBreakdowns[0]),
      row.now,
      row.now,
    ),
  ]);
}

async function seedLimitsFixture(db: D1Database): Promise<void> {
  await db.batch([
    db.prepare(`
      INSERT INTO limit_windows (
        source_id, provider, window, used_percent, remaining_percent, reset_at,
        window_duration_minutes, source_type, confidence, status, observed_at,
        first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind("codex-main", "codex", "session", 40, 60, "2026-06-03T16:00:00+08:00", 300, "runtime_api", "observed", "ok", "2026-06-03T11:00:00+08:00", "2026-06-03T11:00:00+08:00", "2026-06-03T11:00:00+08:00"),
    db.prepare(`
      INSERT INTO limit_windows (
        source_id, provider, window, used_percent, remaining_percent, reset_at,
        window_duration_minutes, source_type, confidence, status, observed_at,
        first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind("claude-weekly", "claude", "week", 0, 0, "2026-06-10T00:00:00+08:00", 10080, "oauth_usage_api", "missing", "provider_failed", "2026-06-03T11:00:00+08:00", "2026-06-03T11:00:00+08:00", "2026-06-03T11:00:00+08:00"),
  ]);
}

async function tableCounts(db: D1Database): Promise<Record<string, number>> {
  const tables = ["limit_windows"];
  const counts: Record<string, number> = {};
  for (const table of tables) {
    const row = await db.prepare(`SELECT count(*) AS count FROM ${table}`).first<{ count: number }>();
    counts[table] = Number(row?.count ?? 0);
  }
  return counts;
}

function bodyContract(contentType: string, body: Buffer): Shape {
  if (contentType.includes("application/json")) {
    return { kind: "json", shape: shape(withoutNativeMachineSourceIdsForContract(JSON.parse(body.toString("utf8")))) };
  }
  if (contentType.includes("text/html")) {
    return { kind: "html", present: body.length > 0 };
  }
  if (body.length > 0) {
    return { kind: "text", present: true };
  }
  return { kind: "empty", present: false };
}

function withoutNativeMachineSourceIdsForContract(value: unknown): unknown {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return value;
  const payload = value as Record<string, unknown>;
  const limits = payload.limits as Record<string, unknown> | undefined;
  const groups = payload.groups as Record<string, unknown> | undefined;
  const normalized: Record<string, unknown> = { ...payload };
  if (payload.client === "ios" && limits && Array.isArray(limits.windows)) {
    normalized.limits = {
      ...limits,
      windows: limits.windows.filter((row) => {
        if (row === null || typeof row !== "object" || Array.isArray(row)) return true;
        return String((row as Record<string, unknown>).window ?? "").toLowerCase() !== "session";
      }),
    };
  }
  if (!groups || !Array.isArray(groups.by_machine)) return normalized;
  return {
    ...normalized,
    groups: {
      ...groups,
      by_machine: groups.by_machine.map((row) => {
        if (row === null || typeof row !== "object" || Array.isArray(row)) return row;
        const { source_ids, ...rest } = row as Record<string, unknown>;
        return rest;
      }),
    },
  };
}

function shape(value: unknown, fieldName = ""): Shape {
  if (volatileFields.has(fieldName) || fieldName.endsWith("_path")) {
    return { type: typeName(value, fieldName), value: "<masked>" };
  }
  if (value !== null && Array.isArray(value)) {
    return {
      type: "array",
      length: value.length,
      items: uniqueShapes(value.map((item) => shape(item))),
    };
  }
  if (value !== null && typeof value === "object") {
    const objectValue = value as Record<string, unknown>;
    const keys = Object.keys(objectValue).sort();
    return {
      type: "object",
      keys,
      fields: Object.fromEntries(keys.map((key) => [key, shape(objectValue[key], key)])),
    };
  }
  if (enumFields.has(fieldName)) {
    return { type: typeName(value, fieldName), value };
  }
  return { type: typeName(value, fieldName) };
}

function typeName(value: unknown, fieldName = ""): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "list";
  if (floatFields.has(fieldName) && typeof value === "number") return "float";
  switch (typeof value) {
    case "boolean":
      return "bool";
    case "number":
      return Number.isInteger(value) ? "int" : "float";
    case "string":
      return "str";
    default:
      return typeof value;
  }
}

function uniqueShapes(shapes: Shape[]): Shape[] {
  const seen = new Set<string>();
  const result: Shape[] = [];
  for (const item of shapes) {
    const serialized = stableStringify(item);
    if (seen.has(serialized)) continue;
    seen.add(serialized);
    result.push(item);
  }
  return result;
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  const entries = Object.entries(value as Record<string, unknown>).sort(([left], [right]) => left.localeCompare(right));
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${stableStringify(item)}`).join(",")}}`;
}

async function applySchema(db: D1Database): Promise<void> {
  await applySqlText(db, await readFile(schemaPath, "utf8"));
  await resetDatabase(db);
}

async function applySqlFile(db: D1Database, filePath: string): Promise<void> {
  await applySqlText(db, await readFile(filePath, "utf8"));
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

function maskVolatile(value: unknown, fieldName = ""): unknown {
  if (volatileFields.has(fieldName) || fieldName.endsWith("_path")) {
    return "<masked>";
  }
  if (Array.isArray(value)) {
    return value.map((item) => maskVolatile(item));
  }
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, maskVolatile(item, key)]),
    );
  }
  return value;
}
