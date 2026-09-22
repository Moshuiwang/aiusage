import { execFile } from "node:child_process";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { Miniflare } from "miniflare";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { applySqlText, bundleWorker } from "./golden/harness";
import { repoRoot, schemaPath } from "./golden/paths";
import { backupCanonicalTables } from "../src/backup";

const execFileAsync = promisify(execFile);
const monthlyCron = "23 18 1 * *";
const backupMonth = "2026-08";
const canonicalTables = [
  "usage_hourly_facts",
  "usage_fact_revisions",
  "usage_reconciliation_ranges",
  "usage_hourly_models",
  "machines",
  "os_identities",
  "ai_accounts",
  "source_identities",
  "limit_windows",
  "usage_daily_rollups",
  "d1_migrations",
  "usage_rollup_dirty_days",
] as const;

type BackupDocument = {
  schema_version: number;
  snapshot_id: string;
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
  it("rejects a partial overwrite from a retry of the same scheduled event", async () => {
    await seedCanonicalTables();
    const scheduled = new Date("2026-08-01T18:23:00Z");
    await backupCanonicalTables({ AIUSAGE_DB: db, AIUSAGE_BACKUPS: bucket }, scheduled);
    await db.batch([db.prepare("UPDATE usage_hourly_facts SET total_tokens=2222"), db.prepare("UPDATE usage_hourly_models SET total_tokens=2222")]);
    const interrupted = new Proxy(bucket, {
      get(target, property, receiver) {
        if (property === "put") return async (key: string, value: string, options: R2PutOptions) => {
          if (key.endsWith("/usage_hourly_models.json")) throw new Error("interrupted retry");
          return target.put(key, value, options);
        };
        const value = Reflect.get(target, property, receiver);
        return typeof value === "function" ? value.bind(target) : value;
      },
    });
    await expect(backupCanonicalTables({ AIUSAGE_DB: db, AIUSAGE_BACKUPS: interrupted }, scheduled)).rejects.toThrow("interrupted retry");
    const inputDir = await mkdtemp(path.join(tmpdir(), "aiusage-backup-interrupted-"));
    for (const table of canonicalTables) {
      const object = await bucket.get(`backup/${backupMonth}/${table}.json`);
      expect(object).not.toBeNull();
      await writeFile(path.join(inputDir, `${table}.json`), await object!.text());
    }
    const fact = JSON.parse(await readFile(path.join(inputDir, "usage_hourly_facts.json"), "utf8"));
    const model = JSON.parse(await readFile(path.join(inputDir, "usage_hourly_models.json"), "utf8"));
    expect(fact.exported_at).toBe(model.exported_at);
    expect(fact.rows[0].total_tokens).toBe(2222);
    expect(model.rows[0].total_tokens).toBe(0);
    await expect(execFileAsync("python3", [path.join(repoRoot, "scripts/restore_from_backup.py"),
      "--input-dir", inputDir, "--output", path.join(inputDir, "restore.sql"),
      "--database", "AIUSAGE_DB", "--config", "cloudflare/native-worker/wrangler.local.toml", "--local"], { cwd: repoRoot }))
      .rejects.toThrow("backup files do not belong to one exported snapshot");
  });
  it("exports one consistent database snapshot even when collection continues during R2 writes", async () => {
    await seedCanonicalTables();
    await db.batch([
      db.prepare("UPDATE usage_hourly_facts SET total_tokens=1"),
      db.prepare("UPDATE usage_hourly_models SET total_tokens=1"),
    ]);
    let changed = false;
    const interleavedBucket = new Proxy(bucket, {
      get(target, property, receiver) {
        if (property === "put") return async (key: string, value: string, options: R2PutOptions) => {
          const result = await target.put(key, value, options);
          if (!changed && key.endsWith("/usage_hourly_facts.json")) {
            changed = true;
            await db.batch([
              db.prepare("UPDATE usage_hourly_facts SET total_tokens=999"),
              db.prepare("UPDATE usage_hourly_models SET total_tokens=999"),
            ]);
          }
          return result;
        };
        const value = Reflect.get(target, property, receiver);
        return typeof value === "function" ? value.bind(target) : value;
      },
    });
    await backupCanonicalTables({ AIUSAGE_DB: db, AIUSAGE_BACKUPS: interleavedBucket }, new Date("2026-08-01T18:23:00Z"));
    expect(changed).toBe(true);
    expect(await db.prepare("SELECT total_tokens FROM usage_hourly_facts").first("total_tokens")).toBe(999);
    const facts = await (await bucket.get("backup/2026-08/usage_hourly_facts.json"))!.json<BackupDocument>();
    const models = await (await bucket.get("backup/2026-08/usage_hourly_models.json"))!.json<BackupDocument>();
    expect(facts.rows).toHaveLength(1);
    expect(models.rows).toHaveLength(1);
    expect(facts.rows[0].total_tokens).toBe(1);
    expect(models.rows[0].total_tokens).toBe(1);
  });
  it("exports every canonical table with source row counts and keeps the daily cron separate", async () => {
    expect(canonicalTables).toHaveLength(12);
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
    await seedCanonicalTables();
    await db.prepare("UPDATE usage_hourly_facts SET input_tokens=1000,total_tokens=1000").run();
    await db.prepare("UPDATE usage_daily_rollups SET input_tokens=1000,total_tokens=1000").run();
    // A fully projected backup has no pending work. Loading its facts must not
    // leave new trigger-generated pending days outside the restored snapshot.
    await db.prepare("DELETE FROM usage_rollup_dirty_days").run();
    const before = await tableCounts();
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

    const restoreArgs = [
      path.join(repoRoot, "scripts/restore_from_backup.py"),
      "--input-dir", inputDir,
      "--output", restoreSql,
      "--database", "AIUSAGE_DB",
      "--config", "cloudflare/native-worker/wrangler.local.toml",
      "--local",
      "--persist-to", path.join(rehearsalDir, "wrangler-state"),
    ];
    const mixedPath = path.join(inputDir, "usage_hourly_models.json");
    const originalModelBackup = await readFile(mixedPath, "utf8");
    const mixedBackup = JSON.parse(originalModelBackup);
    mixedBackup.exported_at = "2026-07-01T18:23:00.000Z";
    await writeFile(mixedPath, JSON.stringify(mixedBackup));
    await expect(execFileAsync("python3", restoreArgs, { cwd: repoRoot }))
      .rejects.toThrow("backup files do not belong to one exported snapshot");
    await writeFile(mixedPath, originalModelBackup);
    const { stdout } = await execFileAsync("python3", restoreArgs, { cwd: repoRoot });
    expect(stdout).toContain("wrangler d1 execute AIUSAGE_DB");
    expect(stdout).toContain("--local");
    expect(stdout).toContain("--file");

    await db.prepare(`INSERT INTO usage_hourly_rollups (
      bucket_start,bucket_end,source_id,machine_id,os_user,ai_provider,ai_account_id,agent,client,
      attribution_confidence,provenance,total_tokens,input_tokens,output_tokens,cache_creation_tokens,
      cache_read_tokens,reasoning_output_tokens,event_count,session_count,fact_count)
      SELECT window_start,window_end,source_id,machine_id,os_user,ai_provider,ai_account_id,agent,coalesce(client,'cli'),
      attribution_confidence,provenance,7,7,0,0,0,0,0,0,1 FROM usage_hourly_facts`).run();
    expect(await db.prepare("SELECT sum(total_tokens) AS n FROM usage_hourly_rollups").first("n")).toBe(7);

    for (const table of [...canonicalTables].reverse()) {
      await db.prepare(`DELETE FROM ${table}`).run();
    }
    // Deleting facts itself creates recovery work; clear it only after the wipe.
    await db.prepare("DELETE FROM usage_rollup_dirty_days").run();
    expect(await tableCounts()).toEqual(Object.fromEntries(canonicalTables.map((table) => [table, 0])));

    await db.exec(await readFile(restoreSql, "utf8"));
    expect(await tableCounts()).toEqual(before);
    for (const table of canonicalTables) {
      const document = JSON.parse(await readFile(path.join(inputDir, `${table}.json`), "utf8"));
      const restored = await db.prepare(`SELECT * FROM ${table}`).all();
      const canonical = (rows: unknown[]) => rows.map(row => JSON.stringify(row, Object.keys(row as object).sort())).sort();
      expect(canonical(restored.results), `${table} complete restored values`).toEqual(canonical(document.rows));
    }
    const visible = await mf.dispatchFetch("http://native.test/api/mobile/summary?date=2026-08-01&period=today", {
      headers: { Authorization: "Bearer contract-test-token" },
    });
    expect(visible.status).toBe(200);
    expect((await visible.json() as any).period.total_tokens).toBe(1000);
  });
});

async function seedCanonicalTables(): Promise<Record<string, number>> {
  for (const table of canonicalTables) {
    if (table === "usage_rollup_dirty_days") continue; // Produced by the actual fact trigger.
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
    const values = selected.map((column) => {
      if (column.name === "window_start") return "2026-08-01T09:00:00+08:00";
      if (column.name === "window_end") return "2026-08-01T10:00:00+08:00";
      return /INT|REAL|NUM|DOUBLE|FLOAT/i.test(column.type) ? 1 : `${table}-${column.name}`;
    });
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
