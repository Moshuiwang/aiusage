import type { Env } from "./index";

export const DAILY_MAINTENANCE_CRON = "17 19 * * *";
export const MONTHLY_BACKUP_CRON = "23 18 1 * *";
const BACKUP_RETENTION_MONTHS = 12;

const BACKUP_TABLES = [
  { name: "usage_hourly_facts", orderBy: "fact_id" },
  { name: "usage_fact_revisions", orderBy: "source_id, agent, client, window_start, window_end, ai_provider, ai_account_id, attribution_confidence, provenance" },
  { name: "usage_reconciliation_ranges", orderBy: "source_id, agent, provenance, coverage_start, coverage_end" },
  { name: "usage_hourly_models", orderBy: "fact_id, model" },
  { name: "machines", orderBy: "machine_id" },
  { name: "os_identities", orderBy: "machine_id, os_user" },
  { name: "ai_accounts", orderBy: "provider, account_id" },
  { name: "source_identities", orderBy: "source_id" },
  { name: "limit_windows", orderBy: "source_id, provider, window" },
  {
    name: "usage_daily_rollups",
    orderBy: "date, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance",
  },
  { name: "d1_migrations", orderBy: "id" },
  { name: "usage_rollup_dirty_days", orderBy: "date" },
] as const;

export async function backupCanonicalTables(env: Env, scheduledTime: Date): Promise<void> {
  if (!env.AIUSAGE_BACKUPS) {
    throw new Error("AIUSAGE_BACKUPS R2 binding is required for the monthly backup cron");
  }
  const exportedAt = scheduledTime.toISOString();
  const snapshotId = crypto.randomUUID();
  const month = utcMonth(scheduledTime);

  // Freeze facts, revisions and pending recovery together before any R2 write.
  const snapshots = await env.AIUSAGE_DB.batch<Record<string, unknown>>(
    BACKUP_TABLES.map(table => env.AIUSAGE_DB.prepare(`SELECT * FROM ${table.name} ORDER BY ${table.orderBy}`)),
  );
  for (const [index, table] of BACKUP_TABLES.entries()) {
    const result = snapshots[index];
    const rows = result.results ?? [];
    await env.AIUSAGE_BACKUPS.put(
      `backup/${month}/${table.name}.json`,
      JSON.stringify({
        schema_version: 1,
        table: table.name,
        exported_at: exportedAt,
        snapshot_id: snapshotId,
        row_count: rows.length,
        rows,
      }, null, 2),
      { httpMetadata: { contentType: "application/json; charset=utf-8" } },
    );
  }

  await pruneOldBackupMonths(env.AIUSAGE_BACKUPS);
}

async function pruneOldBackupMonths(bucket: R2Bucket): Promise<void> {
  const objects = await listAllObjects(bucket, "backup/");
  const months = [...new Set(objects.flatMap((object) => {
    const match = /^backup\/(\d{4}-\d{2})\//.exec(object.key);
    return match ? [match[1]] : [];
  }))].sort();
  const expired = new Set(months.slice(0, Math.max(0, months.length - BACKUP_RETENTION_MONTHS)));
  if (!expired.size) return;

  const expiredKeys = objects
    .filter((object) => expired.has(object.key.split("/")[1]))
    .map((object) => object.key);
  for (let offset = 0; offset < expiredKeys.length; offset += 1000) {
    await bucket.delete(expiredKeys.slice(offset, offset + 1000));
  }
}

async function listAllObjects(bucket: R2Bucket, prefix: string): Promise<R2Object[]> {
  const objects: R2Object[] = [];
  let cursor: string | undefined;
  do {
    const page = await bucket.list({ prefix, cursor, limit: 1000 });
    objects.push(...page.objects);
    cursor = page.truncated ? page.cursor : undefined;
  } while (cursor);
  return objects;
}

function utcMonth(date: Date): string {
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}
