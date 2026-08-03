/**
 * #74 P1：在 Miniflare 上把真实 Worker 跑起来的最小夹具。
 *
 * golden 一律走 `dispatchFetch` 打真实路由，不直接调 `buildSummary()`——
 * 直接调读模型函数会绕过认证、缓存与序列化，产出的 golden 守不住 HTTP 合同。
 */

import { readFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { build } from "esbuild";
import { Miniflare } from "miniflare";
import { schemaPath, timezone, token, workerEntryPath } from "./paths";

/** 一个进程里只 bundle 一次：13 个 provider slots 场景各 bundle 一遍会让生成慢一个量级。 */
let bundlePromise: Promise<string> | null = null;

export function bundleWorker(): Promise<string> {
  if (!bundlePromise) {
    bundlePromise = (async () => {
      const outdir = path.join(tmpdir(), `aiusage-golden-${process.pid}-${Date.now()}`);
      await mkdir(outdir, { recursive: true });
      const outfile = path.join(outdir, "index.mjs");
      await build({
        entryPoints: [workerEntryPath],
        outfile,
        bundle: true,
        format: "esm",
        platform: "browser",
        target: "es2022",
        sourcemap: false,
      });
      return readFile(outfile, "utf8");
    })();
  }
  return bundlePromise;
}

export type WorkerContext = {
  mf: Miniflare;
  db: D1Database;
  /** 打一个请求并拿到原始响应体，认证方式与 Python 合同场景一致（Bearer token）。 */
  fetchRaw(request: RawRequest): Promise<RawResponse>;
};

export type RawRequest = {
  method: string;
  path: string;
  /** true=带正确 token；字符串=带该 token（用来录未授权场景）；省略=不带。 */
  auth?: boolean | string;
  body?: unknown;
  contentType?: string;
  followRedirects?: boolean;
};

export type RawResponse = {
  status: number;
  contentType: string;
  location: string | null;
  body: Buffer;
};

/**
 * 起一个干净的 Worker + D1，交给 `fn` 用完即销毁。
 *
 * `now` 必须显式传：Worker 的 `AIUSAGE_NOW` 决定过期折算、周期截断与 `generated_at`，
 * 不固定它，golden 每次生成都不一样，防陈旧守卫会退化成随机噪音。
 */
export async function withWorker<T>(
  options: { now: string; bindings?: Record<string, string> },
  fn: (ctx: WorkerContext) => Promise<T>,
): Promise<T> {
  const script = await bundleWorker();
  const mf = new Miniflare({
    modules: true,
    script,
    scriptPath: "index.mjs",
    compatibilityDate: "2026-06-21",
    d1Databases: ["AIUSAGE_DB"],
    bindings: {
      AIUSAGE_TOKEN: token,
      AIUSAGE_TIMEZONE: timezone,
      AIUSAGE_NOW: options.now,
      AIUSAGE_CACHE_NAMESPACE: crypto.randomUUID(),
      AIUSAGE_DISABLE_SUMMARY_CACHE: "true",
      ...options.bindings,
    },
  });
  try {
    const db = await mf.getD1Database("AIUSAGE_DB");
    await applySchema(db);
    return await fn({
      mf,
      db,
      fetchRaw: (request) => dispatch(mf, request),
    });
  } finally {
    await mf.dispose();
  }
}

async function dispatch(mf: Miniflare, request: RawRequest): Promise<RawResponse> {
  const headers: Record<string, string> = {};
  if (request.auth) {
    headers.Authorization = `Bearer ${request.auth === true ? token : request.auth}`;
  }
  let body: string | undefined;
  if (request.body !== undefined) {
    const contentType = request.contentType ?? "application/json";
    headers["Content-Type"] = contentType;
    body = contentType === "application/json"
      ? JSON.stringify(request.body)
      : String(request.body);
  }
  const response = await mf.dispatchFetch(`http://native.test${request.path}`, {
    method: request.method,
    headers,
    body,
    redirect: request.followRedirects === false ? "manual" : "follow",
  });
  const contentType = response.headers.get("Content-Type") ?? "";
  return {
    status: response.status,
    contentType,
    location: response.headers.get("Location"),
    body: Buffer.from(await response.arrayBuffer()),
  };
}

export async function applySchema(db: D1Database): Promise<void> {
  await applySqlText(db, await readFile(schemaPath, "utf8"));
  await resetDatabase(db);
}

export async function applySqlFile(db: D1Database, filePath: string): Promise<void> {
  await applySqlText(db, await readFile(filePath, "utf8"));
}

export async function applySqlText(db: D1Database, sqlText: string): Promise<void> {
  const sql = sqlText
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("--"))
    .join("\n");
  for (const statement of sql.split(";")) {
    const trimmed = statement.trim();
    if (trimmed) await db.prepare(trimmed).run();
  }
}

export async function resetDatabase(db: D1Database): Promise<void> {
  const tables = [
    "usage_hourly_models",
    "usage_hourly_facts",
    "ai_accounts",
    "os_identities",
    "machines",
    "limit_windows",
    "source_identities",
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
