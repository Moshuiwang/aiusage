/** #126：/ingest 与 /ingest-limits 的写编排入口（版本兼容判定与拒绝动作在这里）。 */
import type { Env } from "../index";
import { UNSUPPORTED_ERROR_TYPE, evaluateCollectorRelease, publicVersionView, unsupportedMessage } from "../version-contract";
import { buildAccuracyPlans, accuracyWriteStatements } from "./accuracy";
import { filterFactsByLedgerCoverage, normalizeFacts } from "./normalize";
import { collectionReportStatements, factRevisionStatement, factWriteStatements, limitWriteStatements, sourceIdentityStatement } from "./statements";
import { latestSourceReportState, sourceHasNewerReport, upsertHourlyFact, upsertIfChanged } from "./upsert";
import { rejectSensitiveLimitKeys, scanIngestSensitive, validateIngestPayload, validateLimitsPayload } from "./validate";
import { WriteValidationError, acceptedAtFromEnv } from "./shared";
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
  const writeStatements = [...identityStatements, ...revisionStatements, ...factStatements, ...accuracyStatements];
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

async function refreshDisplayRollups(db: D1Database, facts: UsageHourlyFact[] = [], plans: AccuracyPlan[] = []): Promise<void> {
  const requestedHours = JSON.stringify(facts.map((fact) => fact.window_start));
  const requestedRanges = JSON.stringify(plans.filter((plan) => plan.can_reconcile).map((plan) => ({ start: plan.coverage_start, end: plan.coverage_end })));
  const requestedDay = `date IN (SELECT date(value, '+8 hours') FROM json_each(?)) OR EXISTS (
    SELECT 1 FROM json_each(?) AS coverage
    WHERE julianday(usage_rollup_dirty_days.date || 'T00:00:00+08:00') < julianday(json_extract(coverage.value, '$.end'))
      AND julianday(usage_rollup_dirty_days.date || 'T00:00:00+08:00', '+1 day') > julianday(json_extract(coverage.value, '$.start'))
  )`;
  // Bound repair work, prioritizing this request. A large retry progresses across invocations.
  const dirty = await db.prepare(`SELECT date FROM usage_rollup_dirty_days
    ORDER BY CASE WHEN ${requestedDay} THEN 0 ELSE 1 END, date LIMIT 20`)
    .bind(requestedHours, requestedRanges).all<{ date: string }>();
  const statements: D1PreparedStatement[] = [];
  for (const { date } of dirty.results) {
    const start = `${date}T00:00:00+08:00`;
    const end = new Date(`${date}T00:00:00Z`);
    end.setUTCDate(end.getUTCDate() + 1);
    const endValue = `${end.toISOString().slice(0, 10)}T00:00:00+08:00`;
    statements.push(db.prepare("DELETE FROM usage_hourly_rollups WHERE date(bucket_start, '+8 hours') = ?").bind(date));
    statements.push(db.prepare(`
      INSERT INTO usage_hourly_rollups (
        bucket_start, bucket_end, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        attribution_confidence, provenance, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        reasoning_output_tokens, total_tokens, event_count, session_count, fact_count
      )
      SELECT strftime('%Y-%m-%dT%H:00:00', window_start, '+8 hours') || '+08:00',
             max(strftime('%Y-%m-%dT%H:%M:%S', window_end, '+8 hours')) || '+08:00',
             source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
             attribution_confidence, provenance, sum(input_tokens), sum(output_tokens), sum(cache_creation_tokens), sum(cache_read_tokens),
             sum(reasoning_output_tokens), sum(total_tokens), sum(event_count), sum(session_count), count(*)
      FROM usage_hourly_facts WHERE date(window_start, '+8 hours') = ?
      GROUP BY strftime('%Y-%m-%dT%H:00:00', window_start, '+8 hours'), source_id, machine_id, os_user,
               ai_provider, ai_account_id, agent, client, attribution_confidence, provenance
    `).bind(date));
    statements.push(db.prepare("DELETE FROM usage_daily_rollups WHERE date = ? AND provenance <> 'historical_ccusage_fallback_v1'").bind(date));
    statements.push(db.prepare(`
      INSERT OR REPLACE INTO usage_daily_rollups (
        date, bucket_start, bucket_end, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        attribution_confidence, provenance, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        reasoning_output_tokens, total_tokens, event_count, session_count, fact_count
      )
      SELECT ?, ?, ?, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
             attribution_confidence, provenance, sum(input_tokens), sum(output_tokens), sum(cache_creation_tokens), sum(cache_read_tokens),
             sum(reasoning_output_tokens), sum(total_tokens), sum(event_count), sum(session_count), count(*)
      FROM usage_hourly_facts WHERE date(window_start, '+8 hours') = ?
      GROUP BY source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance
    `).bind(date, start, endValue, date));
    // Five statements per day: no chunk boundary can split rebuild from its acknowledgement.
    statements.push(db.prepare("DELETE FROM usage_rollup_dirty_days WHERE date = ?").bind(date));
  }
  for (let offset = 0; offset < statements.length; offset += 25) {
    await db.batch(statements.slice(offset, offset + 25));
  }
  const unfinished = await db.prepare(`SELECT 1 FROM usage_rollup_dirty_days WHERE ${requestedDay} LIMIT 1`)
    .bind(requestedHours, requestedRanges).first();
  if (unfinished) throw new Error("Usage projection repair remains pending; retry this payload");
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
