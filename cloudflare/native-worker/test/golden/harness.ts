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

/**
 * #101：按绑定键控的共享实例池。
 *
 * 一个 Miniflare 实例的成本 = workerd 启动 + schema 应用（每文件另有一次 esbuild）。
 * 绑定完全相同的用例没有理由各自付一遍，所以实例按「调用方绑定」入池复用：
 * schema 只在建实例时应用一次，之后每次 acquire 只做数据重置。
 * 跨用例隔离由 `shared-worker.test.ts` 的守卫证明（污染全表 → 重取 → 断言干净）。
 *
 * 池里的实例**一律强制关 summary cache**：session cookie 是确定值（HMAC 无随机数），
 * 共享实例 + 活缓存必然把上一个用例的缓存响应喂给下一个用例。真要测缓存语义的
 * 用例必须自己起专属实例并原地 dispose（见 web_surface 的两条缓存用例）。
 */
type PooledWorker = { mf: Miniflare; db: D1Database };

const workerPool = new Map<string, Promise<PooledWorker>>();

export async function acquireWorker(bindings: Record<string, string> = {}): Promise<PooledWorker> {
  if ("AIUSAGE_DISABLE_SUMMARY_CACHE" in bindings) {
    // 静默吞掉这个开关比拒绝它危险得多：调用方以为自己开了活缓存，
    // 「响应不该带缓存头」之类的断言会在关缓存的实例上变成恒真。
    throw new Error(
      "acquireWorker 不接受 AIUSAGE_DISABLE_SUMMARY_CACHE：池化实例强制关缓存，"
      + "要测缓存语义请自建专属实例（参考 web_surface 的 createLiveCacheMiniflare）。",
    );
  }
  const key = JSON.stringify(Object.entries(bindings).sort(([a], [b]) => a.localeCompare(b)));
  (globalThis as Record<string, unknown>).__aiusageWorkerPoolUsed = true;
  let pooled = workerPool.get(key);
  if (!pooled) {
    pooled = (async () => {
      const script = await bundleWorker();
      const mf = new Miniflare({
        modules: true,
        script,
        scriptPath: "index.mjs",
        compatibilityDate: "2026-06-21",
        d1Databases: ["AIUSAGE_DB"],
        bindings: {
          AIUSAGE_TOKEN: token,
          AIUSAGE_CACHE_NAMESPACE: crypto.randomUUID(),
          ...bindings,
          AIUSAGE_DISABLE_SUMMARY_CACHE: "true",
        },
      });
      const db = await mf.getD1Database("AIUSAGE_DB");
      await applySqlText(db, await readFile(schemaPath, "utf8"));
      return { mf, db };
    })();
    workerPool.set(key, pooled);
  }
  const worker = await pooled;
  // 复用边界上的清理：上一个用例留下什么都不作数，数据和发号器一起归零。
  await resetDatabase(worker.db);
  return worker;
}

/**
 * 释放池里全部实例。vitest 侧由 `setup.dispose-workers.ts` 在每个测试文件的
 * afterAll 统一调用；脚本消费者（golden 生成）在结束时显式调用，
 * 否则 workerd 子进程会让 node 进程吊死不退出。
 */
export async function disposeWorkers(): Promise<void> {
  const pooled = [...workerPool.values()];
  workerPool.clear();
  await Promise.all(pooled.map((entry) => entry.then(({ mf }) => mf.dispose(), () => undefined)));
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
 * 从池里拿一个干净的 Worker + D1 交给 `fn`。实例复用、数据每次归零；
 * 释放统一走 `disposeWorkers()`，不在这里逐次销毁。
 *
 * `now` 必须显式传：Worker 的 `AIUSAGE_NOW` 决定过期折算、周期截断与 `generated_at`，
 * 不固定它，golden 每次生成都不一样，防陈旧守卫会退化成随机噪音。
 */
export async function withWorker<T>(
  options: { now: string; bindings?: Record<string, string> },
  fn: (ctx: WorkerContext) => Promise<T>,
): Promise<T> {
  const { mf, db } = await acquireWorker({
    AIUSAGE_TIMEZONE: timezone,
    AIUSAGE_NOW: options.now,
    ...options.bindings,
  });
  return fn({
    mf,
    db,
    fetchRaw: (request) => dispatch(mf, request),
  });
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

/**
 * 清库范围必须覆盖 schema 的每一张用户表：实例共享后，漏掉的表就是跨用例污染通道。
 * 覆盖完整性由 `shared-worker.test.ts` 的守卫盯着（污染全部表 → reset → 逐表断言清空），
 * 往 schema 加表而不加这里会直接红。
 */
export async function resetDatabase(db: D1Database): Promise<void> {
  const tables = [
    "usage_hourly_models",
    "usage_hourly_facts",
    "source_accuracy",
    "ai_accounts",
    "os_identities",
    "machines",
    "limit_windows",
    "source_identities",
    "usage_hourly",
    "usage_daily_models",
    "usage_daily",
    "usage_hourly_rollups",
    "usage_daily_rollups",
    "source_report_states",
    "source_reports",
    "collection_runs",
  ];
  for (const table of tables) {
    await db.prepare(`DELETE FROM ${table}`).run();
  }
  // AUTOINCREMENT 的发号器也要归零，复用的库才和新库发同样的 id。
  // sqlite_sequence 由 SQLite 在第一次 AUTOINCREMENT 插入时才创建，不能无条件 DELETE。
  const sequenceTable = await db.prepare(
    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'sqlite_sequence'",
  ).first<{ name: string }>();
  if (sequenceTable) {
    await db.prepare("DELETE FROM sqlite_sequence").run();
  }
}
