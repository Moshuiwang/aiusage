import { readFile, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import { Miniflare } from "miniflare";
import { describe, expect, it } from "vitest";

// Issue #61 验收 6：Native Worker 必须和 Python 读模型在同一份 fixture 下给出一致的 provider_slots。
// golden 与 scenario SQL 由 tests/test_provider_slots_parity.py 共用，任何一侧漂移都会红。

type GoldenRecord = {
  name: string;
  scenario: string;
  request: { method: string; path: string; auth: boolean };
  provider_slots: unknown;
};

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const goldenPath = path.join(repoRoot, "cloudflare/native-worker/test/provider_slots_golden.json");
const scenarioDir = path.join(repoRoot, "cloudflare/native-worker/test/provider_slots");
const schemaPath = path.join(repoRoot, "cloudflare/migrations/0001_initial_schema.sql");
const workerEntry = path.join(repoRoot, "cloudflare/native-worker/src/index.ts");
const token = "contract-test-token";
const fixedNow = "2026-06-03T12:00:00+08:00";

describe.sequential("native TS Worker provider slots parity", () => {
  it("matches the Python provider_slots golden for every fixture scenario", async () => {
    const golden = JSON.parse(await readFile(goldenPath, "utf8")) as GoldenRecord[];
    expect(golden.length, "golden must not be empty").toBeGreaterThan(0);
    const scenarios = [...new Set(golden.map((record) => record.scenario))].sort();
    const bundleScript = await bundleWorker();
    const records: GoldenRecord[] = [];

    for (const scenario of scenarios) {
      const mf = createMiniflare(bundleScript);
      try {
        const db = await mf.getD1Database("AIUSAGE_DB");
        await applySqlFile(db, schemaPath);
        await resetDatabase(db);
        await applySqlFile(db, path.join(scenarioDir, `${scenario}.sql`));
        for (const record of golden.filter((row) => row.scenario === scenario)) {
          const response = await mf.dispatchFetch(`http://native.test${record.request.path}`, {
            headers: { Authorization: `Bearer ${token}` },
          });
          expect(response.status, record.name).toBe(200);
          const body = JSON.parse(await response.text()) as Record<string, unknown>;
          records.push({ ...record, provider_slots: body.provider_slots });
        }
      } finally {
        await mf.dispose();
      }
    }

    expect(records).toEqual(golden);
  });
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
