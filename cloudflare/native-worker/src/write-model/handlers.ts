/** #126：/ingest 与 /ingest-limits 的写编排入口（版本兼容判定与拒绝动作在这里）。 */
import type { Env } from "../index";
import { UNSUPPORTED_ERROR_TYPE, evaluateCollectorRelease, publicVersionView, unsupportedMessage } from "../version-contract";
import { buildAccuracyPlans, accuracyWriteStatements } from "./accuracy";
import { filterFactsByLedgerCoverage, normalizeFacts } from "./normalize";
import { collectionReportStatements, factWriteStatements, limitWriteStatements, sourceIdentityStatement } from "./statements";
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

  if (superseded) {
    return {
      rowsWritten,
      body: {
        status: "accepted",
        source_id: req.source_id,
        accepted_at: acceptedAt,
        facts_accepted: 0,
        message: "Data accepted successfully",
        version: versionView,
      },
    };
  }

  const accuracyPlans = await buildAccuracyPlans(env.AIUSAGE_DB, req, acceptedAt);

  const identityStatements = [sourceIdentityStatement(env.AIUSAGE_DB, {
    source_id: req.source_id,
    host: req.host,
    machine: req.machine ?? req.host,
    os_user: req.os_user,
    platform: req.platform,
  }, acceptedAt)];
  const factStatements = factWriteStatements(env.AIUSAGE_DB, hourlyFacts, acceptedAt);
  const accuracyStatements = accuracyWriteStatements(env.AIUSAGE_DB, accuracyPlans, hourlyFacts, acceptedAt, req.source_id);

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
  const shouldWriteReport = !reportState.hasExisting || reportState.changed;
  const writeStatements = [...identityStatements, ...factStatements, ...accuracyStatements];
  if (shouldWriteReport) {
    writeStatements.push(...reportStatements);
  }

  const initialWrite = await runWriteBatchWithFactChanges(
    env.AIUSAGE_DB,
    writeStatements,
    identityStatements.length,
    identityStatements.length + factStatements.length,
  );
  rowsWritten += initialWrite.rowsWritten;
  const factsChanged = initialWrite.factRowsWritten > 0 || accuracyPlans.some((plan) => plan.can_reconcile);
  if (hourlyFacts.length > 0 && factsChanged) {
    await refreshDisplayRollups(env.AIUSAGE_DB, hourlyFacts, accuracyPlans);
  }
  if (!shouldWriteReport && rowsWritten > 0) {
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

async function refreshDisplayRollups(db: D1Database, facts: UsageHourlyFact[], plans: AccuracyPlan[]): Promise<void> {
  const hours = Array.from(new Set(facts.map((fact) => fact.window_start)));
  const dates = Array.from(new Set(facts.map((fact) => fact.window_start.slice(0, 10))));
  const statements: D1PreparedStatement[] = [];
  for (const hour of hours) {
    statements.push(db.prepare("DELETE FROM usage_hourly_rollups WHERE bucket_start = ?").bind(hour));
    statements.push(db.prepare(`
      INSERT INTO usage_hourly_rollups (
        bucket_start, bucket_end, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        attribution_confidence, provenance, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        reasoning_output_tokens, total_tokens, event_count, session_count, fact_count
      )
      SELECT window_start, max(window_end), source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
             attribution_confidence, provenance, sum(input_tokens), sum(output_tokens), sum(cache_creation_tokens), sum(cache_read_tokens),
             sum(reasoning_output_tokens), sum(total_tokens), sum(event_count), sum(session_count), count(*)
      FROM usage_hourly_facts WHERE window_start = ?
      GROUP BY window_start, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance
    `).bind(hour));
  }
  for (const date of dates) {
    const start = `${date}T00:00:00+08:00`;
    const end = new Date(`${date}T00:00:00Z`);
    end.setUTCDate(end.getUTCDate() + 1);
    const endValue = `${end.toISOString().slice(0, 10)}T00:00:00+08:00`;
    statements.push(db.prepare("DELETE FROM usage_daily_rollups WHERE date = ?").bind(date));
    statements.push(db.prepare(`
      INSERT INTO usage_daily_rollups (
        date, bucket_start, bucket_end, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        attribution_confidence, provenance, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        reasoning_output_tokens, total_tokens, event_count, session_count, fact_count
      )
      SELECT ?, ?, ?, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
             attribution_confidence, provenance, sum(input_tokens), sum(output_tokens), sum(cache_creation_tokens), sum(cache_read_tokens),
             sum(reasoning_output_tokens), sum(total_tokens), sum(event_count), sum(session_count), count(*)
      FROM usage_hourly_facts WHERE window_start >= ? AND window_start < ?
      GROUP BY source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance
    `).bind(date, start, endValue, start, endValue));
  }
  for (const plan of plans.filter((plan) => plan.can_reconcile && plan.coverage_start && plan.coverage_end)) {
    statements.push(db.prepare(`
      DELETE FROM usage_hourly_rollups
      WHERE source_id = ? AND agent = ? AND provenance = ? AND bucket_start >= ? AND bucket_start < ?
    `).bind(plan.source_id, plan.agent, plan.provenance, plan.coverage_start, plan.coverage_end));
    statements.push(db.prepare(`
      INSERT INTO usage_hourly_rollups (
        bucket_start, bucket_end, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        attribution_confidence, provenance, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        reasoning_output_tokens, total_tokens, event_count, session_count, fact_count
      )
      SELECT window_start, max(window_end), source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
             attribution_confidence, provenance, sum(input_tokens), sum(output_tokens), sum(cache_creation_tokens), sum(cache_read_tokens),
             sum(reasoning_output_tokens), sum(total_tokens), sum(event_count), sum(session_count), count(*)
      FROM usage_hourly_facts
      WHERE source_id = ? AND agent = ? AND provenance = ? AND window_start >= ? AND window_start < ?
      GROUP BY window_start, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance
    `).bind(plan.source_id, plan.agent, plan.provenance, plan.coverage_start, plan.coverage_end));
    statements.push(db.prepare(`
      DELETE FROM usage_daily_rollups
      WHERE source_id = ? AND agent = ? AND provenance = ?
        AND date >= substr(?, 1, 10) AND date <= substr(?, 1, 10)
    `).bind(plan.source_id, plan.agent, plan.provenance, plan.coverage_start, plan.coverage_end));
    statements.push(db.prepare(`
      INSERT INTO usage_daily_rollups (
        date, bucket_start, bucket_end, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        attribution_confidence, provenance, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        reasoning_output_tokens, total_tokens, event_count, session_count, fact_count
      )
      SELECT substr(window_start, 1, 10), substr(window_start, 1, 10) || 'T00:00:00+08:00',
             substr(window_start, 1, 10) || 'T23:59:59+08:00', source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
             attribution_confidence, provenance, sum(input_tokens), sum(output_tokens), sum(cache_creation_tokens), sum(cache_read_tokens),
             sum(reasoning_output_tokens), sum(total_tokens), sum(event_count), sum(session_count), count(*)
      FROM usage_hourly_facts
      WHERE source_id = ? AND agent = ? AND provenance = ? AND window_start >= ? AND window_start < ?
      GROUP BY substr(window_start, 1, 10), source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance
    `).bind(plan.source_id, plan.agent, plan.provenance, plan.coverage_start, plan.coverage_end));
  }
  for (let offset = 0; offset < statements.length; offset += 100) {
    await db.batch(statements.slice(offset, offset + 100));
  }
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

async function runWriteBatchWithFactChanges(
  db: D1Database,
  statements: D1PreparedStatement[],
  factStart: number,
  factEnd: number,
): Promise<{ rowsWritten: number; factRowsWritten: number }> {
  if (!statements.length) return { rowsWritten: 0, factRowsWritten: 0 };
  const results = await db.batch(statements);
  const changes = results.map((result) => Number(result.meta?.changes ?? 0));
  return {
    rowsWritten: changes.reduce((total, value) => total + value, 0),
    factRowsWritten: changes.slice(factStart, factEnd).reduce((total, value) => total + value, 0),
  };
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
