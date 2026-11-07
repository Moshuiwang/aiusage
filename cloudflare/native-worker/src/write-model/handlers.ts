/** #126：/ingest 与 /ingest-limits 的写编排入口（版本兼容判定与拒绝动作在这里）。 */
import type { Env } from "../index";
import { UNSUPPORTED_ERROR_TYPE, evaluateCollectorRelease, publicVersionView, unsupportedMessage } from "../version-contract";
import { buildAccuracyPlans, accuracyWriteStatements } from "./accuracy";
import { filterFactsByLedgerCoverage, normalizeFacts } from "./normalize";
import { accountObservationStatements, collectionReportStatements, factRevisionStatement, factWriteStatements, limitWriteStatements, sourceIdentityStatement } from "./statements";
import { latestSourceReportState, sourceHasNewerReport, upsertHourlyFact, upsertIfChanged } from "./upsert";
import { rejectSensitiveLimitKeys, scanIngestSensitive, validateIngestPayload, validateLimitsPayload } from "./validate";
import { WriteValidationError, acceptedAtFromEnv } from "./shared";
import { formatDate, offsetMinutesAt, parseDateOnly, shiftDate, toOffsetIso } from "../read-model/shared";
import type { AccuracyPlan, AnyRecord, UsageHourlyFact, IngestRequest } from "./shared";

export async function handleIngestWrite(payload: unknown, env: Env): Promise<{ body: AnyRecord; rowsWritten: number }> {
  const req = validateIngestPayload(payload);
  // 版本兼容判定在任何写库动作之前完成：明确不兼容就返回明确错误，
  // 不静默 200 也不静默丢数据。版本未知只标记为未核实，照常接收。
  const versionState = evaluateCollectorRelease(req.collector_release);
  if (!versionState.accepted) {
    throw new WriteValidationError(400, UNSUPPORTED_ERROR_TYPE, unsupportedMessage(versionState));
  }
  const versionView = publicVersionView(versionState);
  const hourlyFacts = filterFactsByLedgerCoverage(req, normalizeFacts(req));
  const acceptedAt = req.observed_at || acceptedAtFromEnv(env);
  const superseded = await sourceHasNewerReport(env.AIUSAGE_DB, req.source_id, acceptedAt);
  let rowsWritten = 0;

  // A newer source heartbeat only supersedes health/scan state, never unrelated historical facts.
  const accuracyPlans = superseded ? [] : await buildAccuracyPlans(env.AIUSAGE_DB, req, acceptedAt);

  const identityStatements = superseded ? [] : [sourceIdentityStatement(env.AIUSAGE_DB, {
    source_id: req.source_id,
    host: req.host,
    machine: req.machine ?? req.host,
    os_user: req.os_user,
    platform: req.platform,
  }, acceptedAt)];
  const revisionStatements = hourlyFacts.map((fact) => factRevisionStatement(env.AIUSAGE_DB, fact, acceptedAt));
  const factStatements = factWriteStatements(env.AIUSAGE_DB, hourlyFacts, acceptedAt);
  const accuracyStatements = superseded ? [] : accuracyWriteStatements(env.AIUSAGE_DB, accuracyPlans, hourlyFacts, acceptedAt, req.source_id);
  // #183-b：账户指纹观察跟"这条心跳是否被更晚的心跳超越"无关——它只是"某时刻某来源看到
  // 某 provider 登录的是这个指纹"，不依附于任何用量事实，所以不受 superseded 影响。
  const accountObservationWriteStatements = req.account_observations?.length
    ? accountObservationStatements(env.AIUSAGE_DB, req.source_id, req.account_observations)
    : [];

  const collectorVersion = versionState.collector_version as string | null;
  const report = sourceReport(req, hourlyFacts, collectorVersion);
  const reportState = await latestSourceReportState(env.AIUSAGE_DB, report);
  const reportStatements = collectionReportStatements(
    env.AIUSAGE_DB,
    acceptedAt,
    env.AIUSAGE_TIMEZONE ?? req.timezone,
    "ok",
    report,
    collectorVersion,
  );
  const shouldWriteReport = !superseded && (!reportState.hasExisting || reportState.changed);
  const writeStatements = [
    ...identityStatements, ...revisionStatements, ...factStatements, ...accuracyStatements,
    ...accountObservationWriteStatements,
  ];
  if (shouldWriteReport) {
    writeStatements.push(...reportStatements);
  }

  rowsWritten += await runWriteBatch(env.AIUSAGE_DB, writeStatements);
  // A previous attempt may have committed facts but failed during projection.
  // Durable dirty days survive that failure, including partially completed chunks.
  await refreshDisplayRollups(env.AIUSAGE_DB, hourlyFacts, accuracyPlans);
  if (!superseded && !shouldWriteReport && rowsWritten > 0) {
    rowsWritten += await runWriteBatch(env.AIUSAGE_DB, reportStatements);
  }

  return {
    rowsWritten,
    body: {
      status: "accepted",
      source_id: req.source_id,
      accepted_at: acceptedAt,
      facts_accepted: hourlyFacts.length,
      message: "Data accepted successfully",
      version: versionView,
    },
  };
}

/**
 * 展示用 rollup 的重算。#287：usage_rollup_dirty_days 登记的是 **UTC 日**（触发器里拿不到
 * 时区规则）；这里把每个脏 UTC 日换算成它覆盖到的 1–2 个统计时区本地日，再按本地日的起止时刻
 * 重算。小时桶标签用该本地日午夜的偏移（夏令时切换当天的小时标签会差一小时，已知限制）。
 */
async function refreshDisplayRollups(db: D1Database, facts: UsageHourlyFact[] = [], plans: AccuracyPlan[] = []): Promise<void> {
  const requestedHours = JSON.stringify(facts.map((fact) => fact.window_start));
  const requestedRanges = JSON.stringify(plans.filter((plan) => plan.can_reconcile).map((plan) => ({ start: plan.coverage_start, end: plan.coverage_end })));
  const requestedDay = `date IN (SELECT date(value) FROM json_each(?)) OR EXISTS (
    SELECT 1 FROM json_each(?) AS coverage
    WHERE julianday(usage_rollup_dirty_days.date || 'T00:00:00Z') < julianday(json_extract(coverage.value, '$.end'))
      AND julianday(usage_rollup_dirty_days.date || 'T00:00:00Z', '+1 day') > julianday(json_extract(coverage.value, '$.start'))
  )`;
  // Bound repair work, prioritizing this request. A large retry progresses across invocations.
  const dirty = await db.prepare(`SELECT date FROM usage_rollup_dirty_days
    ORDER BY CASE WHEN ${requestedDay} THEN 0 ELSE 1 END, date LIMIT 20`)
    .bind(requestedHours, requestedRanges).all<{ date: string }>();
  // 去重只在同一个 batch（同一事务）内做：跨 batch 复用「已重算」会让后一个 batch 确认一个
  // 本地日却没在本事务里重算，期间并发写入的 fact 就会被漏掉（#287 审查）。
  let batch: D1PreparedStatement[] = [];
  let rebuiltInBatch = new Set<string>();
  for (const { date: utcDay } of dirty.results) {
    const localDays = localDaysCoveringUtcDay(utcDay);
    let pending = localDays.filter((day) => !rebuiltInBatch.has(day));
    if (batch.length && batch.length + pending.length * LOCAL_DAY_ROLLUP_STATEMENTS + 1 > 25) {
      await db.batch(batch);
      batch = [];
      rebuiltInBatch = new Set();
      pending = localDays;
    }
    for (const localDay of pending) {
      rebuiltInBatch.add(localDay);
      batch.push(...localDayRollupStatements(db, localDay));
    }
    // Ack 与它覆盖的本地日重算在同一个 batch 里。
    batch.push(db.prepare("DELETE FROM usage_rollup_dirty_days WHERE date = ?").bind(utcDay));
  }
  if (batch.length) await db.batch(batch);
  const unfinished = await db.prepare(`SELECT 1 FROM usage_rollup_dirty_days WHERE ${requestedDay} LIMIT 1`)
    .bind(requestedHours, requestedRanges).first();
  if (unfinished) throw new Error("Usage projection repair remains pending; retry this payload");
}

function localDaysCoveringUtcDay(utcDay: string): string[] {
  const start = new Date(`${utcDay}T00:00:00Z`);
  const end = new Date(start.getTime() + 86400000 - 1);
  return [...new Set([formatDate(start), formatDate(end)])];
}

/**
 * 单个本地日的 rollup 重算，增量写：只写数值真正变化的格子，删掉已没有明细支撑的格子。
 * 原来是整天 DELETE + INSERT（D1 把每个索引的重写都计入写入行数；10 个小时里改 1 个小时
 * 实测 55 行，什么都没变也 15 行）。现在同样场景 ≤ 2 行，无变化 0 行。
 * 小时桶标签用该本地日午夜的偏移（夏令时切换当天的小时标签会差一小时，已知限制）。
 */
const LOCAL_DAY_ROLLUP_STATEMENTS = 5;

export function localDayRollupStatements(db: D1Database, localDay: string): D1PreparedStatement[] {
  const start = toOffsetIso(parseDateOnly(localDay));
  const end = toOffsetIso(parseDateOnly(shiftDate(localDay, 1)));
  const offset = offsetMinutesAt(parseDateOnly(localDay));
  const modifier = `${offset >= 0 ? "+" : ""}${offset} minutes`;
  const suffix = start.slice(19);
  const identity = "source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance";
  const sameIdentity = (alias: string) => identity.split(", ")
    .map((column) => `f.${column} = ${alias}.${column}`).join(" AND ");
  const sums = `sum(input_tokens), sum(output_tokens), sum(cache_creation_tokens), sum(cache_read_tokens),
             sum(reasoning_output_tokens), sum(total_tokens), sum(event_count), sum(session_count), count(*), sum(total_cost)`;
  const valueColumns = ["input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens",
    "reasoning_output_tokens", "total_tokens", "event_count", "session_count", "fact_count", "total_cost"];
  const setChanged = (table: string, extra: string[]) => {
    const columns = [...extra, ...valueColumns];
    return `DO UPDATE SET ${columns.map((column) => `${column} = excluded.${column}`).join(", ")}
      WHERE ${columns.map((column) => `${table}.${column} IS NOT excluded.${column}`).join(" OR ")}`;
  };
  return [
    // 1. 删掉这一天里已没有明细支撑的小时格（明细被删除或改了身份）。
    db.prepare(`
      DELETE FROM usage_hourly_rollups AS r
      WHERE julianday(r.bucket_start) >= julianday(?1) AND julianday(r.bucket_start) < julianday(?2)
        AND NOT EXISTS (
          SELECT 1 FROM usage_hourly_facts AS f
          WHERE julianday(f.window_start) >= julianday(?1) AND julianday(f.window_start) < julianday(?2)
            AND strftime('%Y-%m-%dT%H:00:00', f.window_start, ?3) || ?4 = r.bucket_start
            AND ${sameIdentity("r")}
        )
    `).bind(start, end, modifier, suffix),
    // 2. 小时格 upsert：数值不变则不写（冲突键列不在 SET 里，不重写索引）。
    db.prepare(`
      INSERT INTO usage_hourly_rollups (
        bucket_start, bucket_end, ${identity}, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        reasoning_output_tokens, total_tokens, event_count, session_count, fact_count, total_cost
      )
      SELECT strftime('%Y-%m-%dT%H:00:00', window_start, ?1) || ?2,
             max(strftime('%Y-%m-%dT%H:%M:%S', window_end, ?1)) || ?2,
             ${identity}, ${sums}
      FROM usage_hourly_facts WHERE julianday(window_start) >= julianday(?3) AND julianday(window_start) < julianday(?4)
      GROUP BY strftime('%Y-%m-%dT%H:00:00', window_start, ?1), ${identity}
      ON CONFLICT(bucket_start, ${identity}) ${setChanged("usage_hourly_rollups", ["bucket_end"])}
    `).bind(modifier, suffix, start, end),
    // 3. 删掉这一天已没有明细支撑的日汇总行（历史回填行不动）。
    db.prepare(`
      DELETE FROM usage_daily_rollups AS r
      WHERE r.date = ?1 AND r.provenance <> 'historical_ccusage_fallback_v1'
        AND NOT EXISTS (
          SELECT 1 FROM usage_hourly_facts AS f
          WHERE julianday(f.window_start) >= julianday(?2) AND julianday(f.window_start) < julianday(?3)
            AND ${sameIdentity("r")}
        )
    `).bind(localDay, start, end),
    // 4. 日汇总 upsert：数值不变则不写。
    db.prepare(`
      INSERT INTO usage_daily_rollups (
        date, bucket_start, bucket_end, ${identity}, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        reasoning_output_tokens, total_tokens, event_count, session_count, fact_count, total_cost
      )
      SELECT ?1, ?2, ?3, ${identity}, ${sums}
      FROM usage_hourly_facts WHERE julianday(window_start) >= julianday(?2) AND julianday(window_start) < julianday(?3)
      GROUP BY ${identity}
      ON CONFLICT(date, ${identity}) ${setChanged("usage_daily_rollups", [])}
    `).bind(localDay, start, end),
    // 5. 日的起止时刻只随统计时区变化；单独更新、且只在不同时写（bucket_start 带索引）。
    db.prepare(`
      UPDATE usage_daily_rollups SET bucket_start = ?2, bucket_end = ?3
      WHERE date = ?1 AND provenance <> 'historical_ccusage_fallback_v1'
        AND (bucket_start IS NOT ?2 OR bucket_end IS NOT ?3)
    `).bind(localDay, start, end),
  ];
}

export async function handleLimitsWrite(payload: unknown, env: Env): Promise<{ body: AnyRecord; rowsWritten: number }> {
  const { observedAt, windows } = validateLimitsPayload(payload);
  const rowsWritten = await runWriteBatch(env.AIUSAGE_DB, limitWriteStatements(env.AIUSAGE_DB, windows, observedAt));
  return {
    rowsWritten,
    body: {
      success: true,
      status: "accepted",
      windows_written: windows.length,
      accepted_at: observedAt,
    },
  };
}

async function runWriteBatch(db: D1Database, statements: D1PreparedStatement[]): Promise<number> {
  if (!statements.length) return 0;
  const results = await db.batch(statements);
  return results.reduce((total, result) => total + Number(result.meta?.changes ?? 0), 0);
}

function sourceReport(req: IngestRequest, hourlyFacts: UsageHourlyFact[], collectorVersion: string | null): AnyRecord {
  const periods = hourlyFacts.map((fact) => fact.window_start.slice(0, 10));
  return {
    source_id: req.source_id,
    report_type: "daily",
    command: "HTTP Ingest",
    status: req.collection_status,
    ccusage_version: null,
    first_period: periods.length ? periods.sort()[0] : null,
    last_period: periods.length ? periods.sort()[periods.length - 1] : null,
    error_type: req.error_type,
    error_message: req.error_message,
    // 采集端版本物化进报告状态：设备升级后即使报告内容一字不变，
    // 也会被 rowMatches 判成 changed，从而把真实版本写进 collection_runs。
    collector_version: collectorVersion,
  };
}

export {
  refreshDisplayRollups,
  runWriteBatch,
  sourceReport,
};
