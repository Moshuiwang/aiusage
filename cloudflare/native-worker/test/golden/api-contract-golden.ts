/**
 * #74 P1：`tests/fixtures/contract/api_contract_golden.json` 的 owner。
 *
 * 这份是 **shape golden**：非枚举标量只记类型不记值，守的是 HTTP 合同本身——
 * path / method / status code / content-type / JSON 字段结构。少一个字段、字段类型变了、
 * 数组从有元素变成空，都必须变红。
 *
 * 以前它由 Python `tests/test_api_contract.py` 起 `server.py` 实录。#67 把服务端权威
 * 转移到 Worker 之后，实录端跟着转移到这里：同一份场景改为打真实 Worker 路由。
 *
 * 场景是**三段有状态的剧本**，顺序不能改：
 *   1. 空库：未认证面、登录面、静态资源面、`/ingest` 的错误与成功写入面。
 *   2. 灌入 canonical 用量事实：读端点（summary / mobile summary / health）。
 *   3. 灌入官方额度观测：额度写入面与「额度已入库」之后的读端点。
 */

import { withWorker, type RawRequest, type WorkerContext } from "./harness";
import { fixedNow, staleCollectedAt, timezone } from "./paths";
import { bodyContract, type Shape } from "./shape";

export type ContractRecord = {
  name: string;
  request: { method: string; path: string; auth: boolean };
  response: {
    status: number;
    content_type: string;
    location: string | null;
    body: Shape;
  };
};

/** 场景里被灌入的两台设备。名字被 machine / account 过滤请求直接引用，改名会让那几条读空。 */
const macLocal = {
  runId: 101,
  sourceId: "mac-local",
  host: "macbook-pro",
  machine: "macbook-pro",
  osUser: "alice",
  platform: "darwin",
  agent: "claude",
  model: "claude-sonnet",
};
const linuxDevBob = {
  runId: 102,
  sourceId: "linux-dev-bob",
  host: "linux-dev",
  machine: "linux-dev",
  osUser: "bob",
  platform: "linux",
  agent: "codex",
  model: "gpt-5",
};

export async function collectApiContractRecords(): Promise<ContractRecord[]> {
  return withWorker({ now: fixedNow }, async (ctx) => {
    const records: ContractRecord[] = [];
    const push = async (name: string, request: RawRequest) => {
      records.push(await record(ctx, name, request));
    };

    // ---- 第一段：空库上的认证面、登录面、静态资源面与写入面 ----------------
    await push("root-login-page", { method: "GET", path: "/" });
    await push("login-page", { method: "GET", path: "/login" });
    await push("static-css-requires-auth", { method: "GET", path: "/static/dashboard.css" });
    await push("static-css-authorized", { method: "GET", path: "/static/dashboard.css", auth: true });
    await push("static-missing-authorized", { method: "GET", path: "/static/missing.css", auth: true });
    await push("login-invalid-token", {
      method: "POST", path: "/login", body: "token=wrong",
      contentType: "application/x-www-form-urlencoded",
    });
    await push("login-valid-redirect", {
      method: "POST", path: "/login", body: `token=${encodeURIComponent("contract-test-token")}`,
      contentType: "application/x-www-form-urlencoded", followRedirects: false,
    });
    await push("summary-requires-auth", { method: "GET", path: "/api/summary?date=2026-06-03" });
    await push("mobile-summary-requires-auth", { method: "GET", path: "/api/mobile/summary?date=2026-06-03" });
    await push("health-requires-auth", { method: "GET", path: "/api/health" });

    await push("ingest-auth-failed", { method: "POST", path: "/ingest", auth: "wrong", body: usagePayload(macLocal, "2026-06-01", 1200, 500, 300) });
    await push("ingest-schema-invalid", { method: "POST", path: "/ingest", auth: true, body: { schema_version: 1, source_id: "broken" } });
    await push("ingest-success-day1", { method: "POST", path: "/ingest", auth: true, body: usagePayload(macLocal, "2026-06-01", 1200, 500, 300) });
    await push("ingest-idempotent-duplicate-day1", { method: "POST", path: "/ingest", auth: true, body: usagePayload(macLocal, "2026-06-01", 1200, 500, 300) });
    await push("ingest-success-day2", { method: "POST", path: "/ingest", auth: true, body: usagePayload(linuxDevBob, "2026-06-02", 1600, 900, 500) });
    await push("ingest-success-day3", { method: "POST", path: "/ingest", auth: true, body: usagePayload(macLocal, "2026-06-03", 2200, 600, 200) });

    // ---- 第二段：灌入 canonical 用量事实，再录读端点 -----------------------
    //
    // 为什么读端点不直接吃上面 `/ingest` 写进去的数据：那几个 payload 只带 legacy
    // `usage_daily`，Worker 的写模型只落 canonical `usage_hourly_facts`，
    // 于是读端点会全空——录出一份「什么都没有」的 golden，等于什么都没守。
    // 这里显式灌 canonical 事实，读端点才录得到真实结构。
    await seedCanonicalUsage(ctx.db);

    for (const period of ["today", "week", "month", "all"]) {
      await push(`summary-${period}-missing-limits`, { method: "GET", path: `/api/summary?date=2026-06-03&period=${period}`, auth: true });
      await push(`mobile-summary-${period}-missing-limits`, { method: "GET", path: `/api/mobile/summary?date=2026-06-03&period=${period}`, auth: true });
    }
    await push("summary-week-machine-filter", { method: "GET", path: "/api/summary?date=2026-06-03&period=week&machine=macbook-pro", auth: true });
    await push("summary-week-account-filter", { method: "GET", path: "/api/summary?date=2026-06-03&period=week&account=alice", auth: true });
    await push("mobile-summary-week-machine-filter", { method: "GET", path: "/api/mobile/summary?date=2026-06-03&period=week&machine=linux-dev", auth: true });
    await push("mobile-summary-week-account-filter", { method: "GET", path: "/api/mobile/summary?date=2026-06-03&period=week&account=bob", auth: true });
    await push("health-before-limits", { method: "GET", path: "/api/health", auth: true });

    // ---- 第三段：官方额度观测写入面，以及额度入库后的读端点 -----------------
    await push("ingest-limits-requires-auth", { method: "POST", path: "/ingest-limits", body: limitsPayload() });
    await push("ingest-limits-schema-invalid", { method: "POST", path: "/ingest-limits", auth: true, body: { schema_version: 1, windows: [] } });
    await push("ingest-limits-success-observed", { method: "POST", path: "/ingest-limits", auth: true, body: limitsPayload() });
    await push("summary-week-observed-limits", { method: "GET", path: "/api/summary?date=2026-06-03&period=week", auth: true });
    await push("mobile-summary-week-observed-limits", { method: "GET", path: "/api/mobile/summary?date=2026-06-03&period=week", auth: true });
    await push("health-after-limits", { method: "GET", path: "/api/health", auth: true });

    return records;
  });
}

async function record(ctx: WorkerContext, name: string, request: RawRequest): Promise<ContractRecord> {
  const response = await ctx.fetchRaw(request);
  return {
    name,
    request: {
      method: request.method,
      path: request.path,
      auth: Boolean(request.auth),
    },
    response: {
      status: response.status,
      content_type: response.contentType.split(";")[0],
      location: response.location,
      body: bodyContract(response.contentType, response.body),
    },
  };
}

/**
 * 灌入两台设备的 canonical 用量事实与来源健康状态。
 *
 * `linux-dev-bob` 的采集时刻刻意落在 120 分钟阈值以外：全新鲜的 fixture 下
 * 「折算」与「不折算」产出完全一样的 `source_status.counts`，`/api/health` 那条口径
 * 会在这份 golden 里静音。防陈旧守卫里有一条断言专门盯住这个场景不许消失。
 */
async function seedCanonicalUsage(db: D1Database): Promise<void> {
  await insertUsage(db, { ...macLocal, runId: 101, date: "2026-06-01", input: 1200, output: 500, cache: 300, collectedAt: fixedNow });
  await insertUsage(db, { ...linuxDevBob, runId: 102, date: "2026-06-02", input: 1600, output: 900, cache: 500, collectedAt: staleCollectedAt });
  await insertUsage(db, { ...macLocal, runId: 103, date: "2026-06-03", input: 2200, output: 600, cache: 200, collectedAt: fixedNow });
}

async function insertUsage(
  db: D1Database,
  row: {
    runId: number;
    sourceId: string;
    host: string;
    machine: string;
    osUser: string;
    platform: string;
    agent: string;
    model: string;
    date: string;
    input: number;
    output: number;
    cache: number;
    collectedAt: string;
  },
): Promise<void> {
  const total = row.input + row.output + row.cache;
  const dailyRaw = {
    agent: row.agent,
    period: row.date,
    inputTokens: row.input,
    outputTokens: row.output,
    cacheCreationTokens: row.cache,
    cacheReadTokens: 0,
    totalTokens: total,
    modelBreakdowns: [{
      modelName: row.model,
      inputTokens: row.input,
      outputTokens: row.output,
      cacheCreationTokens: row.cache,
      cacheReadTokens: 0,
      totalTokens: total,
    }],
  };
  const metadata = {
    ccusage_row: dailyRaw,
    machine: row.machine,
    host: row.host,
    account: row.osUser,
    platform: row.platform,
  };
  const accountId = `${row.agent}-${row.osUser}`;

  await db.batch([
    db.prepare(`
      INSERT INTO source_report_states (
        source_id, collected_at, report_type, command, status, ccusage_version,
        first_period, last_period, error_type, error_message
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(source_id) DO UPDATE SET
        collected_at = excluded.collected_at,
        first_period = excluded.first_period,
        last_period = excluded.last_period
    `).bind(row.sourceId, row.collectedAt, "daily", "HTTP Ingest", "ok", null, row.date, row.date, null, null),
    db.prepare(`
      INSERT INTO source_identities (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(source_id) DO UPDATE SET
        host=excluded.host, machine=excluded.machine, os_user=excluded.os_user,
        platform=excluded.platform, last_seen_at=excluded.last_seen_at
    `).bind(row.sourceId, row.host, row.machine, row.osUser, row.platform, fixedNow, fixedNow),
    db.prepare(`
      INSERT INTO machines (machine_id, machine_name, host, platform, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?)
      ON CONFLICT(machine_id) DO UPDATE SET
        machine_name=excluded.machine_name, host=excluded.host,
        platform=excluded.platform, last_seen_at=excluded.last_seen_at
    `).bind(row.machine, row.machine, row.host, row.platform, fixedNow, fixedNow),
    db.prepare(`
      INSERT OR IGNORE INTO ai_accounts (provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).bind(row.agent, accountId, row.osUser, row.osUser, null, fixedNow, fixedNow),
    db.prepare(`
      INSERT INTO usage_daily (
        source_id, date, agent, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, total_tokens, total_cost, metadata_json, raw_json, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      row.sourceId, row.date, row.agent, row.input, row.output, row.cache, 0, total, null,
      JSON.stringify(metadata), JSON.stringify(dailyRaw), fixedNow, fixedNow,
    ),
    db.prepare(`
      INSERT INTO usage_daily_models (
        source_id, date, agent, model_name, input_tokens, output_tokens,
        cache_creation_tokens, cache_read_tokens, total_tokens, cost, raw_json, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      row.sourceId, row.date, row.agent, row.model, row.input, row.output, row.cache, 0, total, null,
      JSON.stringify(dailyRaw.modelBreakdowns[0]), fixedNow, fixedNow,
    ),
    db.prepare(`
      INSERT INTO usage_hourly_facts (
        fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
        session_count, attribution_confidence, provenance, metadata_json, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      `fact-${row.runId}`, row.sourceId, row.machine, row.osUser, row.agent, accountId,
      row.agent, "test", `${row.date}T10:00:00+08:00`, `${row.date}T11:00:00+08:00`,
      timezone, row.input, row.output, row.cache, 0, 0, total,
      null, 1, 1, "observed", "test", JSON.stringify(metadata), fixedNow, fixedNow,
    ),
    db.prepare(`
      INSERT INTO usage_hourly_models (
        fact_id, model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        reasoning_output_tokens, total_tokens, total_cost, metadata_json, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      `fact-${row.runId}`, row.model, row.input, row.output, row.cache, 0, 0, total, null,
      JSON.stringify(dailyRaw.modelBreakdowns[0]), fixedNow, fixedNow,
    ),
  ]);
}

function usagePayload(
  device: { sourceId: string; host: string; machine: string; osUser: string; platform: string; agent: string; model: string },
  period: string,
  input: number,
  output: number,
  cache: number,
): Record<string, unknown> {
  const total = input + output + cache;
  return {
    schema_version: 1,
    source_id: device.sourceId,
    host: device.host,
    machine: device.machine,
    os_user: device.osUser,
    platform: device.platform,
    timezone,
    observed_at: `${period}T10:40:00+08:00`,
    collection_window: "daily",
    usage_daily: [{
      agent: device.agent,
      period,
      inputTokens: input,
      outputTokens: output,
      cacheCreationTokens: cache,
      cacheReadTokens: 0,
      totalTokens: total,
      modelBreakdowns: [{
        modelName: device.model,
        inputTokens: input,
        outputTokens: output,
        cacheCreationTokens: cache,
        cacheReadTokens: 0,
        totalTokens: total,
      }],
    }],
  };
}

function limitsPayload(): Record<string, unknown> {
  return {
    schema_version: 1,
    observed_at: "2026-06-03T11:00:00+08:00",
    windows: [
      {
        source_id: "codex-main",
        provider: "codex",
        window: "session",
        used_percent: 40,
        remaining_percent: 60,
        reset_at: "2026-06-03T16:00:00+08:00",
        window_duration_minutes: 300,
        observed_at: "2026-06-03T11:00:00+08:00",
        source_type: "runtime_api",
        confidence: "observed",
        status: "ok",
      },
      {
        source_id: "claude-weekly",
        provider: "claude",
        window: "week",
        used_percent: 0,
        remaining_percent: 0,
        reset_at: "2026-06-10T00:00:00+08:00",
        window_duration_minutes: 10080,
        observed_at: "2026-06-03T11:00:00+08:00",
        source_type: "oauth_usage_api",
        confidence: "missing",
        status: "provider_failed",
      },
    ],
  };
}
