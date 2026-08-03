import { readFile } from "node:fs/promises";
import { mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { Miniflare } from "miniflare";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { fixedNow, staleCollectedAt, token } from "./golden/paths";

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
const schemaPath = path.join(repoRoot, "cloudflare/migrations/0001_initial_schema.sql");
const seedSqlPath = path.join(repoRoot, "cloudflare/native-worker/test/seed.sql");
const workerEntry = path.join(repoRoot, "cloudflare/native-worker/src/index.ts");
// token / fixedNow / staleCollectedAt 从 golden 收集器那边 import，不在这里再抄一份：
// `staleCollectedAt` 是本文件的 seed 与合同 golden 的场景之间的**语义绑定**——
// 合同场景里必须有一台「超过 120 分钟没上报」的设备，否则过期折算这条口径
// 会退化成恒等变换，两边都报绿而实际什么都没守。各存一份就会悄悄漂开。

// 值 golden 的易变字段：与运行时刻绑定，重放必然不同，比对前统一抹掉。
// 口径与 `test/golden/shape.ts` 同源，那边是 golden 生成端的 owner。
const volatileFields = new Set([
  "accepted_at",
  "generated_at",
  "mtime",
  "path",
  "size_bytes",
  "updated_at",
]);

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

  // 原先这里有两条 golden 比对（api 合同 shape、value 全量深比对）。
  // #74 P1 把 golden 的生成端从 Python 读模型搬到 Worker 之后，
  // 「重新生成 + 与已提交 golden 逐条比对」由 `golden-freshness.test.ts` 统一承担——
  // 生成器与校验器共用 `test/golden/` 下的同一份收集器，不再各自持有一份重放逻辑。
  // 本文件保留的是 golden 覆盖不到的**行为不变量**：归档表不参与口径、
  // 历史回退稳定、小时事实查询有周期边界、额度失败即刻降级。

  it("keeps web and shared Apple mobile DTO summaries unchanged when archived legacy usage tables change", async () => {
    await mf.dispose();
    mf = await createMiniflare({ AIUSAGE_NOW: fixedNow });
    const db = await mf.getD1Database("AIUSAGE_DB");
    await applySchema(db);
    await applySqlFile(db, seedSqlPath);
    const { buildSummary } = await import("../src/read-model");
    const { buildMobileSummary } = await import("../src/mobile-summary");
    const requests = [
      ...["today", "week", "month", "all"].map((period) => ({
        date: "2026-06-03", period, timezone: "Asia/Shanghai", currentTime: fixedNow,
      })),
      {
        date: "2026-06-03", period: "week", timezone: "Asia/Shanghai",
        currentTime: fixedNow, machine: "macbook-pro",
      },
      {
        date: "2026-06-03", period: "week", timezone: "Asia/Shanghai",
        currentTime: fixedNow, account: "bob",
      },
    ];
    const before = [];
    for (const request of requests) {
      const web = await buildSummary(db, request);
      before.push({ web, mobile: buildMobileSummary(web) });
    }

    await db.batch([
      db.prepare("DELETE FROM usage_daily_models"),
      db.prepare("DELETE FROM usage_daily"),
      db.prepare("DELETE FROM usage_hourly"),
      db.prepare("DELETE FROM usage_blocks"),
    ]);

    const after = [];
    for (const request of requests) {
      const web = await buildSummary(db, request);
      after.push({ web, mobile: buildMobileSummary(web) });
    }
    expect(after).toEqual(before);
  });

  it("keeps a reviewed historical daily fallback stable when later detailed facts coexist", async () => {
    await mf.dispose();
    mf = await createMiniflare({ AIUSAGE_NOW: fixedNow });
    const db = await mf.getD1Database("AIUSAGE_DB");
    await applySchema(db);
    await applySqlFile(db, seedSqlPath);
    await db.prepare(`
      INSERT INTO usage_daily_rollups (
        date, bucket_start, bucket_end, source_id, machine_id, os_user,
        ai_provider, ai_account_id, agent, client, attribution_confidence,
        provenance, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, reasoning_output_tokens, total_tokens,
        event_count, session_count, fact_count
      )
      SELECT substr(window_start, 1, 10),
             substr(window_start, 1, 10) || 'T00:00:00+08:00',
             substr(window_start, 1, 10) || 'T23:59:59+08:00',
             source_id, machine_id, os_user, ai_provider, ai_account_id, agent,
             client, attribution_confidence, provenance, sum(input_tokens),
             sum(output_tokens), sum(cache_creation_tokens), sum(cache_read_tokens),
             sum(reasoning_output_tokens), sum(total_tokens), sum(event_count),
             sum(session_count), count(*)
      FROM usage_hourly_facts
      GROUP BY substr(window_start, 1, 10), source_id, machine_id, os_user,
               ai_provider, ai_account_id, agent, client,
               attribution_confidence, provenance
    `).run();
    await db.prepare(`
      INSERT INTO usage_daily_rollups (
        date, bucket_start, bucket_end, source_id, machine_id, os_user,
        ai_provider, ai_account_id, agent, client, attribution_confidence,
        provenance, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, reasoning_output_tokens, total_tokens,
        event_count, session_count, fact_count
      ) VALUES (
        '2026-05-29', '2026-05-29T00:00:00+08:00',
        '2026-05-29T23:59:59+08:00', 'mac-local', 'macbook-pro', 'alice',
        'claude', 'claude-main', 'claude', 'legacy_daily_archive',
        'legacy_identity_mapped', 'historical_ccusage_fallback_v1',
        1500, 600, 400, 0, 0, 2500, 0, 0, 0
      )
    `).run();

    const { buildSummary } = await import("../src/read-model");
    for (const request of [
      { date: "2026-06-03", period: "all", timezone: "Asia/Shanghai", currentTime: fixedNow },
      {
        date: "2026-06-03", period: "all", timezone: "Asia/Shanghai",
        currentTime: fixedNow, machine: "macbook-pro",
      },
      {
        date: "2026-06-03", period: "all", timezone: "Asia/Shanghai",
        currentTime: fixedNow, account: "alice",
      },
    ]) {
      const summary = await buildSummary(db, request);
      const item = (summary.items as Shape[]).find((row) =>
        row.source_id === "mac-local" && row.date === "2026-05-29" && row.agent === "claude"
      );
      expect(item?.total_tokens).toBe(2500);
      expect(item?.model_breakdowns).toEqual([]);
    }

    await db.prepare(`
      INSERT INTO usage_daily_rollups (
        date, bucket_start, bucket_end, source_id, machine_id, os_user,
        ai_provider, ai_account_id, agent, client, attribution_confidence,
        provenance, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, reasoning_output_tokens, total_tokens,
        event_count, session_count, fact_count
      ) VALUES (
        '2026-06-01', '2026-06-01T00:00:00+08:00',
        '2026-06-01T23:59:59+08:00', 'workstation-cara', 'workstation-9',
        'cara', 'antigravity', 'ag-main', 'all', 'legacy_daily_archive',
        'legacy_identity_mapped', 'historical_ccusage_fallback_v1',
        900, 350, 100, 50, 0, 1400, 0, 0, 0
      )
    `).run();
    for (const request of [
      { date: "2026-06-03", period: "week", timezone: "Asia/Shanghai", currentTime: fixedNow },
      {
        date: "2026-06-03", period: "week", timezone: "Asia/Shanghai",
        currentTime: fixedNow, machine: "workstation-9",
      },
      {
        date: "2026-06-03", period: "week", timezone: "Asia/Shanghai",
        currentTime: fixedNow, account: "cara",
      },
    ]) {
      const summary = await buildSummary(db, request);
      const sourceDateItems = (summary.items as Shape[]).filter((row) =>
        row.source_id === "workstation-cara" && row.date === "2026-06-01"
      );
      expect(sourceDateItems).toEqual([
        expect.objectContaining({ agent: "all", total_tokens: 1400, model_breakdowns: [] }),
      ]);
    }

    await db.prepare(`
      INSERT INTO usage_hourly_rollups (
        bucket_start, bucket_end, source_id, machine_id, os_user, ai_provider,
        ai_account_id, agent, client, attribution_confidence, provenance,
        input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        reasoning_output_tokens, total_tokens, event_count, session_count, fact_count
      ) VALUES (
        '2026-05-29T09:00:00+08:00', '2026-05-29T10:00:00+08:00',
        'mac-local', 'macbook-pro', 'alice', 'claude', 'claude-main', 'claude',
        'legacy_hourly_archive', 'legacy_identity_mapped',
        'legacy_hourly_archive_backfill_v1', 1500, 600, 400, 0, 0, 2500, 0, 0, 1
      )
    `).run();
    const historicalToday = await buildSummary(db, {
      date: "2026-05-29", period: "today", timezone: "Asia/Shanghai", currentTime: fixedNow,
    });
    const historicalItem = (historicalToday.items as Shape[]).find((row) =>
      row.source_id === "mac-local" && row.date === "2026-05-29" && row.agent === "claude"
    );
    expect(historicalItem?.total_tokens).toBe(2500);
  });

  it("bounds the hourly-fact query to the requested display period", async () => {
    const db = await mf.getD1Database("AIUSAGE_DB");
    const queries: string[] = [];
    const tracedDb = new Proxy(db, {
      get(target, property, receiver) {
        if (property !== "prepare") return Reflect.get(target, property, receiver);
        return (sql: string) => {
          queries.push(sql);
          return target.prepare(sql);
        };
      },
    }) as unknown as D1Database;

    const summary = await import("../src/read-model");
    await summary.buildSummary(tracedDb, {
      date: "2026-06-03", period: "week", timezone: "Asia/Shanghai", currentTime: fixedNow,
    });

    const hourlyQuery = queries.find((sql) => sql.includes("FROM usage_hourly_facts"));
    expect(hourlyQuery).toContain("f.window_start >= ?");
    expect(hourlyQuery).toContain("f.window_start < ?");
    const usageQueries = queries.join("\n");
    for (const archivedTable of ["usage_daily", "usage_daily_models", "usage_hourly", "usage_blocks"]) {
      expect(usageQueries).not.toMatch(new RegExp(`(?:FROM|JOIN)\\s+${archivedTable}\\b`));
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

  it("does not mix archived all-agent daily residuals into canonical facts", async () => {
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

    expect((mobile.period as Shape).total_tokens).toBe(400);
    expect(((mobile.breakdown as Shape).by_agent as Shape[])).toEqual([
      expect.objectContaining({ id: "codex", tokens: 400 }),
    ]);
  });

  // 这里曾经有一条 "does not mix archived ccusage block snapshots into today's hourly trend"，
  // 已随 ccusage block 读路径一起删除：它插入 usage_blocks 行、再断言某个小时点是 0，
  // 而 `blockRows` 从来就是空数组、`usage_blocks` 表从来没被读模型查询过——
  // 这条断言**由构造恒成立**，什么都没守。判定见 #90。

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
      AIUSAGE_CACHE_NAMESPACE: crypto.randomUUID(),
      AIUSAGE_DISABLE_SUMMARY_CACHE: "true",
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
    // Issue #77：合同场景里这台设备的采集时刻落在 120 分钟阈值以外
    // （与 `test/golden/paths.ts` 的 `staleCollectedAt` 同一个值）。
    // 这里必须造出同一个场景，否则本文件的来源永远新鲜、status 恒为 ok，
    // 而合同 golden 说 stale——「过期折算」这条口径就会在这里静音。
    // 用固定时刻而不是 `new Date()`：它相对真实当前时间、相对 fixedNow(2026-06-03T12:00)、
    // 相对 provider-failure 用例的 2026-06-03T10:31 都超过 120 分钟，三种参照下都判 stale。
    collectedAt: staleCollectedAt,
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
    /** 采集时刻。省略即用 `now`（新鲜来源）；传旧时刻可造出「超过 120 分钟没上报」的来源。 */
    collectedAt?: string;
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
  // 只回拨采集时刻这一列（其余 first_seen_at / last_seen_at / 用量行仍用 now），
  // 与 Python 侧 `_backdate_source_collection` 只改 collection_runs.collected_at 同口径。
  // 读模型的来源健康取 source_report_states.collected_at（read-model.ts buildSummary），
  // 所以两张表都要跟着回拨，否则场景造不出来。
  const collectedAt = row.collectedAt ?? row.now;
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
      .bind(row.runId, collectedAt, "Asia/Shanghai", "0.1.0", "ok"),
    db.prepare(`
      INSERT INTO source_reports (
        id, run_id, source_id, report_type, command, status, ccusage_version,
        first_period, last_period, error_type, error_message
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(row.runId, row.runId, row.sourceId, "daily", "HTTP Ingest", "ok", null, row.period, row.period, null, null),
    db.prepare(`
      INSERT INTO source_report_states (
        source_id, collected_at, report_type, command, status, ccusage_version,
        first_period, last_period, error_type, error_message
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(source_id) DO UPDATE SET
        collected_at = excluded.collected_at,
        report_type = excluded.report_type,
        command = excluded.command,
        status = excluded.status,
        ccusage_version = excluded.ccusage_version,
        first_period = excluded.first_period,
        last_period = excluded.last_period,
        error_type = excluded.error_type,
        error_message = excluded.error_message
      WHERE excluded.collected_at >= source_report_states.collected_at
    `).bind(row.sourceId, collectedAt, "daily", "HTTP Ingest", "ok", null, row.period, row.period, null, null),
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
    db.prepare(`
      INSERT INTO machines (
        machine_id, machine_name, host, platform, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?)
      ON CONFLICT(machine_id) DO UPDATE SET
        machine_name=excluded.machine_name,
        host=excluded.host,
        platform=excluded.platform,
        last_seen_at=excluded.last_seen_at
    `).bind(row.machine, row.machine, row.host, row.platform, row.now, row.now),
    db.prepare(`
      INSERT OR IGNORE INTO ai_accounts (
        provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?)
    `).bind(row.agent, `${row.agent}-${row.osUser}`, row.osUser, row.osUser, null, row.now, row.now),
    db.prepare(`
      INSERT INTO usage_hourly_facts (
        fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
        session_count, attribution_confidence, provenance, metadata_json, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      `fact-${row.runId}`, row.sourceId, row.machine, row.osUser, row.agent, `${row.agent}-${row.osUser}`,
      row.agent, "test", `${row.period}T12:00:00+08:00`, `${row.period}T13:00:00+08:00`,
      "Asia/Shanghai", row.inputTokens, row.outputTokens, row.cacheTokens, 0, 0, totalTokens,
      null, 1, 1, "observed", "test", JSON.stringify(metadata), row.now, row.now,
    ),
    db.prepare(`
      INSERT INTO usage_hourly_models (
        fact_id, model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        reasoning_output_tokens, total_tokens, total_cost, metadata_json, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      `fact-${row.runId}`, row.model, row.inputTokens, row.outputTokens, row.cacheTokens,
      0, 0, totalTokens, null, JSON.stringify(dailyRaw.modelBreakdowns[0]), row.now, row.now,
    ),
  ]);
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
