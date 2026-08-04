import { buildHealthSourceStatus, buildMobile, buildSummary } from "./read-model";
import { backupCanonicalTables, MONTHLY_BACKUP_CRON } from "./backup";
import { buildVersionHealth } from "./version-contract";
import { STATIC_ASSETS } from "./static-assets";
import { syncDailyRollupsToSupabase } from "./supabase-sync";
import { handleIngestWrite, handleLimitsWrite, WriteValidationError } from "./write-model";

export interface Env {
  AIUSAGE_DB: D1Database;
  AIUSAGE_BACKUPS?: R2Bucket;
  AIUSAGE_TOKEN?: string;
  AIUSAGE_TOKEN_SPECS?: string;
  AIUSAGE_SESSION_SECRET?: string;
  AIUSAGE_TIMEZONE?: string;
  AIUSAGE_NOW?: string;
  AIUSAGE_CACHE_NAMESPACE?: string;
  AIUSAGE_DISABLE_SUMMARY_CACHE?: string;
  AIUSAGE_BACKEND_MODE?: string;
  AIUSAGE_SUPABASE_URL?: string;
  AIUSAGE_SUPABASE_SECRET_KEY?: string;
}

const SESSION_COOKIE_NAME = "ai_usage_session";
const SESSION_COOKIE_MESSAGE = "ai-usage-dashboard-session-v1";
const STATIC_CONTENT_TYPES: Record<string, string> = {
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".html": "text/html; charset=utf-8",
};
const LOCAL_ESTIMATE_SOURCE_TYPES = [
  "active_limits_cache",
  "local_history_estimate",
  "ccusage_daily",
  "ccusage_blocks",
  "session_log_estimate",
];
const AUDIT_RETENTION_DAYS = 7;
const HOURLY_ROLLUP_RETENTION_DAYS = 30;
const SUMMARY_CACHE_TTL_SECONDS = 60;

function securityHeaders(): Record<string, string> {
  return {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
  };
}

function json(payload: unknown, status = 200, extraHeaders: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      ...securityHeaders(),
      ...extraHeaders,
    },
  });
}

function text(payload: string, status = 200, extraHeaders: Record<string, string> = {}): Response {
  return new Response(payload, {
    status,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      ...securityHeaders(),
      ...extraHeaders,
    },
  });
}

function html(payload: string, status = 200, extraHeaders: Record<string, string> = {}): Response {
  return new Response(payload, {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      ...securityHeaders(),
      ...extraHeaders,
    },
  });
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    if (backendMode(env) === "native_d1_production" && !authTokens(env).length) {
      return json({
        status: "error",
        error_type: "auth_unconfigured",
        message: "Authentication is not configured",
      }, 503);
    }
    const url = new URL(request.url);
    if (url.pathname === "/login") {
      if (request.method === "GET") return loginPage();
      if (request.method === "POST") return handleLogin(request, env);
      return json({ status: "error", error_type: "method_not_allowed", message: "Method not allowed" }, 405);
    }
    if (url.pathname === "/ingest" || url.pathname === "/ingest-limits") {
      if (request.method !== "POST") {
        return json({ status: "error", error_type: "method_not_allowed", message: "Method not allowed" }, 405);
      }
      if (!(await isAuthenticated(request, env))) {
        return json({ status: "error", error_type: "http_auth_failed", message: "Invalid or missing token" }, 401);
      }
      let payload: unknown;
      try {
        payload = await request.json();
      } catch (_exc) {
        return json({ status: "error", error_type: "http_schema_invalid", message: "Request body must be valid JSON" }, 400);
      }
      try {
        const result = url.pathname === "/ingest"
          ? await handleIngestWrite(payload, env)
          : await handleLimitsWrite(payload, env);
        return json(result.body, 200, { "X-AIUsage-Rows-Written": String(result.rowsWritten) });
      } catch (exc) {
        if (exc instanceof WriteValidationError) {
          try {
            await recordRejectedIngestAttempt(payload, exc, url.pathname, env);
          } catch (_recordingError) {
            // Rejection telemetry is best-effort and must never change the established response.
          }
          return json({ status: "error", error_type: exc.errorType, message: exc.message }, exc.status);
        }
        return json({ status: "error", error_type: "write_failed", message: "Failed to save data" }, 500);
      }
    }
    if (url.pathname === "/" || url.pathname === "/dashboard") {
      if (!(await isAuthenticated(request, env))) return loginPage();
      return staticAssetResponse("index.html");
    }
    if (url.pathname.startsWith("/static/")) {
      if (!(await isAuthenticated(request, env))) {
        return json({ status: "error", error_type: "auth_required", message: "Authentication required" }, 401);
      }
      return staticAssetResponse(url.pathname.replace(/^\/static\//, ""));
    }
    if (url.pathname === "/api/health") {
      if (!(await isAuthenticated(request, env))) {
        return json({ status: "error", error_type: "auth_required", message: "Authentication required" }, 401);
      }
      return json(await buildHealthResponse(env));
    }
    if (url.pathname === "/api/summary" || url.pathname === "/api/mobile/summary") {
      if (!(await isAuthenticated(request, env))) {
        return json({ status: "error", error_type: "auth_required", message: "Authentication required" }, 401);
      }
      const cacheKey = request.method === "GET" && env.AIUSAGE_DISABLE_SUMMARY_CACHE !== "true"
        ? await summaryCacheKey(request, env)
        : null;
      if (cacheKey) {
        try {
          const cached = await caches.default.match(cacheKey);
          if (cached) return cacheResponse(cached, "HIT");
        } catch (_exc) {
          // Cache availability must not affect a user's ability to read current data.
        }
      }
      const date = url.searchParams.get("date") ?? currentDate(env);
      const requestParams = {
        date,
        period: url.searchParams.get("period") ?? "today",
        timezone: env.AIUSAGE_TIMEZONE ?? "Asia/Shanghai",
        machine: url.searchParams.get("machine"),
        account: url.searchParams.get("account"),
        currentTime: env.AIUSAGE_NOW,
        backendMode: backendMode(env),
      };
      const payload = url.pathname === "/api/mobile/summary"
        ? await buildMobile(env.AIUSAGE_DB, requestParams)
        : await buildSummary(env.AIUSAGE_DB, requestParams);
      const response = json(payload, 200, cacheKey ? summaryResponseHeaders("MISS") : {});
      if (cacheKey) {
        try {
          await caches.default.put(cacheKey, cacheableSummaryResponse(response.clone()));
        } catch (_exc) {
          // A failed cache write is safe to ignore because this is only a read optimization.
        }
      }
      return response;
    }
    return json({ status: "error", error_type: "not_found", message: "Endpoint not found" }, 404);
  },

  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    const scheduledTime = Number(controller.scheduledTime || 0)
      ? new Date(controller.scheduledTime)
      : new Date();
    if (controller.cron === MONTHLY_BACKUP_CRON) {
      await backupCanonicalTables(env, scheduledTime);
      return;
    }
    await pruneAuditTables(env.AIUSAGE_DB, scheduledTime);
    if (env.AIUSAGE_SUPABASE_URL && env.AIUSAGE_SUPABASE_SECRET_KEY) {
      try {
        await syncDailyRollupsToSupabase({
          db: env.AIUSAGE_DB,
          supabaseUrl: env.AIUSAGE_SUPABASE_URL,
          secretKey: env.AIUSAGE_SUPABASE_SECRET_KEY,
          now: scheduledTime,
        });
      } catch (error) {
        console.error("Supabase daily rollup sync failed", error);
      }
    }
  },
};

async function pruneAuditTables(db: D1Database, now: Date): Promise<void> {
  const cutoff = new Date(now.getTime() - AUDIT_RETENTION_DAYS * 24 * 60 * 60 * 1000).toISOString();
  const hourlyRollupCutoff = new Date(now.getTime() - HOURLY_ROLLUP_RETENTION_DAYS * 24 * 60 * 60 * 1000).toISOString();
  await db.batch([
    db.prepare(`
      DELETE FROM source_reports
      WHERE run_id IN (
        SELECT id
        FROM collection_runs
        WHERE collected_at < ?
      )
    `).bind(cutoff),
    db.prepare("DELETE FROM collection_runs WHERE collected_at < ?").bind(cutoff),
    db.prepare("DELETE FROM rejected_ingest_attempts WHERE last_seen_at < ?").bind(cutoff),
    db.prepare("DELETE FROM usage_hourly_rollups WHERE bucket_start < ?").bind(hourlyRollupCutoff),
  ]);
}

async function recordRejectedIngestAttempt(
  payload: unknown,
  error: WriteValidationError,
  path: string,
  env: Env,
): Promise<void> {
  const observedAt = referenceTime(env);
  const now = observedAt.toISOString();
  const sourceIdClaimed = await claimedSourceId(payload, env.AIUSAGE_DB);
  const day = dateInTimezone(observedAt, env.AIUSAGE_TIMEZONE ?? "Asia/Shanghai");
  await env.AIUSAGE_DB.prepare(`
    INSERT INTO rejected_ingest_attempts (
      source_id_claimed, error_type, path, day, first_seen_at, last_seen_at, count
    ) VALUES (?, ?, ?, ?, ?, ?, 1)
    ON CONFLICT(source_id_claimed, error_type, day) DO UPDATE SET
      path = excluded.path,
      last_seen_at = excluded.last_seen_at,
      count = rejected_ingest_attempts.count + 1
  `).bind(sourceIdClaimed, error.errorType, path, day, now, now).run();
}

async function claimedSourceId(payload: unknown, db: D1Database): Promise<string> {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return "unknown";
  const claimed = (payload as Record<string, unknown>).source_id;
  if (typeof claimed !== "string") return "unknown";
  const value = claimed.trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value)) return "unknown";
  const known = await db.prepare(`
    SELECT source_id FROM source_identities WHERE source_id = ?
    UNION
    SELECT source_id FROM source_report_states WHERE source_id = ?
    LIMIT 1
  `).bind(value, value).first<{ source_id: string }>();
  return known?.source_id === value ? value : "unknown";
}

async function summaryCacheKey(request: Request, env: Env): Promise<Request> {
  const cacheUrl = new URL(request.url);
  cacheUrl.protocol = "https:";
  cacheUrl.hostname = `${env.AIUSAGE_CACHE_NAMESPACE ?? "default"}.aiusage-summary-cache.invalid`;
  cacheUrl.port = "";
  const credential = request.headers.get("Authorization") ?? request.headers.get("Cookie") ?? "unprotected";
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(credential));
  cacheUrl.searchParams.set("__auth", Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join(""));
  return new Request(cacheUrl.toString(), { method: "GET" });
}

function summaryResponseHeaders(status: "HIT" | "MISS"): Record<string, string> {
  return {
    "Cache-Control": "private, no-store",
    "X-AIUsage-Cache": status,
    "Vary": "Authorization, Cookie",
  };
}

function cacheableSummaryResponse(response: Response): Response {
  const headers = new Headers(response.headers);
  headers.set("Cache-Control", `max-age=${SUMMARY_CACHE_TTL_SECONDS}`);
  return new Response(response.body, { status: response.status, headers });
}

function cacheResponse(cached: Response, status: "HIT"): Response {
  const headers = new Headers(cached.headers);
  headers.set("X-AIUsage-Cache", status);
  headers.set("Cache-Control", "private, no-store");
  return new Response(cached.body, { status: cached.status, headers });
}

async function handleLogin(request: Request, env: Env): Promise<Response> {
  let token = "";
  const contentType = request.headers.get("Content-Type") ?? "";
  const body = await request.text();
  if (contentType.includes("application/json")) {
    try {
      const payload = JSON.parse(body) as Record<string, unknown>;
      token = String(payload.token ?? "");
    } catch (_exc) {
      return loginPage("Invalid login payload", 400);
    }
  } else {
    token = new URLSearchParams(body).get("token") ?? "";
  }

  if (!verifyToken(token, env)) return loginPage("Invalid token", 401);

  return new Response(null, {
    status: 303,
    headers: {
      Location: "/dashboard",
      "Set-Cookie": await sessionCookieHeader(env),
      ...securityHeaders(),
    },
  });
}

async function isAuthenticated(request: Request, env: Env): Promise<boolean> {
  if (!authTokens(env).length) return true;
  const authHeader = request.headers.get("Authorization") ?? "";
  if (authHeader.toLowerCase().startsWith("bearer ") && verifyToken(authHeader.slice(7).trim(), env)) {
    return true;
  }
  const cookie = request.headers.get("Cookie") ?? "";
  const expectedSession = await sessionCookieValue(sessionSecret(env));
  return cookie.split(";").some((part) => {
    const [name, ...rest] = part.trim().split("=");
    return name === SESSION_COOKIE_NAME && rest.join("=") === expectedSession;
  });
}

function verifyToken(supplied: string | null | undefined, env: Env): boolean {
  const tokens = authTokens(env);
  if (!tokens.length) return true;
  if (!supplied) return false;
  return tokens.some((token) => token === supplied);
}

function authTokens(env: Env): string[] {
  const values: string[] = [];
  const primaryToken = (env.AIUSAGE_TOKEN ?? "").trim();
  if (primaryToken) values.push(primaryToken);
  for (const item of (env.AIUSAGE_TOKEN_SPECS ?? "").split(",")) {
    const trimmed = item.trim();
    if (!trimmed) continue;
    const separator = trimmed.indexOf(":");
    const token = separator >= 0 ? trimmed.slice(separator + 1).trim() : trimmed;
    if (token && !values.includes(token)) values.push(token);
  }
  return values;
}

function sessionSecret(env: Env): string {
  return env.AIUSAGE_SESSION_SECRET ?? authTokens(env)[0] ?? "";
}

async function sessionCookieHeader(env: Env): Promise<string> {
  return `${SESSION_COOKIE_NAME}=${await sessionCookieValue(sessionSecret(env))}; Max-Age=2592000; Path=/; HttpOnly; Secure; SameSite=Lax`;
}

async function sessionCookieValue(token: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(token),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(SESSION_COOKIE_MESSAGE));
  return Array.from(new Uint8Array(signature)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function loginPage(message = "", status = 200): Response {
  const errorBlock = message ? `<p class="error">${escapeHtml(message)}</p>` : "";
  return html(STATIC_ASSETS["login.html"].replace("{{ERROR_BLOCK}}", errorBlock), status);
}

function staticAssetResponse(assetName: string): Response {
  const normalized = normalizeAssetName(assetName);
  if (!normalized) return json({ status: "error", error_type: "not_found", message: "Static asset not found" }, 404);
  const payload = STATIC_ASSETS[normalized];
  if (payload === undefined) return text("Static asset not found", 404);
  const extension = normalized.includes(".") ? normalized.slice(normalized.lastIndexOf(".")) : "";
  return new Response(payload, {
    status: 200,
    headers: {
      "Content-Type": STATIC_CONTENT_TYPES[extension] ?? "application/octet-stream",
      "Cache-Control": "no-cache",
      ...securityHeaders(),
    },
  });
}

function normalizeAssetName(assetName: string): string | null {
  if (!assetName || assetName.startsWith("/") || assetName.includes("\\") || assetName.split("/").includes("..")) {
    return null;
  }
  return assetName;
}

async function buildHealthResponse(env: Env): Promise<Record<string, unknown>> {
  const [sourceRows, latestCollectedAt, sizeBytes, limitsReport, rejectedRecent] = await Promise.all([
    latestSourceStatuses(env.AIUSAGE_DB),
    latestMetadataTime(env.AIUSAGE_DB),
    databaseSizeProxy(env.AIUSAGE_DB),
    buildLimitsHealth(env.AIUSAGE_DB),
    recentRejectedIngestAttempts(env.AIUSAGE_DB, referenceTime(env)),
  ]);
  // Issue #77：source_status.counts / non_ok 与 versions 数的是**同一份**条目
  // （`buildHealthSourceStatus`），status 一律带 120 分钟过期折算，参照时刻取
  // `AIUSAGE_NOW`。跟的是 Python 参考实现的口径：server_services.py 的 counts 直接数
  // latest.json 里 source_status[].status，而那个 status 在 snapshot_source_health.py
  // 已经过了 `_status_with_staleness()`。
  //
  // 这里曾经数行上的**原始** status（#63 之前的既有行为），结果是同一份响应里同一台
  // 设备在 counts 里算 ok、在 versions.needs_attention 里显示 stale。#77 已统一，
  // 不要再退回原始值：折算后的 status 才回答「这台设备现在是否可信」。
  const healthSourceStatus = buildHealthSourceStatus(sourceRows, env.AIUSAGE_NOW);
  const counts: Record<string, number> = {};
  const nonOk: Record<string, string>[] = [];
  for (const entry of healthSourceStatus) {
    const status = String(entry.status || "unknown");
    counts[status] = (counts[status] ?? 0) + 1;
    if (status !== "ok") {
      nonOk.push({
        source_id: String(entry.source_id || ""),
        status,
      });
    }
  }
  return {
    status: "ok",
    generated_at: env.AIUSAGE_NOW ?? new Date().toISOString(),
    backend_mode: backendMode(env),
    canonical_store: "cloudflare_d1",
    database: {
      path: "D1:AIUSAGE_DB",
      size_bytes: sizeBytes,
      exists: true,
    },
    snapshot: {
      path: "D1:latest-snapshot-metadata",
      exists: latestCollectedAt !== null,
      updated_at: latestCollectedAt,
    },
    source_status: {
      // total 必须与 counts / non_ok 数同一份条目（Python `server_services.py` 的
      // `len(source_status)` 就是与 counts 同一个列表）。数 sourceRows 今天恰好等值，
      // 但只要 buildHealthSourceStatus 将来加任何过滤，total 就会大于 counts 之和——
      // 那正是 #77 刚消灭的那类「同一个块里两个数字口径不同」。
      total: healthSourceStatus.length,
      counts,
      non_ok: nonOk,
    },
    // 版本判定核心沿用既有 `versions` 合同；rejected_recent 是仅健康端可见的服务端审计数据。
    versions: {
      ...buildVersionHealth(healthSourceStatus),
      rejected_recent: rejectedRecent,
    },
    limits: limitsReport,
  };
}

function backendMode(env: Env): string {
  const configured = String(env.AIUSAGE_BACKEND_MODE ?? "").trim();
  return configured || "native_d1_unknown";
}

/**
 * `/api/health` 需要的来源行：状态计数只用 `status`，`versions` 还需要
 * `collector_version`（判 state）、`collected_at`（当 observed_at）以及身份字段（拼 display_name）。
 *
 * 仍然只扫 `source_report_states`（每来源一行），外加一次按主键的 `source_identities` 关联，
 * 与原来同量级；**不回头 join `source_reports` × `collection_runs` 取版本**。
 */
async function latestSourceStatuses(db: D1Database): Promise<Record<string, string | null>[]> {
  const result = await db.prepare(`
    SELECT s.source_id, s.status, s.collected_at, s.error_message, s.collector_version,
           i.host, i.machine, i.os_user, i.platform
    FROM source_report_states s
    LEFT JOIN source_identities i ON i.source_id = s.source_id
    ORDER BY s.source_id ASC
  `).all<Record<string, string | null>>();
  return result.results ?? [];
}

async function latestMetadataTime(db: D1Database): Promise<string | null> {
  const row = await db.prepare("SELECT max(collected_at) AS updated_at FROM collection_runs")
    .first<{ updated_at: string | null }>();
  return row?.updated_at ?? null;
}

async function recentRejectedIngestAttempts(db: D1Database, now: Date): Promise<Record<string, unknown>[]> {
  const cutoff = new Date(now.getTime() - AUDIT_RETENTION_DAYS * 24 * 60 * 60 * 1000).toISOString();
  const result = await db.prepare(`
    SELECT source_id_claimed, error_type, path, last_seen_at, count
    FROM rejected_ingest_attempts
    WHERE last_seen_at >= ?
    ORDER BY last_seen_at DESC, source_id_claimed ASC, error_type ASC
  `).bind(cutoff).all<{
    source_id_claimed: string;
    error_type: string;
    path: string;
    last_seen_at: string;
    count: number;
  }>();
  return (result.results ?? []).map((row) => ({
    ...row,
    count: Number(row.count),
  }));
}

async function buildLimitsHealth(db: D1Database): Promise<Record<string, unknown>> {
  const placeholders = LOCAL_ESTIMATE_SOURCE_TYPES.map(() => "?").join(", ");
  const effective = `status = 'ok' AND confidence = 'observed' AND source_type NOT IN (${placeholders})`;
  const row = await db.prepare(`
    SELECT
      count(*) AS raw_window_count,
      sum(CASE WHEN ${effective} THEN 1 ELSE 0 END) AS effective_window_count,
      sum(CASE WHEN ${effective} THEN 0 ELSE 1 END) AS stale_window_count,
      max(CASE WHEN ${effective} THEN observed_at ELSE NULL END) AS latest_observed_at
    FROM limit_windows
  `)
    .bind(...LOCAL_ESTIMATE_SOURCE_TYPES, ...LOCAL_ESTIMATE_SOURCE_TYPES, ...LOCAL_ESTIMATE_SOURCE_TYPES)
    .first<{
      raw_window_count: number | null;
      effective_window_count: number | null;
      stale_window_count: number | null;
      latest_observed_at: string | null;
    }>();
  return {
    latest_observed_at: row?.latest_observed_at ?? null,
    effective_window_count: Number(row?.effective_window_count ?? 0),
    raw_window_count: Number(row?.raw_window_count ?? 0),
    stale_window_count: Number(row?.stale_window_count ?? 0),
  };
}

async function databaseSizeProxy(db: D1Database): Promise<number> {
  const tables = [
    "collection_runs",
    "source_reports",
    "source_report_states",
    "rejected_ingest_attempts",
    "source_identities",
    "machines",
    "os_identities",
    "ai_accounts",
    "usage_hourly_facts",
    "usage_hourly_models",
    "usage_hourly_rollups",
    "usage_daily_rollups",
    "limit_windows",
  ];
  let rows = 0;
  for (const table of tables) {
    const row = await db.prepare(`SELECT count(*) AS count FROM ${table}`).first<{ count: number }>();
    rows += Number(row?.count ?? 0);
  }
  return rows;
}

function referenceTime(env: Env): Date {
  const configured = env.AIUSAGE_NOW ? new Date(env.AIUSAGE_NOW) : new Date();
  return Number.isNaN(configured.getTime()) ? new Date() : configured;
}

function dateInTimezone(date: Date, timezone: string): string {
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(date);
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
  } catch (_invalidTimezone) {
    return date.toISOString().slice(0, 10);
  }
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#x27;");
}

function currentDate(env: Env): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: env.AIUSAGE_TIMEZONE ?? "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}
