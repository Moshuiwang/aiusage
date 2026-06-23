import { buildMobile, buildSummary } from "./read-model";
import { STATIC_ASSETS } from "./static-assets";
import { handleIngestWrite, handleLimitsWrite, WriteValidationError } from "./write-model";

export interface Env {
  AIUSAGE_DB: D1Database;
  AIUSAGE_TOKEN?: string;
  AIUSAGE_TOKEN_SPECS?: string;
  AIUSAGE_SESSION_SECRET?: string;
  AIUSAGE_TIMEZONE?: string;
  AIUSAGE_NOW?: string;
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
      const date = url.searchParams.get("date") ?? currentDate();
      const requestParams = {
        date,
        period: url.searchParams.get("period") ?? "today",
        timezone: env.AIUSAGE_TIMEZONE ?? "Asia/Shanghai",
        machine: url.searchParams.get("machine"),
        account: url.searchParams.get("account"),
        currentTime: env.AIUSAGE_NOW,
      };
      const payload = url.pathname === "/api/mobile/summary"
        ? await buildMobile(env.AIUSAGE_DB, requestParams)
        : await buildSummary(env.AIUSAGE_DB, requestParams);
      return json(payload);
    }
    return json({ status: "error", error_type: "not_found", message: "Endpoint not found" }, 404);
  },
};

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
  if (env.AIUSAGE_TOKEN) values.push(env.AIUSAGE_TOKEN);
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
  const [sourceRows, latestCollectedAt, sizeBytes, limitsReport] = await Promise.all([
    latestSourceStatuses(env.AIUSAGE_DB),
    latestMetadataTime(env.AIUSAGE_DB),
    databaseSizeProxy(env.AIUSAGE_DB),
    buildLimitsHealth(env.AIUSAGE_DB),
  ]);
  const counts: Record<string, number> = {};
  const nonOk: Record<string, string>[] = [];
  for (const row of sourceRows) {
    const status = String(row.status || "unknown");
    counts[status] = (counts[status] ?? 0) + 1;
    if (status !== "ok") {
      nonOk.push({
        source_id: String(row.source_id || ""),
        status,
      });
    }
  }
  return {
    status: "ok",
    generated_at: env.AIUSAGE_NOW ?? new Date().toISOString(),
    backend_mode: "native_d1_staging",
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
      total: sourceRows.length,
      counts,
      non_ok: nonOk,
    },
    limits: limitsReport,
  };
}

async function latestSourceStatuses(db: D1Database): Promise<Array<{ source_id: string | null; status: string | null }>> {
  const result = await db.prepare(`
    SELECT r.source_id, r.status
    FROM source_reports r
    JOIN collection_runs c ON r.run_id = c.id
    WHERE NOT EXISTS (
      SELECT 1
      FROM source_reports r2
      JOIN collection_runs c2 ON r2.run_id = c2.id
      WHERE r2.source_id = r.source_id
        AND (
          c2.collected_at > c.collected_at
          OR (c2.collected_at = c.collected_at AND r2.id > r.id)
        )
    )
    ORDER BY r.source_id ASC
  `).all<{ source_id: string | null; status: string | null }>();
  return result.results ?? [];
}

async function latestMetadataTime(db: D1Database): Promise<string | null> {
  const row = await db.prepare("SELECT max(collected_at) AS updated_at FROM collection_runs")
    .first<{ updated_at: string | null }>();
  return row?.updated_at ?? null;
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
    "limit_windows",
  ];
  let rows = 0;
  for (const table of tables) {
    const row = await db.prepare(`SELECT count(*) AS count FROM ${table}`).first<{ count: number }>();
    rows += Number(row?.count ?? 0);
  }
  return rows;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#x27;");
}

function currentDate(): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}
