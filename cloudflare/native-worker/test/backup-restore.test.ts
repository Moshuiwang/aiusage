import { execFile } from "node:child_process";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { Miniflare } from "miniflare";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { applySqlText, bundleWorker } from "./golden/harness";
import { repoRoot, schemaPath } from "./golden/paths";

const execFileAsync = promisify(execFile);
const monthlyCron = "23 18 1 * *";
const backupMonth = "2026-08";
const canonicalTables = [
  "usage_hourly_facts",
  "usage_hourly_models",
  "machines",
  "os_identities",
  "ai_accounts",
  "source_identities",
  "limit_windows",
  "usage_daily_rollups",
  "d1_migrations",
] as const;

type BackupDocument = {
  schema_version: number;
  table: string;
  exported_at: string;
  row_count: number;
  rows: Record<string, unknown>[];
};

let mf: Miniflare;
let db: D1Database;
let bucket: R2Bucket;

beforeEach(async () => {
  mf = new Miniflare({
    modules: true,
    script: await bundleWorker(),
    scriptPath: "index.mjs",
    compatibilityDate: "2026-06-21",
    d1Databases: ["AIUSAGE_DB"],
    r2Buckets: ["AIUSAGE_BACKUPS"],
    bindings: {
      AIUSAGE_TOKEN: "contract-test-token",
      AIUSAGE_TIMEZONE: "Asia/Shanghai",
      AIUSAGE_BACKEND_MODE: "native_d1_production",
    },
  });
  db = await mf.getD1Database("AIUSAGE_DB");
  bucket = await mf.getR2Bucket("AIUSAGE_BACKUPS");
  await applySqlText(db, await readFile(schemaPath, "utf8"));
  await db.prepare(`
    CREATE TABLE d1_migrations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT UNIQUE NOT NULL,
      applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
  `).run();
});

afterEach(async () => {
  await mf.dispose();
});

describe.sequential("monthly D1 backup and local restore rehearsal", () => {
  it("exports every canonical table with source row counts and keeps the daily cron separate", async () => {
    const config = await readFile(path.join(repoRoot, "cloudflare/native-worker/wrangler.toml"), "utf8");
    expect(config).toContain(`crons = ["17 19 * * *", "${monthlyCron}"]`);
    expect(config).toContain('binding = "AIUSAGE_BACKUPS"');
    expect(config).toContain('bucket_name = "aiusage-backups"');

    const expectedCounts = await seedCanonicalTables();
    await runScheduled(monthlyCron, "2026-08-01T18:23:00.000Z");

    const listed = await bucket.list({ prefix: `backup/${backupMonth}/` });
    const keys = listed.objects.map((object) => object.key).sort();
    expect(keys).toEqual(canonicalTables.map((table) => `backup/${backupMonth}/${table}.json`).sort());

    for (const table of canonicalTables) {
      const object = await bucket.get(`backup/${backupMonth}/${table}.json`);
      expect(object, `${table} backup object`).not.toBeNull();
      const document = await object!.json<BackupDocument>();
      expect(document.schema_version, `${table} schema version`).toBe(1);
      expect(document.table).toBe(table);
      expect(document.row_count, `${table} declared row count`).toBe(expectedCounts[table]);
      expect(document.rows.length, `${table} serialized row count`).toBe(expectedCounts[table]);
    }

    await bucket.put("sentinel/daily-cron-must-not-touch-r2", "keep");
    await runScheduled("17 19 * * *", "2026-08-02T19:17:00.000Z");
    expect(await bucket.get("sentinel/daily-cron-must-not-touch-r2")).not.toBeNull();
    const afterDaily = await bucket.list({ prefix: "backup/2026-08/" });
    expect(afterDaily.objects.map((object) => object.key).sort()).toEqual(keys);
  });

  it("deletes the oldest month when the thirteenth backup appears", async () => {
    await seedCanonicalTables();
    for (const month of monthsFrom("2025-08", 12)) {
      await bucket.put(`backup/${month}/marker.json`, month);
    }

    await runScheduled(monthlyCron, "2026-08-01T18:23:00.000Z");

    const listed = await bucket.list({ prefix: "backup/" });
    const months = [...new Set(listed.objects.map((object) => object.key.split("/")[1]))].sort();
    expect(months).toHaveLength(12);
    expect(months[0]).toBe("2025-09");
    expect(months.at(-1)).toBe("2026-08");
    expect(await bucket.get("backup/2025-08/marker.json")).toBeNull();
  });

  it("rehearses export, wipe, restore-script generation, replay, and per-table reconciliation", async () => {
    const before = await seedCanonicalTables();
    await runScheduled(monthlyCron, "2026-08-01T18:23:00.000Z");

    const rehearsalDir = await mkdtemp(path.join(tmpdir(), "aiusage-backup-rehearsal-"));
    const inputDir = path.join(rehearsalDir, "backup");
    const restoreSql = path.join(rehearsalDir, "restore.sql");
    await mkdir(inputDir);
    for (const table of canonicalTables) {
      const object = await bucket.get(`backup/${backupMonth}/${table}.json`);
      expect(object, `${table} must exist before rehearsal`).not.toBeNull();
      await writeFile(path.join(inputDir, `${table}.json`), await object!.text(), "utf8");
    }

    const { stdout } = await execFileAsync("python3", [
      path.join(repoRoot, "scripts/restore_from_backup.py"),
      "--input-dir", inputDir,
      "--output", restoreSql,
      "--database", "AIUSAGE_DB",
      "--config", "cloudflare/native-worker/wrangler.local.toml",
      "--local",
      "--persist-to", path.join(rehearsalDir, "wrangler-state"),
    ], { cwd: repoRoot });
    expect(stdout).toContain("wrangler d1 execute AIUSAGE_DB");
    expect(stdout).toContain("--local");
    expect(stdout).toContain("--file");

    for (const table of [...canonicalTables].reverse()) {
      await db.prepare(`DELETE FROM ${table}`).run();
    }
    expect(await tableCounts()).toEqual(Object.fromEntries(canonicalTables.map((table) => [table, 0])));

    await db.exec(await readFile(restoreSql, "utf8"));
    expect(await tableCounts()).toEqual(before);
  });
});

async function seedCanonicalTables(): Promise<Record<string, number>> {
  for (const table of canonicalTables) {
    const columns = await db.prepare(`PRAGMA table_info(${table})`).all<{
      name: string;
      type: string;
      notnull: number;
      dflt_value: string | null;
      pk: number;
    }>();
    const selected = columns.results.filter((column) =>
      column.pk > 0 || (column.notnull === 1 && column.dflt_value === null),
    );
    const names = selected.map((column) => column.name);
    const values = selected.map((column) =>
      /INT|REAL|NUM|DOUBLE|FLOAT/i.test(column.type) ? 1 : `${table}-${column.name}`,
    );
    await db.prepare(
      `INSERT INTO ${table} (${names.join(", ")}) VALUES (${names.map(() => "?").join(", ")})`,
    ).bind(...values).run();
  }
  return tableCounts();
}

async function tableCounts(): Promise<Record<string, number>> {
  const counts: Record<string, number> = {};
  for (const table of canonicalTables) {
    const row = await db.prepare(`SELECT count(*) AS count FROM ${table}`).first<{ count: number }>();
    counts[table] = Number(row?.count ?? 0);
  }
  return counts;
}

async function runScheduled(cron: string, isoTime: string): Promise<void> {
  const worker = await mf.getWorker();
  await worker.scheduled({ cron, scheduledTime: new Date(isoTime).getTime() });
}

function monthsFrom(start: string, count: number): string[] {
  const [year, month] = start.split("-").map(Number);
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(Date.UTC(year, month - 1 + index, 1));
    return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
  });
}
