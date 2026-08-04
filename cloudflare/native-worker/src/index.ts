import { buildMobile, buildSummary } from "./read-model";
import { backupCanonicalTables, MONTHLY_BACKUP_CRON } from "./backup";
import { STATIC_ASSETS } from "./static-assets";
import { syncDailyRollupsToSupabase } from "./supabase-sync";
import { handleIngestWrite, handleLimitsWrite, WriteValidationError } from "./write-model";
import { authTokens, handleLogin, isAuthenticated, loginPage } from "./auth";
import { AUDIT_RETENTION_DAYS, backendMode, buildHealthResponse, referenceTime } from "./health";
import { json, securityHeaders, text } from "./http";

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

const STATIC_CONTENT_TYPES: Record<string, string> = {
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".html": "text/html; charset=utf-8",
};
const HOURLY_ROLLUP_RETENTION_DAYS = 30;
const SUMMARY_CACHE_TTL_SECONDS = 60;

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
