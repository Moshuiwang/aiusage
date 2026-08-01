import { readFileSync } from "node:fs";
import { readFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { Miniflare } from "miniflare";
import { beforeAll, describe, expect, it } from "vitest";

// Issue #61 验收 6：Native Worker 必须和 Python 读模型在同一份 fixture 下给出一致的
// provider_slots / provider_usage_coverage。golden 与 scenario SQL 由
// tests/test_provider_slots_parity.py 共用，任何一侧漂移都会红。
//
// 每个 scenario 一个 it()：把全部 scenario 塞进单个 it 会顶到 vitest 的 testTimeout，
// CI 一慢就红，而且红出来的现场看着像跨实现契约破了，其实只是超时。

type GoldenRecord = {
  name: string;
  scenario: string;
  request: { method: string; path: string; auth: boolean };
  provider_slots: unknown;
  provider_usage_coverage: unknown;
};

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const goldenPath = path.join(repoRoot, "cloudflare/native-worker/test/provider_slots_golden.json");
const scenarioDir = path.join(repoRoot, "cloudflare/native-worker/test/provider_slots");
const schemaPath = path.join(repoRoot, "cloudflare/migrations/0001_initial_schema.sql");
const workerEntry = path.join(repoRoot, "cloudflare/native-worker/src/index.ts");
const token = "contract-test-token";
const fixedNow = "2026-06-03T12:00:00+08:00";

// 收集阶段就要知道有哪些 scenario，才能一个 scenario 生成一个 it()。
const golden = JSON.parse(readFileSync(goldenPath, "utf8")) as GoldenRecord[];
const scenarios = [...new Set(golden.map((record) => record.scenario))].sort();

describe.sequential("native TS Worker provider slots parity", () => {
  let bundleScript = "";

  beforeAll(async () => {
    expect(golden.length, "golden must not be empty").toBeGreaterThan(0);
    expect(scenarios.length, "golden must cover at least the four combinations").toBeGreaterThanOrEqual(4);
    bundleScript = await bundleWorker();
  });

  for (const scenario of scenarios) {
    it(`matches the Python golden for ${scenario}`, async () => {
      const expected = golden.filter((record) => record.scenario === scenario);
      expect(expected.length, `${scenario} has golden records`).toBeGreaterThan(0);

      const mf = createMiniflare(bundleScript);
      const actual: GoldenRecord[] = [];
      try {
        const db = await mf.getD1Database("AIUSAGE_DB");
        await applySqlFile(db, schemaPath);
        await resetDatabase(db);
        await applySqlFile(db, path.join(scenarioDir, `${scenario}.sql`));
        for (const record of expected) {
          const response = await mf.dispatchFetch(`http://native.test${record.request.path}`, {
            headers: { Authorization: `Bearer ${token}` },
          });
          expect(response.status, record.name).toBe(200);
          const body = JSON.parse(await response.text()) as Record<string, unknown>;
          actual.push({
            ...record,
            provider_slots: body.provider_slots,
            provider_usage_coverage: body.provider_usage_coverage,
          });
        }
      } finally {
        await mf.dispose();
      }

      expect(actual).toEqual(expected);
    });
  }
});

async function bundleWorker(): Promise<string> {
  const outdir = path.join(tmpdir(), `aiusage-provider-slots-${Date.now()}-${Math.random().toString(16).slice(2)}`);
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

function createMiniflare(bundleScript: string): Miniflare {
  return new Miniflare({
    modules: true,
    script: bundleScript,
    scriptPath: "index.mjs",
    compatibilityDate: "2026-06-21",
    d1Databases: ["AIUSAGE_DB"],
    bindings: {
      AIUSAGE_TOKEN: token,
      AIUSAGE_TIMEZONE: "Asia/Shanghai",
      AIUSAGE_NOW: fixedNow,
      AIUSAGE_CACHE_NAMESPACE: crypto.randomUUID(),
      AIUSAGE_DISABLE_SUMMARY_CACHE: "true",
    },
  });
}

async function applySqlFile(db: D1Database, filePath: string): Promise<void> {
  const sql = (await readFile(filePath, "utf8"))
    .split("\n")
    .filter((line) => !line.trimStart().startsWith("--"))
    .join("\n");
  for (const statement of sql.split(";")) {
    const trimmed = statement.trim();
    if (trimmed) await db.prepare(trimmed).run();
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
