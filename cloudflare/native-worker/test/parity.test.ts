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
// 与 Python 合同场景 `tests/test_api_contract.py::STALE_COLLECTED_AT` 保持同一个值：
// 合同 fixture 里必须有一台「超过 120 分钟没上报」的设备，否则过期折算这条口径
// 在两侧都退化成恒等变换，parity 会一直报绿而实际什么都没守。
const staleCollectedAt = "2026-06-03T08:00:00+08:00";

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

// #74 P2：`api_contract_golden.json` 是 **shape golden**——非枚举标量只记 type 不记 value，
// 所以浮点字段（used_percent / remaining_percent）在这份 golden 里只以 {"type":"float"} 出现，
// 全文没有一处 float 带 value。这里因此不需要（也不该加）浮点容差比较：
// 数值口径由下一条测试的 value_golden.json 全量深比对守护。
//
// 下面这份清单是 web `/api/summary` 7 条记录与 Python golden 之间**仅有的**字段级差异，
// 根因只有一个 fixture 事实：这份 golden 由 Python server 实录，数据全部经 Python `/ingest`
// 的 legacy `usage_daily` 路径写入，从不产生 canonical 小时事实与 `ai_accounts` 行；
// 而 Worker 读模型只读 canonical 事实（见本文件 "does not mix archived ..." 几条）。
// 于是 golden 在这几棵子树上记录的是空数组，Worker 侧非空——差异全部落在数组 length 上。
//
// 必须说清这条清单的**代价**（早先注释写成「字段名、类型、枚举值逐条一致」，那句话不成立）：
// `walkDiff` 在数组长度不等时 push `|len` 后**直接 return**，不再进入元素比对；
// 而 golden 这几棵子树是 `{"items": [], "length": 0}`，根本没有元素形状可比。
// 所以这几棵子树的**元素结构在本条测试里完全没有被比对过**——
// 例如把 read-model 的 `ai_accounts.label` 改名，本条测试是绿的（已实测）。
// 覆盖由下一条 `matches Python value golden` 的全量深比对提供：它跑在 canonical seed 上，
// `ai_accounts` / `account_hourly.by_*` / `confidence_breakdown` / `trend.by_agent` 全部非空，
// 同一个改名变异在那里会红（也已实测）。这是分工，不是缺口，但不要误以为本条守住了它们。
//
// 这不是实现缺陷：同样由 Python 读模型生成、但跑在 canonical seed 上的 value_golden.json，
// `ai_accounts` 与 `account_hourly.by_*` 同样非空，且 Worker 与它全量深比对通过。
//
// 清单是**精确集合**而非模式匹配：多一条、少一条、换个路径、换个差异类型都会红。
// 等 #74 P1 交出 Worker 侧的 golden 生成器并重新生成 golden，这些差异会消失，
// 届时本清单会因为「差异不再存在」而变红，正好强制把它删掉。
const legacyDailyFixtureGaps = [
  ".response.body.shape.fields.account_hourly.fields.by_agent.items|len",
  ".response.body.shape.fields.account_hourly.fields.by_agent.length|value",
  ".response.body.shape.fields.account_hourly.fields.by_ai_account.items|len",
  ".response.body.shape.fields.account_hourly.fields.by_ai_account.length|value",
  ".response.body.shape.fields.account_hourly.fields.by_machine.items|len",
  ".response.body.shape.fields.account_hourly.fields.by_machine.length|value",
  ".response.body.shape.fields.account_hourly.fields.by_os_user.items|len",
  ".response.body.shape.fields.account_hourly.fields.by_os_user.length|value",
  ".response.body.shape.fields.account_hourly.fields.confidence_breakdown.items|len",
  ".response.body.shape.fields.account_hourly.fields.confidence_breakdown.length|value",
  ".response.body.shape.fields.ai_accounts.items|len",
  ".response.body.shape.fields.ai_accounts.length|value",
];
// today 期额外多两条：Python 的当日趋势按小时聚合，legacy fixture 没有小时数据，
// 所以 golden 的 trend.by_agent 是空的；Worker 从 canonical 小时事实聚合出 1 个 agent。
const todayTrendFixtureGaps = [
  ...legacyDailyFixtureGaps,
  ".response.body.shape.fields.trend.fields.by_agent.items|len",
  ".response.body.shape.fields.trend.fields.by_agent.length|value",
].sort();
const knownGoldenGaps = new Map<string, string[]>([
  ["summary-today-missing-limits", todayTrendFixtureGaps],
  ["summary-week-missing-limits", legacyDailyFixtureGaps],
  ["summary-month-missing-limits", legacyDailyFixtureGaps],
  ["summary-all-missing-limits", legacyDailyFixtureGaps],
  ["summary-week-machine-filter", legacyDailyFixtureGaps],
  ["summary-week-account-filter", legacyDailyFixtureGaps],
  ["summary-week-observed-limits", legacyDailyFixtureGaps],
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

  it("keeps authentication and JSON surface contracts for summary read paths", async () => {
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

    // #74 P2：这里曾经只对前 2 条做全字段 toEqual，其余 14 条只校
    // status / content_type / body.kind——等于那 14 条的字段级合同无人看守：
    // 少一个字段、字段类型变了、数组长度变了，测试都不会红。Python 平行实现删除后
    // 这份 golden 是唯一的合同守卫，所以 16 条一律逐字段比对。
    expect(records.length, "契约记录条数（新增记录必须同时进入全字段比对）").toBe(16);
    expect(
      [...knownGoldenGaps.keys()].filter((name) => !records.some((row) => row.name === name)),
      "已知缺口清单不得引用不存在的记录",
    ).toEqual([]);
    for (const actual of records) {
      const wanted = expected.get(actual.name);
      expect(wanted, `${actual.name} exists in Python golden`).toBeTruthy();
      expect(
        structuralDiff(actual, wanted),
        `${actual.name} 与 Python golden 的字段级差异必须与已知 fixture 缺口完全一致`,
      ).toEqual(knownGoldenGaps.get(actual.name) ?? []);
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
    expect(sortedSourceRows(summaryWeek.source_status), "Native source_status must be covered by value parity").toEqual(
      sortedSourceRows(bodyFor(golden, "summary-week").source_status),
    );
    expect(sortedSourceRows(mobileSummaryWeek.sources), "Native mobile sources must be covered by value parity").toEqual(
      sortedSourceRows(bodyFor(golden, "mobile-summary-week").sources),
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

  it("does not mix archived ccusage block snapshots into today's hourly trend", async () => {
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
    expect(eight).toEqual(expect.objectContaining({ tokens: 0 }));
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

// 逐字段结构化比对：返回排序后的差异路径清单（空数组 = 完全一致）。
// 差异种类刻意分开标注，"字段存在但值是 null / 空对象 / 空数组" 这类绕过路径分别落在
// |type（null 与 str 的 type 名不同）、|key（keys 不同）、|len（数组长度不同）上，
// 不会被当成一致。
function structuralDiff(actual: unknown, expectedValue: unknown): string[] {
  const diffs: string[] = [];
  walkDiff(actual, expectedValue, "", diffs);
  return diffs.sort();
}

function walkDiff(actual: unknown, expectedValue: unknown, jsonPath: string, diffs: string[]): void {
  if (valueKind(actual) !== valueKind(expectedValue)) {
    diffs.push(`${jsonPath}|type`);
    return;
  }
  if (Array.isArray(actual) && Array.isArray(expectedValue)) {
    if (actual.length !== expectedValue.length) {
      diffs.push(`${jsonPath}|len`);
      return;
    }
    actual.forEach((item, index) => walkDiff(item, expectedValue[index], `${jsonPath}[${index}]`, diffs));
    return;
  }
  if (actual !== null && typeof actual === "object") {
    const left = actual as Record<string, unknown>;
    const right = expectedValue as Record<string, unknown>;
    for (const key of [...new Set([...Object.keys(left), ...Object.keys(right)])].sort()) {
      if (!(key in left) || !(key in right)) {
        diffs.push(`${jsonPath}.${key}|key`);
        continue;
      }
      walkDiff(left[key], right[key], `${jsonPath}.${key}`, diffs);
    }
    return;
  }
  if (!Object.is(actual, expectedValue)) diffs.push(`${jsonPath}|value`);
}

function valueKind(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

function bodyFor(records: ContractRecord[], name: string): Shape {
  const record = records.find((item) => item.name === name);
  expect(record, `${name} record exists`).toBeTruthy();
  return record?.response.body as Shape;
}

function normalizeStoreMetadata(value: unknown, fieldName = ""): unknown {
  if (Array.isArray(value)) {
    const normalized = value.map((item) => normalizeStoreMetadata(item));
    return fieldName === "source_status" || fieldName === "sources" ? sortedSourceRows(normalized) : normalized;
  }
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key,
        key === "backend_mode" || key === "canonical_store" ? "<store-specific>" : normalizeStoreMetadata(item, key),
      ]),
    );
  }
  return value;
}

function sortedSourceRows(value: unknown): unknown[] {
  return Array.isArray(value)
    ? [...value].sort((left, right) => String((left as Shape).source_id ?? "").localeCompare(String((right as Shape).source_id ?? "")))
    : [];
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
    // Issue #77：Python 合同场景把这台设备的采集时刻回拨到 120 分钟阈值以外
    // （`tests/test_api_contract.py::_backdate_source_collection`，STALE_COLLECTED_AT）。
    // 这里必须造出同一个场景，否则 Worker 侧这台来源永远新鲜、status 恒为 ok，
    // 而 golden 说 stale——「过期折算」这条口径就会在 parity 里静音。
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
