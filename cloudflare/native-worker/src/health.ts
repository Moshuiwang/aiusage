/** #126：/api/health 响应装配与部署身份（backendMode）。 */
import { buildHealthSourceStatus } from "./read-model";
import { buildVersionHealth } from "./version-contract";
import type { Env } from "./index";

const LOCAL_ESTIMATE_SOURCE_TYPES = [
  "active_limits_cache",
  "local_history_estimate",
  "ccusage_daily",
  "ccusage_blocks",
  "session_log_estimate",
];
const AUDIT_RETENTION_DAYS = 7;

async function buildHealthResponse(env: Env): Promise<Record<string, unknown>> {
  const [sourceRows, latestCollectedAt, sizeBytes, limitsReport, rejectedRecent] = await Promise.all([
    latestSourceStatuses(env.AIUSAGE_DB),
    latestMetadataTime(env.AIUSAGE_DB),
    databaseSizeProxy(env.AIUSAGE_DB),
    buildLimitsHealth(env.AIUSAGE_DB),
    recentRejectedIngestAttempts(env.AIUSAGE_DB, referenceTime(env)),
  ]);
  // Issue #77：source_status.counts / non_ok 与 versions 数的是**同一份**条目
  // （`buildHealthSourceStatus`），status 一律带 120 分钟过期折算，参照时刻取
  // `AIUSAGE_NOW`。跟的是 Python 参考实现的口径：server_services.py 的 counts 直接数
  // latest.json 里 source_status[].status，而那个 status 在 snapshot_source_health.py
  // 已经过了 `_status_with_staleness()`。
  //
  // 这里曾经数行上的**原始** status（#63 之前的既有行为），结果是同一份响应里同一台
  // 设备在 counts 里算 ok、在 versions.needs_attention 里显示 stale。#77 已统一，
  // 不要再退回原始值：折算后的 status 才回答「这台设备现在是否可信」。
  const healthSourceStatus = buildHealthSourceStatus(sourceRows, env.AIUSAGE_NOW);
  const counts: Record<string, number> = {};
  const nonOk: Record<string, string>[] = [];
  for (const entry of healthSourceStatus) {
    const status = String(entry.status || "unknown");
    counts[status] = (counts[status] ?? 0) + 1;
    if (status !== "ok") {
      nonOk.push({
        source_id: String(entry.source_id || ""),
        status,
      });
    }
  }
  return {
    status: "ok",
    generated_at: env.AIUSAGE_NOW ?? new Date().toISOString(),
    backend_mode: backendMode(env),
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
      // total 必须与 counts / non_ok 数同一份条目（Python `server_services.py` 的
      // `len(source_status)` 就是与 counts 同一个列表）。数 sourceRows 今天恰好等值，
      // 但只要 buildHealthSourceStatus 将来加任何过滤，total 就会大于 counts 之和——
      // 那正是 #77 刚消灭的那类「同一个块里两个数字口径不同」。
      total: healthSourceStatus.length,
      counts,
      non_ok: nonOk,
    },
    // 版本判定核心沿用既有 `versions` 合同；rejected_recent 是仅健康端可见的服务端审计数据。
    versions: {
      ...buildVersionHealth(healthSourceStatus),
      rejected_recent: rejectedRecent,
    },
    limits: limitsReport,
  };
}

function backendMode(env: Env): string {
  const configured = String(env.AIUSAGE_BACKEND_MODE ?? "").trim();
  return configured || "native_d1_unknown";
}

/**
 * `/api/health` 需要的来源行：状态计数只用 `status`，`versions` 还需要
 * `collector_version`（判 state）、`collected_at`（当 observed_at）以及身份字段（拼 display_name）。
 *
 * 仍然只扫 `source_report_states`（每来源一行），外加一次按主键的 `source_identities` 关联，
 * 与原来同量级；**不回头 join `source_reports` × `collection_runs` 取版本**。
 */
async function latestSourceStatuses(db: D1Database): Promise<Record<string, string | null>[]> {
  const result = await db.prepare(`
    SELECT s.source_id, s.status, s.collected_at, s.error_message, s.collector_version,
           i.host, i.machine, i.os_user, i.platform
    FROM source_report_states s
    LEFT JOIN source_identities i ON i.source_id = s.source_id
    ORDER BY s.source_id ASC
  `).all<Record<string, string | null>>();
  return result.results ?? [];
}

async function latestMetadataTime(db: D1Database): Promise<string | null> {
  const row = await db.prepare("SELECT max(collected_at) AS updated_at FROM collection_runs")
    .first<{ updated_at: string | null }>();
  return row?.updated_at ?? null;
}

async function recentRejectedIngestAttempts(db: D1Database, now: Date): Promise<Record<string, unknown>[]> {
  const cutoff = new Date(now.getTime() - AUDIT_RETENTION_DAYS * 24 * 60 * 60 * 1000).toISOString();
  const result = await db.prepare(`
    SELECT source_id_claimed, error_type, path, last_seen_at, count
    FROM rejected_ingest_attempts
    WHERE last_seen_at >= ?
    ORDER BY last_seen_at DESC, source_id_claimed ASC, error_type ASC
  `).bind(cutoff).all<{
    source_id_claimed: string;
    error_type: string;
    path: string;
    last_seen_at: string;
    count: number;
  }>();
  return (result.results ?? []).map((row) => ({
    ...row,
    count: Number(row.count),
  }));
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
    "source_report_states",
    "rejected_ingest_attempts",
    "source_identities",
    "machines",
    "os_identities",
    "ai_accounts",
    "usage_hourly_facts",
    "usage_hourly_models",
    "usage_hourly_rollups",
    "usage_daily_rollups",
    "limit_windows",
  ];
  let rows = 0;
  for (const table of tables) {
    const row = await db.prepare(`SELECT count(*) AS count FROM ${table}`).first<{ count: number }>();
    rows += Number(row?.count ?? 0);
  }
  return rows;
}

function referenceTime(env: Env): Date {
  const configured = env.AIUSAGE_NOW ? new Date(env.AIUSAGE_NOW) : new Date();
  return Number.isNaN(configured.getTime()) ? new Date() : configured;
}

export {
  AUDIT_RETENTION_DAYS,
  backendMode,
  buildHealthResponse,
  referenceTime,
};
