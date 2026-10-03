/** #126/#199：认证（Bearer token 校验）。网页看板与登录 Cookie 已随 #199 删除。 */
import type { Env } from "./index";

async function isAuthenticated(request: Request, env: Env): Promise<boolean> {
  if (!authTokens(env).length) return !env.AIUSAGE_DEVICE_ADMIN_TOKEN?.trim() && env.AIUSAGE_BACKEND_MODE?.trim() !== "native_d1_production";
  const authHeader = request.headers.get("Authorization") ?? "";
  return authHeader.toLowerCase().startsWith("bearer ") && verifyToken(authHeader.slice(7).trim(), env);
}

function verifyToken(supplied: string | null | undefined, env: Env): boolean {
  const tokens = authTokens(env);
  if (!tokens.length) return !env.AIUSAGE_DEVICE_ADMIN_TOKEN?.trim() && env.AIUSAGE_BACKEND_MODE?.trim() !== "native_d1_production";
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

export {
  authTokens,
  isAuthenticated,
  verifyToken,
};
