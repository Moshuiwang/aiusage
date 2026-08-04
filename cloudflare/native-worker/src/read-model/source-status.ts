/** #126：来源健康与版本视图（/api/summary 与 /api/health 共用产物）。 */
import { evaluateCollectorRelease, publicVersionView } from "../version-contract";
import { identityMatchesFilter, int, nowInTimezone, str } from "./shared";
import type { SourceIdentity } from "./shared";

function buildSourceStatus(
  statusRows: Record<string, string | null>[],
  accuracyRows: Record<string, unknown>[],
  identities: Record<string, SourceIdentity>,
  refTime: Date,
  machineFilter?: string | null,
  accountFilter?: string | null,
): Record<string, unknown>[] {
  const accuracyBySource = new Map<string, Record<string, unknown>[]>();
  for (const row of accuracyRows) {
    const sourceId = str(row.source_id);
    const entries = accuracyBySource.get(sourceId) ?? [];
    entries.push(row);
    accuracyBySource.set(sourceId, entries);
  }
  const rows = statusRows
    .filter((row) => identityMatchesFilter(identities[str(row.source_id)], machineFilter, accountFilter))
    .map((row) => {
      const identity = identities[str(row.source_id)] ?? {};
      const status = statusWithStaleness(str(row.status), str(row.collected_at), refTime, 120);
      const machine = identity.machine ?? identity.host;
      const host = identity.host ?? identity.machine;
      const osUser = identity.os_user;
      const result: Record<string, unknown> = {
        source_id: row.source_id,
        status,
        observed_at: row.collected_at,
        error_message: row.error_message,
      };
      if (machine) result.machine = String(machine);
      if (host) result.host = String(host);
      if (osUser) result.os_user = String(osUser);
      if (identity.platform) result.platform = String(identity.platform);
      if (machine && osUser) result.display_name = `${machine} · ${osUser}`;
      else if (machine) result.display_name = String(machine);
      else result.display_name = str(row.source_id || "unknown-source");
      result.accuracy = sourceAccuracySummary(accuracyBySource.get(str(row.source_id)) ?? []);
      result.version = sourceVersionView(row.collector_version);
      return result;
    });
  return rows;
}

/**
 * 某个来源的对外版本块。
 *
 * 物化下来的只有 `collector_version` 一个字段，其余采集端字段一律为 null——
 * 与 `snapshot_builder.py` 的 `source_versions = {source_id: {"collector_version": row[4]}}` 逐字一致。
 * **不得**从 `source_accuracy` 补 `collector_version` / `parser_schema_version`：Python 侧的
 * `source_versions` 是单键 dict，一旦在这里"丰富"，两套实现立刻分叉。
 *
 * 没有版本时传 `null` 而不是 `{collector_version: null}`：前者判成
 * `collector_release_missing`（Python 侧 `if row[4]` 过滤掉空值的行为），后者是
 * `collector_version_missing`。0007 迁移后存量行的该列全是 NULL，这是常态路径。
 */
function sourceVersionView(collectorVersion: unknown): Record<string, unknown> {
  const release = collectorVersion ? { collector_version: collectorVersion } : null;
  return publicVersionView(evaluateCollectorRelease(release));
}

/**
 * `/api/health` 的来源条目。
 *
 * 只吃 `source_report_states` + `source_identities` 两张表的行，**不调用 `buildSummary`**：
 * 那会把 usage_daily / usage_hourly_facts / limit_windows / source_accuracy 全拉进一个
 * 健康检查端点，是实打实的 D1 读取量回退。
 *
 * 条目成形逻辑复用 `buildSourceStatus`，于是 `/api/health` 的 `source_status.counts`、
 * `versions` 与 `/api/summary` 的 `source_status` 是同一份产物：status 一律带 120 分钟
 * 过期折算（Python 侧 `snapshot_source_health._status_with_staleness()` 的同一口径）。
 */
export function buildHealthSourceStatus(
  rows: Record<string, string | null>[],
  currentTime?: string | null,
): Record<string, unknown>[] {
  const refTime = nowInTimezone("Asia/Shanghai", currentTime);
  const identities: Record<string, SourceIdentity> = {};
  for (const row of rows) {
    identities[str(row.source_id)] = {
      host: row.host,
      machine: row.machine ?? row.host,
      os_user: row.os_user,
      platform: row.platform,
    };
  }
  return buildSourceStatus(rows, [], identities, refTime);
}

function sourceAccuracySummary(rows: Record<string, unknown>[]): Record<string, unknown> {
  if (!rows.length) return { status: "unknown", agents: [] };
  const agents = rows.map((row) => ({
    agent: row.agent,
    status: row.accuracy_status || "unknown",
    collector_version: row.collector_version,
    parser_schema_version: int(row.parser_schema_version),
    mode: row.mode,
    lookback_hours: row.lookback_hours,
    coverage: { start: row.coverage_start, end: row.coverage_end },
    matching_full_scans: int(row.matching_full_scans),
    scan_complete: int(row.scan_complete) === 1,
    read_errors: int(row.read_errors),
    unresolved_mismatch: int(row.unresolved_mismatch),
    verified_at: row.verified_at,
    observed_at: row.observed_at,
  }));
  const statuses = agents.map((row) => str(row.status));
  const status = statuses.every((value) => value === "verified") ? "verified" : "unverified";
  const primary = agents.length === 1 ? agents[0] : null;
  return {
    status,
    collector_version: primary?.collector_version ?? null,
    matching_full_scans: primary?.matching_full_scans ?? Math.min(...agents.map((row) => int(row.matching_full_scans))),
    verified_at: primary?.verified_at ?? null,
    agents,
  };
}

function statusWithStaleness(status: string, collectedAt: string, refTime: Date, staleMinutes: number): string {
  const collected = new Date(collectedAt);
  if (Number.isNaN(collected.getTime())) return status;
  const diffMinutes = (refTime.getTime() - collected.getTime()) / 60000;
  return diffMinutes > staleMinutes ? "stale" : status;
}

export {
  buildSourceStatus,
  sourceAccuracySummary,
  sourceVersionView,
  statusWithStaleness,
};
