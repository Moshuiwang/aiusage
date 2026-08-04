/** #126：认证与登录（token 校验、session cookie、登录页）。 */
import { STATIC_ASSETS } from "./static-assets";
import { html, securityHeaders } from "./http";
import type { Env } from "./index";

const SESSION_COOKIE_NAME = "ai_usage_session";
const SESSION_COOKIE_MESSAGE = "ai-usage-dashboard-session-v1";

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

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#x27;");
}

export {
  authTokens,
  handleLogin,
  isAuthenticated,
  loginPage,
  verifyToken,
};
