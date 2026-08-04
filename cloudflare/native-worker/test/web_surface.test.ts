import { createHmac } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { Miniflare } from "miniflare";
import { beforeEach, describe, expect, it } from "vitest";
import { acquireWorker, applySchema, bundleWorker } from "./golden/harness";
import { apiContractGoldenPath, fixedNow, repoRoot, token } from "./golden/paths";

const staticRoot = path.join(repoRoot, "cloudflare/native-worker/static");
// 仅属于登录 Cookie 行为测试，不是 golden 合同的共享输入。
const sessionSecret = "cutover-session-secret";

describe.sequential("native TS Worker web surface", () => {
  let mf: Miniflare;

  beforeEach(async () => {
    mf = await acquire({
      AIUSAGE_TOKEN: token,
      AIUSAGE_TOKEN_SPECS: "second:second-contract-test-token",
      AIUSAGE_SESSION_SECRET: sessionSecret,
      AIUSAGE_NOW: fixedNow,
      AIUSAGE_BACKEND_MODE: "native_d1_production",
    });
    const db = await mf.getD1Database("AIUSAGE_DB");
    await seedMinimalUsage(db);
    await seedHealthRows(db);
  });

  it("issues the stable session cookie value inherited from the Python cutover era on login", async () => {
    const expectedValue = await expectedSessionCookieValue(sessionSecret);
    const response = await mf.dispatchFetch("http://native.test/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({ token }).toString(),
      redirect: "manual",
    });

    expect(response.status).toBe(303);
    expect(response.headers.get("Location")).toBe("/dashboard");
    expect(response.headers.get("Set-Cookie")).toBe(
      `ai_usage_session=${expectedValue}; Max-Age=2592000; Path=/; HttpOnly; Secure; SameSite=Lax`,
    );
  });

  it("rejects invalid login and renders the Python-style error page", async () => {
    const response = await mf.dispatchFetch("http://native.test/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: "wrong-token" }),
    });

    expect(response.status).toBe(401);
    expect(response.headers.get("Content-Type")).toBe("text/html; charset=utf-8");
    expect(await response.text()).toContain('<p class="error">Invalid token</p>');
  });

  it("serves login page before auth and dashboard HTML after cookie auth", async () => {
    const expectedLogin = (await readStatic("login.html")).replace("{{ERROR_BLOCK}}", "");
    const expectedDashboard = await readStatic("index.html");
    const cookie = await sessionCookieHeader();

    const publicRoot = await mf.dispatchFetch("http://native.test/");
    const publicDashboard = await mf.dispatchFetch("http://native.test/dashboard");
    const authenticatedRoot = await mf.dispatchFetch("http://native.test/", {
      headers: { Cookie: cookie },
    });
    const authenticatedDashboard = await mf.dispatchFetch("http://native.test/dashboard", {
      headers: { Cookie: cookie },
    });

    expect(publicRoot.status).toBe(200);
    expect(publicRoot.headers.get("Content-Type")).toBe("text/html; charset=utf-8");
    expect(await publicRoot.text()).toBe(expectedLogin);
    expect(await publicDashboard.text()).toBe(expectedLogin);
    expect(authenticatedRoot.status).toBe(200);
    expect(authenticatedRoot.headers.get("Cache-Control")).toBe("no-cache");
    expect(await authenticatedRoot.text()).toBe(expectedDashboard);
    expect(await authenticatedDashboard.text()).toBe(expectedDashboard);
  });

  it("serves static assets byte-for-byte from cloudflare/native-worker/static behind session auth", async () => {
    const cookie = await sessionCookieHeader();

    for (const asset of ["dashboard.css", "dashboard.js", "index.html", "login.html"]) {
      const unauthenticated = await mf.dispatchFetch(`http://native.test/static/${asset}`);
      expect(unauthenticated.status).toBe(401);

      const response = await mf.dispatchFetch(`http://native.test/static/${asset}`, {
        headers: { Cookie: cookie },
      });

      expect(response.status).toBe(200);
      expect(response.headers.get("Cache-Control")).toBe("no-cache");
      expect(await response.text()).toBe(await readStatic(asset));
    }
  });

  it("protects health with the same session cookie and keeps the M0 response shape", async () => {
    const unauthenticated = await mf.dispatchFetch("http://native.test/api/health");
    expect(unauthenticated.status).toBe(401);

    const response = await mf.dispatchFetch("http://native.test/api/health", {
      headers: { Cookie: await sessionCookieHeader() },
    });
    const payload = await response.json<Record<string, unknown>>();

    expect(response.status).toBe(200);
    expect(payload).toMatchObject({
      status: "ok",
      generated_at: fixedNow,
      backend_mode: "native_d1_production",
      canonical_store: "cloudflare_d1",
      database: {
        path: "D1:AIUSAGE_DB",
        exists: true,
      },
      snapshot: {
        path: "D1:latest-snapshot-metadata",
        exists: true,
        updated_at: "2026-06-03T11:55:00+08:00",
      },
      source_status: {
        total: 2,
        counts: { ok: 1, provider_failed: 1 },
        non_ok: [{ source_id: "linux-dev-bob", status: "provider_failed" }],
      },
      limits: {
        latest_observed_at: null,
        effective_window_count: 0,
        raw_window_count: 0,
        stale_window_count: 0,
      },
    });
    expect(payload.database).toHaveProperty("size_bytes");
  });

  // Issue #77：`/api/health` 的 `source_status.counts` / `non_ok` 必须数**过期折算后**的
  // status，与 Python 的 `snapshot_source_health._status_with_staleness()` 同一口径
  // （阈值 120 分钟，`diff > threshold` 才算 stale，参照时刻取 `AIUSAGE_NOW`）。
  //
  // 折算前后必须真的不同，否则这条覆盖等于没加：所以 fixture 里同时放了
  //   - `boundary-fresh-source`：正好 120 分钟，**不**折算（守住 `>` 不能写成 `>=`）
  //   - `stale-source`：121 分钟，折算成 stale（行上原始 status 是 ok）
  // 用原始口径跑这段会得到 `{ok: 3, provider_failed: 1}` 且 non_ok 只有一条。
  it("counts health source_status with staleness folded in, matching the Python caliber", async () => {
    const db = await mf.getD1Database("AIUSAGE_DB");
    await db.batch([
      db.prepare(`
        INSERT INTO source_report_states (
          source_id, collected_at, report_type, command, status, ccusage_version,
          first_period, last_period, error_type, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind("boundary-fresh-source", "2026-06-03T10:00:00+08:00", "daily", "HTTP Ingest", "ok", null, null, null, null, null),
      db.prepare(`
        INSERT INTO source_report_states (
          source_id, collected_at, report_type, command, status, ccusage_version,
          first_period, last_period, error_type, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind("stale-source", "2026-06-03T09:59:00+08:00", "daily", "HTTP Ingest", "ok", null, null, null, null, null),
    ]);

    const response = await mf.dispatchFetch("http://native.test/api/health", {
      headers: { Cookie: await sessionCookieHeader() },
    });
    const payload = await response.json<Record<string, any>>();

    expect(payload.source_status.total).toBe(4);
    expect(payload.source_status.counts).toEqual({ ok: 2, provider_failed: 1, stale: 1 });
    expect(payload.source_status.non_ok).toEqual([
      { source_id: "linux-dev-bob", status: "provider_failed" },
      { source_id: "stale-source", status: "stale" },
    ]);

    // 同一份响应内两处 status 必须是同一口径：counts 数到的 stale，
    // 在 versions.needs_attention 里也得是 stale（#63 起该块已走折算）。
    const attention = new Map(
      (payload.versions.needs_attention as Array<Record<string, unknown>>).map((row) => [row.source_id, row]),
    );
    expect(attention.get("stale-source")?.status).toBe("stale");
    expect(attention.get("boundary-fresh-source")?.status).toBe("ok");
  });

  // Issue #77 的口径覆盖：直接拿已提交的合同 golden 比形状。
  // #74 P1 之后这份 golden 由 Worker 自己实录（`test/golden/api-contract-golden.ts`），
  // 不再是 Python 产出——所以这条已经不是跨实现比对，而是「读端点当前输出必须与
  // 已提交合同一致」的回归。golden 里 `health-*` 场景带一台超过 120 分钟没上报的设备
  // （收集器的 `staleCollectedAt`），所以 counts 的键含 "stale"、non_ok 里有一条 stale。
  // Worker 不折算时只会产出 ["ok"] 和空 non_ok，这里必红。
  it("reproduces the committed contract golden shape for /api/health source_status", async () => {
    const golden = JSON.parse(await readFile(apiContractGoldenPath, "utf8")) as Array<Record<string, any>>;
    const goldenHealth = golden.find((record) => record.name === "health-after-limits");
    expect(goldenHealth, "golden 里应当有 health-after-limits").toBeTruthy();
    const expectedShape = goldenHealth!.response.body.shape.fields.source_status;
    // 绕过路径守卫：golden 一旦退回全新鲜数据，这条覆盖就什么都不守了，必须先炸在这里。
    expect(expectedShape.fields.counts.keys, "golden 的 health 场景必须含过期设备").toContain("stale");

    const db = await mf.getD1Database("AIUSAGE_DB");
    // 对齐 Python 合同场景的来源分布：mac-local 新鲜 ok，linux-dev-bob 超阈值。
    await db.prepare("DELETE FROM source_report_states").run();
    await db.batch([
      db.prepare(`
        INSERT INTO source_report_states (
          source_id, collected_at, report_type, command, status, ccusage_version,
          first_period, last_period, error_type, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind("mac-local", "2026-06-03T11:55:00+08:00", "daily", "HTTP Ingest", "ok", null, "2026-06-03", "2026-06-03", null, null),
      db.prepare(`
        INSERT INTO source_report_states (
          source_id, collected_at, report_type, command, status, ccusage_version,
          first_period, last_period, error_type, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind("linux-dev-bob", "2026-06-03T08:00:00+08:00", "daily", "HTTP Ingest", "ok", null, "2026-06-02", "2026-06-02", null, null),
    ]);

    const response = await mf.dispatchFetch("http://native.test/api/health", {
      headers: { Cookie: await sessionCookieHeader() },
    });
    const payload = await response.json<Record<string, any>>();

    expect(contractShape(payload.source_status)).toEqual(expectedShape);
  });

  it("does not read archived legacy usage tables for the health database-size proxy", async () => {
    const cookie = await sessionCookieHeader();
    const beforeResponse = await mf.dispatchFetch("http://native.test/api/health", {
      headers: { Cookie: cookie },
    });
    const before = await beforeResponse.json() as Record<string, any>;
    const db = await mf.getD1Database("AIUSAGE_DB");
    await db.batch([
      db.prepare(`
        INSERT INTO usage_daily (
          source_id, date, agent, input_tokens, output_tokens, cache_creation_tokens,
          cache_read_tokens, total_tokens, total_cost, first_seen_at, last_seen_at
        ) VALUES ('archive-health', '2026-01-01', 'codex', 1, 0, 0, 0, 1, 0, '2026-01-01', '2026-01-01')
      `),
      db.prepare(`
        INSERT INTO usage_daily_models (
          source_id, date, agent, model_name, input_tokens, output_tokens,
          cache_creation_tokens, cache_read_tokens, total_tokens, cost, first_seen_at, last_seen_at
        ) VALUES ('archive-health', '2026-01-01', 'codex', 'archive', 1, 0, 0, 0, 1, 0, '2026-01-01', '2026-01-01')
      `),
      db.prepare(`
        INSERT INTO usage_hourly (
          source_id, hour, agent, input_tokens, output_tokens, cache_creation_tokens,
          cache_read_tokens, total_tokens, total_cost, first_seen_at, last_seen_at
        ) VALUES ('archive-health', '2026-01-01T00:00:00+08:00', 'codex', 1, 0, 0, 0, 1, 0, '2026-01-01', '2026-01-01')
      `),
    ]);

    const afterResponse = await mf.dispatchFetch("http://native.test/api/health", {
      headers: { Cookie: cookie },
    });
    const after = await afterResponse.json() as Record<string, any>;

    expect(after.database.size_bytes).toBe(before.database.size_bytes);
  });

  it("reports D1 limits freshness separately from collection health", async () => {
    const db = await mf.getD1Database("AIUSAGE_DB");
    await seedLimitRows(db);

    const response = await mf.dispatchFetch("http://native.test/api/health", {
      headers: { Cookie: await sessionCookieHeader() },
    });
    const payload = await response.json<Record<string, unknown>>();

    expect(response.status).toBe(200);
    expect(payload).toMatchObject({
      backend_mode: "native_d1_production",
      canonical_store: "cloudflare_d1",
      limits: {
        latest_observed_at: "2026-06-03T11:01:00+08:00",
        effective_window_count: 2,
        raw_window_count: 3,
        stale_window_count: 1,
      },
    });
  });

  it("uses the same explicit production identity in health and user summaries", async () => {
    const headers = { Authorization: `Bearer ${token}` };
    const health = await (await mf.dispatchFetch("http://native.test/api/health", { headers })).json<Record<string, any>>();
    const summary = await (await mf.dispatchFetch("http://native.test/api/mobile/summary?period=today", { headers }))
      .json<Record<string, any>>();

    expect(health.backend_mode).toBe("native_d1_production");
    expect(summary.metadata.backend_mode).toBe("native_d1_production");
  });

  it("fails closed for reads and writes when production has no configured auth token", async () => {
    const unconfiguredBindings = [
      { AIUSAGE_TOKEN: "", AIUSAGE_TOKEN_SPECS: "" },
      { AIUSAGE_TOKEN: "   ", AIUSAGE_TOKEN_SPECS: "name:   " },
    ];
    const requests: Array<[string, RequestInit?]> = [
      ["/"],
      ["/login", { method: "POST" }],
      ["/dashboard"],
      ["/static/dashboard.js"],
      ["/api/health"],
      ["/api/summary?period=today"],
      ["/api/mobile/summary?period=today"],
      ["/ingest", { method: "POST" }],
      ["/ingest-limits", { method: "POST" }],
      ["/unknown-route"],
    ];

    for (const bindings of unconfiguredBindings) {
      mf = await acquire({ ...bindings, AIUSAGE_BACKEND_MODE: "native_d1_production" });
      for (const [path, init] of requests) {
        const response = await mf.dispatchFetch(`http://native.test${path}`, init);
        expect(response.status, `${JSON.stringify(bindings)} ${path}`).toBe(503);
        expect(await response.json()).toEqual({
          status: "error",
          error_type: "auth_unconfigured",
          message: "Authentication is not configured",
        });
      }
    }
  });

  it("keeps token-free local development available outside production mode", async () => {
    mf = await acquire({
      AIUSAGE_TOKEN: "",
      AIUSAGE_TOKEN_SPECS: "",
      AIUSAGE_BACKEND_MODE: "native_d1_dev",
    });

    const response = await mf.dispatchFetch("http://native.test/api/summary?period=today");

    expect(response.status).toBe(200);
  });

  it("derives the default summary date from the configured timezone", async () => {
    const timezones = ["Pacific/Kiritimati", "Etc/GMT+12"] as const;
    const dates: string[] = [];

    for (const configuredTimezone of timezones) {
      const before = currentDateIn(configuredTimezone);
      mf = await acquire({ AIUSAGE_TOKEN: token, AIUSAGE_TIMEZONE: configuredTimezone });
      const response = await mf.dispatchFetch("http://native.test/api/summary?period=today", {
        headers: { Authorization: `Bearer ${token}` },
      });
      const after = currentDateIn(configuredTimezone);
      const payload = await response.json<Record<string, any>>();
      dates.push(String(payload.summary.date));
      expect([before, after]).toContain(payload.summary.date);
    }

    expect(dates[0]).not.toBe(dates[1]);
  });

  it("fails closed when deployment identity is missing", async () => {
    mf = await acquire({
      AIUSAGE_TOKEN: token,
      AIUSAGE_SESSION_SECRET: sessionSecret,
      AIUSAGE_NOW: fixedNow,
      AIUSAGE_BACKEND_MODE: "",
    });
    const db = await mf.getD1Database("AIUSAGE_DB");
    await seedMinimalUsage(db);
    await seedHealthRows(db);

    const response = await mf.dispatchFetch("http://native.test/api/health", {
      headers: { Authorization: `Bearer ${token}` },
    });
    const payload = await response.json<Record<string, any>>();

    expect(payload.backend_mode).toBe("native_d1_unknown");
  });

  it("pins the deployed Native Worker configuration to production identity", async () => {
    const config = await readFile(path.join(repoRoot, "cloudflare/native-worker/wrangler.toml"), "utf8");

    expect(config).toContain('AIUSAGE_BACKEND_MODE = "native_d1_production"');
  });

  it("reads current source health from the per-source state model", async () => {
    // #126 拆分后入口面 = index.ts + 拆出的 auth/health/http 三个模块，守卫覆盖整组。
    const entryFiles = ["index.ts", "auth.ts", "health.ts", "http.ts"];
    const indexSource = (await Promise.all(
      entryFiles.map((name) => readFile(path.join(repoRoot, "cloudflare/native-worker/src", name), "utf8")),
    )).join("\n");
    // #126 目录化后读模型 = 兼容入口 + read-model/ 目录全部模块，守卫覆盖整个目录，
    // 防止有人把被禁的 SQL 写进任何一个子模块。
    const readModelDir = path.join(repoRoot, "cloudflare/native-worker/src/read-model");
    const moduleNames = (await readdir(readModelDir)).sort();
    expect(moduleNames.length, "read-model/ 目录不该是空的").toBeGreaterThanOrEqual(8);
    const readModelSource = [
      await readFile(path.join(repoRoot, "cloudflare/native-worker/src/read-model.ts"), "utf8"),
      ...(await Promise.all(
        moduleNames.map((name) => readFile(path.join(readModelDir, name), "utf8")),
      )),
    ].join("\n");

    expect(indexSource).toContain("FROM source_report_states");
    expect(indexSource).not.toContain("FROM source_reports r");
    expect(readModelSource).toContain("FROM source_report_states");
    expect(readModelSource).not.toContain("FROM source_reports");
    expect(readModelSource).not.toContain("FROM collection_runs");
    expect(readModelSource).not.toContain("ROW_NUMBER() OVER");
  });

  it("keeps dashboard and mobile source health on current per-source states, including ok, failed, and stale sources", async () => {
    const db = await mf.getD1Database("AIUSAGE_DB");
    await db.batch([
      db.prepare(`
        INSERT INTO collection_runs (id, collected_at, timezone, collector_version, status)
        VALUES (?, ?, ?, ?, ?)
      `).bind(3, "2026-06-03T11:59:00+08:00", "Asia/Shanghai", "legacy", "ok"),
      db.prepare(`
        INSERT INTO source_reports (
          id, run_id, source_id, report_type, command, status, ccusage_version,
          first_period, last_period, error_type, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind(3, 3, "mac-local", "daily", "legacy audit", "provider_failed", null, null, null, "provider_failed", "legacy failure must not affect current state"),
      db.prepare(`
        INSERT INTO source_identities (
          source_id, host, machine, os_user, platform, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
      `).bind("stale-source", "wrong-network-host", "actual-machine", "carol", "linux", "2026-06-03T09:00:00+08:00", "2026-06-03T09:00:00+08:00"),
      db.prepare(`
        INSERT INTO source_report_states (
          source_id, collected_at, report_type, command, status, ccusage_version,
          first_period, last_period, error_type, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind("stale-source", "2026-06-03T09:00:00+08:00", "daily", "HTTP Ingest", "ok", null, null, null, null, null),
    ]);

    const cookie = await sessionCookieHeader();
    const dashboardResponse = await mf.dispatchFetch("http://native.test/api/summary?date=2026-06-03&period=today", {
      headers: { Cookie: cookie },
    });
    const mobileResponse = await mf.dispatchFetch("http://native.test/api/mobile/summary?date=2026-06-03&period=today", {
      headers: { Cookie: cookie },
    });
    const dashboard = await dashboardResponse.json() as Record<string, unknown>;
    const mobile = await mobileResponse.json() as Record<string, unknown>;
    const dashboardSources = new Map(
      (dashboard.source_status as Array<Record<string, unknown>>).map((row) => [String(row.source_id), row]),
    );
    const mobileSources = new Map(
      (mobile.sources as Array<Record<string, unknown>>).map((row) => [String(row.source_id), row]),
    );

    expect(dashboardResponse.status).toBe(200);
    expect(mobileResponse.status).toBe(200);
    expect(dashboardSources.get("mac-local")).toMatchObject({
      source_id: "mac-local", status: "ok", observed_at: "2026-06-03T11:55:00+08:00", error_message: null,
    });
    expect(dashboardSources.get("linux-dev-bob")).toMatchObject({
      source_id: "linux-dev-bob", status: "provider_failed", observed_at: "2026-06-03T11:50:00+08:00", error_message: "provider down",
    });
    expect(dashboardSources.get("stale-source")).toMatchObject({
      source_id: "stale-source", machine: "actual-machine", host: "wrong-network-host",
      display_name: "actual-machine · carol", status: "stale",
      observed_at: "2026-06-03T09:00:00+08:00", error_message: null,
    });
    expect(mobileSources.get("mac-local")).toMatchObject({
      source_id: "mac-local", status: "ok", last_observed_at: "2026-06-03T11:55:00+08:00", error_message: null,
    });
    expect(mobileSources.get("linux-dev-bob")).toMatchObject({
      source_id: "linux-dev-bob", status: "provider_failed", last_observed_at: "2026-06-03T11:50:00+08:00", error_message: "provider down",
    });
    expect(mobileSources.get("stale-source")).toMatchObject({
      source_id: "stale-source", machine: "actual-machine", status: "stale",
      last_observed_at: "2026-06-03T09:00:00+08:00", error_message: null,
    });
  });

  it("accepts the session cookie on read APIs", async () => {
    const rejected = await mf.dispatchFetch("http://native.test/api/summary?date=2026-06-03");
    expect(rejected.status).toBe(401);

    const response = await mf.dispatchFetch("http://native.test/api/summary?date=2026-06-03", {
      headers: { Cookie: await sessionCookieHeader() },
    });
    const payload = await response.json<Record<string, unknown>>();

    expect(response.status).toBe(200);
    expect(payload.summary).toMatchObject({ total_tokens: 300 });
  });

  // #101：下面两条用例测的是 summary cache 语义本身。池化实例强制关缓存
  // （session cookie 是确定值，共享实例 + 活缓存会把上个用例的响应喂给下个用例），
  // 所以这两条各自起专属实例、用完即销毁——是全套件仅剩的按用例建实例的地方。
  it("caches successful summary reads for one authenticated session without sharing query variants", async () => {
    mf = await createLiveCacheMiniflare();
    try {
      const setupDb = await mf.getD1Database("AIUSAGE_DB");
      await applySchema(setupDb);
      await seedMinimalUsage(setupDb);
      await seedHealthRows(setupDb);
      const cookie = await sessionCookieHeader();
      const todayUrl = "http://native.test/api/summary?date=2026-06-03&period=today";

      const first = await mf.dispatchFetch(todayUrl, { headers: { Cookie: cookie } });
      expect(first.status).toBe(200);
      expect(first.headers.get("X-AIUsage-Cache")).toBe("MISS");
      expect((await first.json() as Record<string, any>).summary.total_tokens).toBe(300);

      const db = await mf.getD1Database("AIUSAGE_DB");
      await db.prepare("UPDATE usage_daily SET total_tokens = 999 WHERE source_id = ? AND date = ? AND agent = ?")
        .bind("mac-local", "2026-06-03", "codex")
        .run();

      const cached = await mf.dispatchFetch(todayUrl, { headers: { Cookie: cookie } });
      expect(cached.headers.get("X-AIUsage-Cache")).toBe("HIT");
      expect((await cached.json() as Record<string, any>).summary.total_tokens).toBe(300);

      const distinctQuery = await mf.dispatchFetch(
        "http://native.test/api/summary?date=2026-06-03&period=week",
        { headers: { Cookie: cookie } },
      );
      expect(distinctQuery.headers.get("X-AIUsage-Cache")).toBe("MISS");
      expect((await distinctQuery.json() as Record<string, any>).summary.total_tokens).toBe(300);

      const distinctCredential = await mf.dispatchFetch(todayUrl, {
        headers: { Authorization: "Bearer second-contract-test-token" },
      });
      expect(distinctCredential.headers.get("X-AIUsage-Cache")).toBe("MISS");
      expect((await distinctCredential.json() as Record<string, any>).summary.total_tokens).toBe(300);
    } finally {
      await mf.dispose();
    }
  });

  it("does not cache unauthenticated summary responses", async () => {
    mf = await createLiveCacheMiniflare();
    try {
      const setupDb = await mf.getD1Database("AIUSAGE_DB");
      await applySchema(setupDb);
      await seedMinimalUsage(setupDb);
      await seedHealthRows(setupDb);
      const response = await mf.dispatchFetch("http://native.test/api/mobile/summary?date=2026-06-03&period=today");

      expect(response.status).toBe(401);
      expect(response.headers.get("X-AIUsage-Cache")).toBeNull();
      expect(response.headers.get("Cache-Control")).toBeNull();
    } finally {
      await mf.dispose();
    }
  });
});

// #90 块 15：空库 summary。
// 全部现有读路径用例都跑在已 seed 的库上；「上线首日 / 数据被清空」这个真实形态
// （表全建好、一行数据都没有）此前从未回放过——聚合、metadata、额度、版本健康里
// 任何一处「默认有数据」的写法（空数组取 [0]、Math.max(...[])、排序后取尾）都只会在这里炸。
describe.sequential("native TS Worker empty-database read surface", () => {
  let mf: Miniflare;

  beforeEach(async () => {
    mf = await acquire({
      AIUSAGE_TOKEN: token,
      AIUSAGE_NOW: fixedNow,
    });
    // 刻意不 seed：这是「合法的空快照而不是 500」这条断言的全部前提。
    // acquireWorker 在取用时已把数据清空，schema 建好、一行数据都没有。
  });

  it("空库时 /api/summary 返回合法空快照而不是 500", async () => {
    const response = await mf.dispatchFetch("http://native.test/api/summary?date=2026-06-03&period=today", {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(response.status).toBe(200);
    const body = await response.json() as Record<string, any>;

    expect(body.schema_version).toBe(1);
    expect(body.summary).toMatchObject({
      period: "today", date: "2026-06-03",
      total_tokens: 0, input_tokens: 0, output_tokens: 0,
      cache_creation_tokens: 0, cache_read_tokens: 0,
    });
    // 结构下限：空快照不是「响应体也空」——合同要求的顶层键一个都不许少。
    for (const key of [
      "generated_at", "timezone", "summary", "groups", "items", "trend", "source_status",
      "version_health", "limits", "limit_status", "provider_slots", "provider_usage_coverage",
      "account_hourly", "ai_accounts", "metadata",
    ]) {
      expect(key in body, `空快照缺少顶层键 ${key}`).toBe(true);
    }
    expect(body.groups).toEqual({ by_machine: [], by_account: [], by_agent: [] });
    expect(body.items).toEqual([]);
    expect(body.source_status).toEqual([]);
    expect(body.limits).toEqual([]);
    expect(body.limit_status).toEqual([]);
    expect(body.ai_accounts).toEqual([]);
    expect(body.account_hourly).toMatchObject({ total_tokens: 0, by_ai_account: [] });
    // today 的小时轴在空库下仍然是完整的 24 点全零，不是空数组。
    expect(body.trend.points).toHaveLength(24);
    expect(body.trend.points.every((point: Record<string, unknown>) => point.total_tokens === 0)).toBe(true);
    // 版本健康在零来源时产出全零 counts，而不是整块消失。
    expect(body.version_health.needs_attention).toEqual([]);
    const counts = body.version_health.counts as Record<string, number>;
    expect(Object.keys(counts).length).toBeGreaterThanOrEqual(5);
    expect(Object.values(counts).every((value) => value === 0)).toBe(true);
    // 固定 provider 槽位空库时也必须在：两个槽位、用量与额度都如实标 missing。
    expect(body.provider_slots.map((slot: Record<string, any>) => [slot.provider, slot.usage.status, slot.quota.status]))
      .toEqual([["claude", "missing", "missing"], ["codex", "missing", "missing"]]);
  });

  it("空库时 /api/mobile/summary 返回合法空 DTO 而不是 500", async () => {
    const response = await mf.dispatchFetch("http://native.test/api/mobile/summary?date=2026-06-03&period=today", {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(response.status).toBe(200);
    const body = await response.json() as Record<string, any>;

    expect(body.schema_version).toBe(1);
    expect(body.period).toMatchObject({ id: "today", total_tokens: 0 });
    expect(body.sources).toEqual([]);
    expect(body.breakdown).toEqual({
      by_machine: [], by_os_user: [], by_agent: [], by_model: [], by_date: [],
    });
    expect(body.limits).toMatchObject({ observed_count: 0, total_count: 0, windows: [] });
    expect(body.provider_slots.map((slot: Record<string, any>) => [slot.provider, slot.usage.status, slot.quota.status]))
      .toEqual([["claude", "missing", "missing"], ["codex", "missing", "missing"]]);
  });
});

async function sessionCookieHeader(): Promise<string> {
  return `ai_usage_session=${await expectedSessionCookieValue(sessionSecret)}`;
}

// #74 之前这里 shell 出 Python，从 server.py 的 `_session_cookie_value()` 现算参考值
// （「Worker 必须接受 Python 服务端签发的 cookie」的切换期合同）。Python 服务端已删除，
// 但算法本身仍是合同：它决定既有浏览器会话在 Worker 部署间是否存活。所以在测试里
// **独立**钉死同一算法（HMAC-SHA256(secret, "ai-usage-dashboard-session-v1") 的 hex），
// 与 index.ts 的实现互为对照——服务端换算法会当场红，而不是让全部用户被静默登出。
async function expectedSessionCookieValue(secret: string): Promise<string> {
  return createHmac("sha256", secret).update("ai-usage-dashboard-session-v1").digest("hex");
}

function currentDateIn(timezone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

async function readStatic(asset: string): Promise<string> {
  return readFile(path.join(staticRoot, asset), "utf8");
}

/**
 * 合同 golden 的 shape 投影，用来直接和已提交的 `api_contract_golden.json` 比对。
 * 完整实现在 `test/golden/shape.ts`（golden 生成端的 owner）；这里是**刻意收窄的一份**，
 * 只覆盖 `/api/health` 的 `source_status` 子树用得到的分支：该子树里没有 VOLATILE /
 * `_path` 字段，枚举字段只有 `status`。改口径时两边都要看一眼。
 */
const contractEnumFields = new Set(["status"]);

function contractShape(value: unknown, fieldName = ""): Record<string, unknown> {
  if (Array.isArray(value)) {
    const shapes = value.map((item) => contractShape(item));
    const seen = new Set<string>();
    const unique: Record<string, unknown>[] = [];
    for (const shape of shapes) {
      const key = canonicalJson(shape);
      if (seen.has(key)) continue;
      seen.add(key);
      unique.push(shape);
    }
    return { type: "array", length: value.length, items: unique };
  }
  if (value !== null && typeof value === "object") {
    const keys = Object.keys(value as Record<string, unknown>).sort();
    const fields: Record<string, unknown> = {};
    for (const key of keys) fields[key] = contractShape((value as Record<string, unknown>)[key], key);
    return { type: "object", keys, fields };
  }
  const valueType = value === null
    ? "null"
    : typeof value === "boolean"
      ? "bool"
      : typeof value === "number"
        ? (Number.isInteger(value) ? "int" : "float")
        : "str";
  return contractEnumFields.has(fieldName) ? { type: valueType, value } : { type: valueType };
}

function canonicalJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value !== null && typeof value === "object") {
    const entries = Object.keys(value as Record<string, unknown>).sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson((value as Record<string, unknown>)[key])}`);
    return `{${entries.join(",")}}`;
  }
  return JSON.stringify(value);
}

/** #101：从共享池取实例；同绑定复用，数据由 acquireWorker 在取用时归零，schema 无需重复应用。 */
async function acquire(extraBindings: Record<string, string> = {}): Promise<Miniflare> {
  const { mf } = await acquireWorker({ AIUSAGE_TIMEZONE: "Asia/Shanghai", ...extraBindings });
  return mf;
}

/**
 * 两条缓存用例的专属实例：summary cache 保持活性（池里的实例强制关缓存），
 * bundle 走 harness 的进程级缓存，schema 由调用方自己 apply，用完必须 dispose。
 */
async function createLiveCacheMiniflare(): Promise<Miniflare> {
  const script = await bundleWorker();
  return new Miniflare({
    modules: true,
    script,
    scriptPath: "index.mjs",
    compatibilityDate: "2026-06-21",
    d1Databases: ["AIUSAGE_DB"],
    bindings: {
      AIUSAGE_TOKEN: token,
      AIUSAGE_TIMEZONE: "Asia/Shanghai",
      AIUSAGE_TOKEN_SPECS: "second:second-contract-test-token",
      AIUSAGE_SESSION_SECRET: sessionSecret,
      AIUSAGE_NOW: fixedNow,
      AIUSAGE_BACKEND_MODE: "native_d1_production",
      AIUSAGE_CACHE_NAMESPACE: crypto.randomUUID(),
    },
  });
}

async function seedMinimalUsage(db: D1Database): Promise<void> {
  await db.batch([
    db.prepare("INSERT INTO collection_runs (id, collected_at, timezone, collector_version, status) VALUES (?, ?, ?, ?, ?)")
      .bind(1, "2026-06-03T11:55:00+08:00", "Asia/Shanghai", "0.1.0", "ok"),
    db.prepare(`
      INSERT INTO source_identities (
        source_id, host, machine, os_user, platform, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?)
    `).bind("mac-local", "macbook-pro", "macbook-pro", "alice", "darwin", "2026-06-03T11:55:00+08:00", "2026-06-03T11:55:00+08:00"),
    db.prepare(`
      INSERT INTO usage_daily (
        source_id, date, agent, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, total_tokens, total_cost, metadata_json, raw_json,
        first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "mac-local",
      "2026-06-03",
      "claude",
      100,
      150,
      50,
      0,
      300,
      null,
      JSON.stringify({ machine: "macbook-pro", account: "alice", platform: "darwin" }),
      "{}",
      "2026-06-03T11:55:00+08:00",
      "2026-06-03T11:55:00+08:00",
    ),
    db.prepare(`
      INSERT INTO usage_hourly_facts (
        fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
        cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
        session_count, attribution_confidence, provenance, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "minimal-fact", "mac-local", "macbook-pro", "alice", "claude", "claude-alice", "claude", "test",
      "2026-06-03T11:00:00+08:00", fixedNow, "Asia/Shanghai",
      100, 150, 50, 0, 0, 300, null, 1, 1, "observed", "test",
      "2026-06-03T11:55:00+08:00", "2026-06-03T11:55:00+08:00",
    ),
  ]);
}

async function seedHealthRows(db: D1Database): Promise<void> {
  await db.batch([
    db.prepare(`
      INSERT INTO source_reports (
        id, run_id, source_id, report_type, command, status, ccusage_version,
        first_period, last_period, error_type, error_message
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(1, 1, "mac-local", "daily", "HTTP Ingest", "ok", null, "2026-06-03", "2026-06-03", null, null),
    db.prepare(`
      INSERT INTO collection_runs (id, collected_at, timezone, collector_version, status)
      VALUES (?, ?, ?, ?, ?)
    `).bind(2, "2026-06-03T11:50:00+08:00", "Asia/Shanghai", "0.1.0", "ok"),
    db.prepare(`
      INSERT INTO source_reports (
        id, run_id, source_id, report_type, command, status, ccusage_version,
        first_period, last_period, error_type, error_message
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(2, 2, "linux-dev-bob", "limits", "HTTP Ingest", "provider_failed", null, null, null, "provider_failed", "provider down"),
    db.prepare(`
      INSERT INTO source_report_states (
        source_id, collected_at, report_type, command, status, ccusage_version,
        first_period, last_period, error_type, error_message
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind("mac-local", "2026-06-03T11:55:00+08:00", "daily", "HTTP Ingest", "ok", null, "2026-06-03", "2026-06-03", null, null),
    db.prepare(`
      INSERT INTO source_report_states (
        source_id, collected_at, report_type, command, status, ccusage_version,
        first_period, last_period, error_type, error_message
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind("linux-dev-bob", "2026-06-03T11:50:00+08:00", "limits", "HTTP Ingest", "provider_failed", null, null, null, "provider_failed", "provider down"),
  ]);
}

async function seedLimitRows(db: D1Database): Promise<void> {
  await db.batch([
    db.prepare(`
      INSERT INTO limit_windows (
        source_id, provider, window, used_percent, remaining_percent, reset_at,
        window_duration_minutes, source_type, confidence, status, observed_at,
        first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "codex-main",
      "codex",
      "5h",
      42.5,
      57.5,
      "2026-06-03T16:00:00+08:00",
      300,
      "runtime_api",
      "observed",
      "ok",
      "2026-06-03T11:00:00+08:00",
      "2026-06-03T11:00:00+08:00",
      "2026-06-03T11:00:00+08:00",
    ),
    db.prepare(`
      INSERT INTO limit_windows (
        source_id, provider, window, used_percent, remaining_percent, reset_at,
        window_duration_minutes, source_type, confidence, status, observed_at,
        first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "codex-main",
      "codex",
      "week",
      64.25,
      35.75,
      "2026-06-10T00:00:00+08:00",
      10080,
      "runtime_api",
      "observed",
      "ok",
      "2026-06-03T11:01:00+08:00",
      "2026-06-03T11:01:00+08:00",
      "2026-06-03T11:01:00+08:00",
    ),
    db.prepare(`
      INSERT INTO limit_windows (
        source_id, provider, window, used_percent, remaining_percent, reset_at,
        window_duration_minutes, source_type, confidence, status, observed_at,
        first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `).bind(
      "claude-main",
      "claude",
      "5h",
      90,
      10,
      "2026-06-03T16:00:00+08:00",
      300,
      "active_limits_cache",
      "observed",
      "ok",
      "2026-06-03T11:02:00+08:00",
      "2026-06-03T11:02:00+08:00",
      "2026-06-03T11:02:00+08:00",
    ),
  ]);
}
