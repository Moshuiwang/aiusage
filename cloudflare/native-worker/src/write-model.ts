import type { Env } from "./index";

type AnyRecord = Record<string, unknown>;

type SourceReportState = {
  hasExisting: boolean;
  changed: boolean;
};

type IngestRequest = {
  schema_version: number;
  source_id: string;
  host: string;
  machine: string | null;
  os_user: string;
  platform: string;
  timezone: string;
  observed_at: string;
  collection_window: string;
  usage_daily: AnyRecord[];
  ccusage_daily_report?: AnyRecord;
  ccusage_session_report?: AnyRecord;
  ccusage_blocks_report?: AnyRecord;
  mswusage_codex_hourly_report?: AnyRecord;
  codex_hourly_status?: AnyRecord;
  usage_hourly_facts?: AnyRecord[];
  usage_ledger_runs?: AnyRecord[];
  collection_status: string;
  error_type: string | null;
  error_message: string | null;
};

type UsageHourlyFact = {
  fact_id: string;
  source_id: string;
  machine_id: string;
  machine_name: string;
  host: string;
  os_user: string;
  platform: string;
  ai_provider: string;
  ai_account_id: string;
  ai_account_label: string;
  ai_account_display_name: string | null;
  ai_account_subscription: string | null;
  agent: string;
  client: string;
  window_start: string;
  window_end: string;
  timezone: string;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  reasoning_output_tokens: number;
  total_tokens: number;
  total_cost: number | null;
  event_count: number;
  session_count: number;
  attribution_confidence: string;
  provenance: string;
  account_evidence: AnyRecord;
  metadata: AnyRecord;
  model_breakdowns: AnyRecord[];
};

type AccuracyPlan = {
  source_id: string;
  agent: string;
  provenance: string;
  collector: AnyRecord;
  facts_digest: string;
  coverage_start: string | null;
  coverage_end: string | null;
  matching_full_scans: number;
  accuracy_status: "unverified" | "verified";
  verified_at: string | null;
  can_reconcile: boolean;
};

type LimitWindow = {
  source_id: string;
  provider: string;
  window: string;
  used_percent: number;
  remaining_percent: number;
  reset_at: string;
  window_duration_minutes: number;
  observed_at: string;
  source_type: string;
  confidence: string;
  status: string;
};

export class WriteValidationError extends Error {
  errorType: string;
  status: number;

  constructor(status: number, errorType: string, message: string) {
    super(message);
    this.errorType = errorType;
    this.status = status;
  }
}

export async function handleIngestWrite(payload: unknown, env: Env): Promise<{ body: AnyRecord; rowsWritten: number }> {
  const req = validateIngestPayload(payload);
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
      },
    };
  }

  const accuracyPlans = await buildAccuracyPlans(env.AIUSAGE_DB, req, acceptedAt);

  const writeStatements = ingestWriteStatements(env.AIUSAGE_DB, {
    source_id: req.source_id,
    host: req.host,
    machine: req.machine ?? req.host,
    os_user: req.os_user,
    platform: req.platform,
  }, hourlyFacts, acceptedAt);
  writeStatements.push(...accuracyWriteStatements(env.AIUSAGE_DB, accuracyPlans, hourlyFacts, acceptedAt, req.source_id));

  const report = sourceReport(req, hourlyFacts);
  const reportState = await latestSourceReportState(env.AIUSAGE_DB, report);
  const reportStatements = collectionReportStatements(env.AIUSAGE_DB, acceptedAt, env.AIUSAGE_TIMEZONE ?? req.timezone, "ok", report);
  const shouldWriteReport = !reportState.hasExisting || reportState.changed;
  if (shouldWriteReport) {
    writeStatements.push(...reportStatements);
  }

  rowsWritten += await runWriteBatch(env.AIUSAGE_DB, writeStatements);
  if (hourlyFacts.length > 0 && rowsWritten > 0) {
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

function ingestWriteStatements(
  db: D1Database,
  identity: AnyRecord,
  hourlyFacts: UsageHourlyFact[],
  seenAt: string,
): D1PreparedStatement[] {
  return [
    sourceIdentityStatement(db, identity, seenAt),
    ...hourlyFacts.flatMap((fact) => hourlyFactStatements(db, fact, seenAt)),
  ];
}

function limitWriteStatements(db: D1Database, windows: LimitWindow[], seenAt: string): D1PreparedStatement[] {
  return windows.flatMap((window) => limitWindowStatements(db, window, seenAt));
}

function sourceIdentityStatement(db: D1Database, identity: AnyRecord, seenAt: string): D1PreparedStatement {
  return db.prepare(`
    INSERT INTO source_identities (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(source_id) DO UPDATE SET
      host = excluded.host,
      machine = excluded.machine,
      os_user = excluded.os_user,
      platform = excluded.platform,
      last_seen_at = CASE
        WHEN excluded.last_seen_at >= source_identities.last_seen_at THEN excluded.last_seen_at
        ELSE source_identities.last_seen_at
      END
    WHERE source_identities.host IS NOT excluded.host
       OR source_identities.machine IS NOT excluded.machine
       OR source_identities.os_user IS NOT excluded.os_user
       OR source_identities.platform IS NOT excluded.platform
       OR (
         excluded.last_seen_at >= source_identities.last_seen_at
         AND source_identities.last_seen_at IS NOT excluded.last_seen_at
       )
  `).bind(identity.source_id, identity.host, identity.machine, identity.os_user, identity.platform, seenAt, seenAt);
}

function hourlyFactStatements(db: D1Database, fact: UsageHourlyFact, seenAt: string): D1PreparedStatement[] {
  const statements = [
    machineStatement(db, fact, seenAt),
    osIdentityStatement(db, fact, seenAt),
    aiAccountStatement(db, fact, seenAt),
    staleFactModelStatement(db, fact),
    factStatement(db, fact, seenAt),
    staleCurrentFactModelsStatement(db, fact),
  ];
  for (const model of fact.model_breakdowns) {
    statements.push(hourlyFactModelStatement(db, fact, model, seenAt));
  }
  return statements;
}

function machineStatement(db: D1Database, fact: UsageHourlyFact, seenAt: string): D1PreparedStatement {
  return db.prepare(`
    INSERT INTO machines (machine_id, machine_name, host, platform, first_seen_at, last_seen_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(machine_id) DO UPDATE SET
      machine_name = excluded.machine_name,
      host = excluded.host,
      platform = excluded.platform,
      last_seen_at = excluded.last_seen_at
    WHERE machines.machine_name IS NOT excluded.machine_name
       OR machines.host IS NOT excluded.host
       OR machines.platform IS NOT excluded.platform
  `).bind(fact.machine_id, fact.machine_name, fact.host, fact.platform, seenAt, seenAt);
}

function osIdentityStatement(db: D1Database, fact: UsageHourlyFact, seenAt: string): D1PreparedStatement {
  const display = `${fact.machine_name} · ${fact.os_user}`;
  return db.prepare(`
    INSERT INTO os_identities (machine_id, os_user, display_name, first_seen_at, last_seen_at)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(machine_id, os_user) DO UPDATE SET
      display_name = excluded.display_name,
      last_seen_at = excluded.last_seen_at
    WHERE os_identities.display_name IS NOT excluded.display_name
  `).bind(fact.machine_id, fact.os_user, display, seenAt, seenAt);
}

function aiAccountStatement(db: D1Database, fact: UsageHourlyFact, seenAt: string): D1PreparedStatement {
  return db.prepare(`
    INSERT INTO ai_accounts (provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(provider, account_id) DO UPDATE SET
      account_label = excluded.account_label,
      display_name = excluded.display_name,
      subscription = excluded.subscription,
      last_seen_at = excluded.last_seen_at
    WHERE ai_accounts.account_label IS NOT excluded.account_label
       OR ai_accounts.display_name IS NOT excluded.display_name
       OR ai_accounts.subscription IS NOT excluded.subscription
  `).bind(
    fact.ai_provider, fact.ai_account_id, fact.ai_account_label,
    fact.ai_account_display_name, fact.ai_account_subscription, seenAt, seenAt,
  );
}

function staleFactModelStatement(db: D1Database, fact: UsageHourlyFact): D1PreparedStatement {
  return db.prepare(`
    DELETE FROM usage_hourly_models
    WHERE fact_id IN (
      SELECT fact_id
      FROM usage_hourly_facts
      WHERE source_id = ? AND agent = ? AND client = ? AND window_start = ? AND window_end = ?
        AND ai_provider = ? AND ai_account_id = ? AND attribution_confidence = ? AND provenance = ?
        AND fact_id IS NOT ?
    )
  `).bind(
    fact.source_id, fact.agent, fact.client, fact.window_start, fact.window_end,
    fact.ai_provider, fact.ai_account_id, fact.attribution_confidence, fact.provenance, fact.fact_id,
  );
}

function factStatement(db: D1Database, fact: UsageHourlyFact, seenAt: string): D1PreparedStatement {
  return db.prepare(`
    INSERT INTO usage_hourly_facts (
      fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
      window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
      cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
      session_count, attribution_confidence, provenance, account_evidence_json, metadata_json,
      first_seen_at, last_seen_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(
      source_id, agent, client, window_start, window_end,
      ai_provider, ai_account_id, attribution_confidence, provenance
    ) DO UPDATE SET
      fact_id = excluded.fact_id,
      source_id = excluded.source_id,
      machine_id = excluded.machine_id,
      os_user = excluded.os_user,
      ai_provider = excluded.ai_provider,
      ai_account_id = excluded.ai_account_id,
      agent = excluded.agent,
      client = excluded.client,
      window_start = excluded.window_start,
      window_end = excluded.window_end,
      timezone = excluded.timezone,
      input_tokens = excluded.input_tokens,
      output_tokens = excluded.output_tokens,
      cache_creation_tokens = excluded.cache_creation_tokens,
      cache_read_tokens = excluded.cache_read_tokens,
      reasoning_output_tokens = excluded.reasoning_output_tokens,
      total_tokens = excluded.total_tokens,
      total_cost = excluded.total_cost,
      event_count = excluded.event_count,
      session_count = excluded.session_count,
      attribution_confidence = excluded.attribution_confidence,
      provenance = excluded.provenance,
      account_evidence_json = excluded.account_evidence_json,
      metadata_json = excluded.metadata_json,
      last_seen_at = excluded.last_seen_at
    WHERE usage_hourly_facts.fact_id IS NOT excluded.fact_id
       OR usage_hourly_facts.machine_id IS NOT excluded.machine_id
       OR usage_hourly_facts.os_user IS NOT excluded.os_user
       OR usage_hourly_facts.timezone IS NOT excluded.timezone
       OR usage_hourly_facts.input_tokens IS NOT excluded.input_tokens
       OR usage_hourly_facts.output_tokens IS NOT excluded.output_tokens
       OR usage_hourly_facts.cache_creation_tokens IS NOT excluded.cache_creation_tokens
       OR usage_hourly_facts.cache_read_tokens IS NOT excluded.cache_read_tokens
       OR usage_hourly_facts.reasoning_output_tokens IS NOT excluded.reasoning_output_tokens
       OR usage_hourly_facts.total_tokens IS NOT excluded.total_tokens
       OR usage_hourly_facts.total_cost IS NOT excluded.total_cost
       OR usage_hourly_facts.event_count IS NOT excluded.event_count
       OR usage_hourly_facts.session_count IS NOT excluded.session_count
       OR usage_hourly_facts.account_evidence_json IS NOT excluded.account_evidence_json
       OR usage_hourly_facts.metadata_json IS NOT excluded.metadata_json
  `).bind(...factParams(fact), seenAt, seenAt);
}

function staleCurrentFactModelsStatement(db: D1Database, fact: UsageHourlyFact): D1PreparedStatement {
  const models = fact.model_breakdowns.map((model) => String(model.model ?? model.model_name ?? "unknown"));
  if (!models.length) {
    return db.prepare("DELETE FROM usage_hourly_models WHERE fact_id = ?").bind(fact.fact_id);
  }
  return db.prepare(`
    DELETE FROM usage_hourly_models
    WHERE fact_id = ? AND model NOT IN (${models.map(() => "?").join(", ")})
  `).bind(fact.fact_id, ...models);
}

function hourlyFactModelStatement(db: D1Database, fact: UsageHourlyFact, model: AnyRecord, seenAt: string): D1PreparedStatement {
  const modelName = String(model.model ?? model.model_name ?? "unknown");
  const values = {
    input_tokens: Number(model.input_tokens ?? 0),
    output_tokens: Number(model.output_tokens ?? 0),
    cache_creation_tokens: Number(model.cache_creation_tokens ?? 0),
    cache_read_tokens: Number(model.cache_read_tokens ?? 0),
    reasoning_output_tokens: Number(model.reasoning_output_tokens ?? 0),
    total_tokens: Number(model.total_tokens ?? 0),
    total_cost: model.total_cost === undefined || model.total_cost === null ? null : Number(model.total_cost),
    metadata_json: stableStringify(model),
  };
  return db.prepare(`
    INSERT INTO usage_hourly_models (
      fact_id, model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
      reasoning_output_tokens, total_tokens, total_cost, metadata_json, first_seen_at, last_seen_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(fact_id, model) DO UPDATE SET
      input_tokens = excluded.input_tokens,
      output_tokens = excluded.output_tokens,
      cache_creation_tokens = excluded.cache_creation_tokens,
      cache_read_tokens = excluded.cache_read_tokens,
      reasoning_output_tokens = excluded.reasoning_output_tokens,
      total_tokens = excluded.total_tokens,
      total_cost = excluded.total_cost,
      metadata_json = excluded.metadata_json,
      last_seen_at = excluded.last_seen_at
    WHERE usage_hourly_models.input_tokens IS NOT excluded.input_tokens
       OR usage_hourly_models.output_tokens IS NOT excluded.output_tokens
       OR usage_hourly_models.cache_creation_tokens IS NOT excluded.cache_creation_tokens
       OR usage_hourly_models.cache_read_tokens IS NOT excluded.cache_read_tokens
       OR usage_hourly_models.reasoning_output_tokens IS NOT excluded.reasoning_output_tokens
       OR usage_hourly_models.total_tokens IS NOT excluded.total_tokens
       OR usage_hourly_models.total_cost IS NOT excluded.total_cost
       OR usage_hourly_models.metadata_json IS NOT excluded.metadata_json
  `).bind(
    fact.fact_id, modelName, values.input_tokens, values.output_tokens, values.cache_creation_tokens,
    values.cache_read_tokens, values.reasoning_output_tokens, values.total_tokens,
    values.total_cost, values.metadata_json, seenAt, seenAt,
  );
}

function limitWindowStatements(db: D1Database, window: LimitWindow, seenAt: string): D1PreparedStatement[] {
  const statements: D1PreparedStatement[] = [];
  if (window.status !== "provider_failed") {
    statements.push(db.prepare(`
      DELETE FROM limit_windows
      WHERE source_id = ? AND provider = ? AND source_type = 'provider_runtime' AND status = 'provider_failed'
        AND julianday(observed_at) < julianday(?)
    `).bind(window.source_id, window.provider, window.observed_at));
  }
  statements.push(db.prepare(`
    INSERT INTO limit_windows (
      source_id, provider, window, used_percent, remaining_percent, reset_at,
      window_duration_minutes, source_type, confidence, status, observed_at, first_seen_at, last_seen_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(source_id, provider, window) DO UPDATE SET
      used_percent = excluded.used_percent,
      remaining_percent = excluded.remaining_percent,
      reset_at = excluded.reset_at,
      window_duration_minutes = excluded.window_duration_minutes,
      source_type = excluded.source_type,
      confidence = excluded.confidence,
      status = excluded.status,
      observed_at = excluded.observed_at,
      last_seen_at = excluded.last_seen_at
    WHERE julianday(excluded.observed_at) >= julianday(limit_windows.observed_at)
      AND (limit_windows.used_percent IS NOT excluded.used_percent
       OR limit_windows.remaining_percent IS NOT excluded.remaining_percent
       OR limit_windows.reset_at IS NOT excluded.reset_at
       OR limit_windows.window_duration_minutes IS NOT excluded.window_duration_minutes
       OR limit_windows.source_type IS NOT excluded.source_type
       OR limit_windows.confidence IS NOT excluded.confidence
       OR limit_windows.status IS NOT excluded.status
       OR limit_windows.observed_at IS NOT excluded.observed_at)
  `).bind(
    window.source_id, window.provider, window.window, window.used_percent, window.remaining_percent,
    window.reset_at, window.window_duration_minutes, window.source_type, window.confidence,
    window.status, window.observed_at, seenAt, seenAt,
  ));
  return statements;
}

function collectionReportStatements(
  db: D1Database,
  collectedAt: string,
  timezone: string,
  status: string,
  report: AnyRecord,
): D1PreparedStatement[] {
  return [
    db.prepare(
      "INSERT INTO collection_runs (collected_at, timezone, collector_version, status) VALUES (?, ?, ?, ?)",
    ).bind(collectedAt, timezone, "0.1.0", status),
    db.prepare(`
      INSERT INTO source_reports (
        run_id, source_id, report_type, command, status, ccusage_version,
        first_period, last_period, error_type, error_message
      ) VALUES (
        (
          SELECT id
          FROM collection_runs
          WHERE collected_at = ? AND timezone = ? AND status = ?
          ORDER BY id DESC
          LIMIT 1
        ),
        ?, ?, ?, ?, ?, ?, ?, ?, ?
      )
    `).bind(
      collectedAt, timezone, status,
      report.source_id, report.report_type, report.command, report.status,
      report.ccusage_version, report.first_period, report.last_period, report.error_type, report.error_message,
    ),
    db.prepare(`
      INSERT INTO source_report_states (
        source_id, collected_at, report_type, command, status, ccusage_version,
        first_period, last_period, error_type, error_message
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(source_id) DO UPDATE SET
        collected_at = excluded.collected_at,
        report_type = excluded.report_type,
        command = excluded.command,
        status = excluded.status,
        ccusage_version = excluded.ccusage_version,
        first_period = excluded.first_period,
        last_period = excluded.last_period,
        error_type = excluded.error_type,
        error_message = excluded.error_message
      WHERE excluded.collected_at >= source_report_states.collected_at
    `).bind(
      report.source_id, collectedAt, report.report_type, report.command, report.status,
      report.ccusage_version, report.first_period, report.last_period, report.error_type, report.error_message,
    ),
  ];
}

function validateIngestPayload(payload: unknown): IngestRequest {
  if (!isRecord(payload)) throw new WriteValidationError(400, "http_schema_invalid", "Payload must be a JSON object");
  const jsonBytes = new TextEncoder().encode(JSON.stringify(payload)).length;
  if (jsonBytes > 50 * 1024 * 1024) {
    throw new WriteValidationError(400, "http_schema_invalid", "Payload size exceeds 50MB limit");
  }
  for (const field of ["schema_version", "source_id", "host", "os_user", "timezone", "observed_at"]) {
    if (!(field in payload)) throw new WriteValidationError(400, "http_schema_invalid", `Missing required field: ${field}`);
  }
  if (!Number.isInteger(payload.schema_version)) {
    throw new WriteValidationError(400, "http_schema_invalid", `schema_version must be an integer, got: ${String(payload.schema_version)}`);
  }
  scanIngestSensitive(payload);
  const usageHourlyFacts = payload.usage_hourly_facts;
  if (usageHourlyFacts !== undefined) {
    if (!Array.isArray(usageHourlyFacts)) throw new WriteValidationError(400, "http_schema_invalid", "usage_hourly_facts must be a list");
    usageHourlyFacts.forEach((fact, index) => {
      if (!isRecord(fact)) throw new WriteValidationError(400, "http_schema_invalid", `usage_hourly_facts[${index}] must be an object`);
      for (const key of ["fact_id", "agent", "window_start", "window_end", "usage", "attribution_confidence", "provenance"]) {
        if (!(key in fact)) throw new WriteValidationError(400, "http_schema_invalid", `usage_hourly_facts[${index}].${key} is required`);
      }
      if (!isRecord(fact.usage)) throw new WriteValidationError(400, "http_schema_invalid", `usage_hourly_facts[${index}].usage must be an object`);
      if (fact.ai_account !== undefined && !isRecord(fact.ai_account)) {
        throw new WriteValidationError(400, "http_schema_invalid", `usage_hourly_facts[${index}].ai_account must be an object`);
      }
    });
  }
  const usageLedgerRuns = payload.usage_ledger_runs;
  if (usageLedgerRuns !== undefined) {
    if (!Array.isArray(usageLedgerRuns)) throw new WriteValidationError(400, "http_schema_invalid", "usage_ledger_runs must be a list");
    usageLedgerRuns.forEach((run, index) => {
      if (!isRecord(run)) throw new WriteValidationError(400, "http_schema_invalid", `usage_ledger_runs[${index}] must be an object`);
      if (!run.agent || !run.provenance || !isRecord(run.collector) || typeof run.facts_digest !== "string") {
        throw new WriteValidationError(400, "http_schema_invalid", `usage_ledger_runs[${index}] is incomplete`);
      }
    });
  }
  for (const key of ["ccusage_daily_report", "ccusage_session_report", "ccusage_blocks_report", "mswusage_codex_hourly_report", "codex_hourly_status"]) {
    if (payload[key] !== undefined && !isRecord(payload[key])) {
      throw new WriteValidationError(400, "http_schema_invalid", `${key} must be an object`);
    }
  }
  return {
    schema_version: Number(payload.schema_version),
    source_id: String(payload.source_id),
    host: String(payload.host),
    machine: payload.machine ? String(payload.machine) : null,
    os_user: String(payload.os_user),
    platform: String(payload.platform ?? "unknown"),
    timezone: String(payload.timezone),
    observed_at: String(payload.observed_at),
    collection_window: String(payload.collection_window ?? "daily"),
    usage_daily: Array.isArray(payload.usage_daily) ? payload.usage_daily.filter(isRecord) : [],
    ccusage_daily_report: isRecord(payload.ccusage_daily_report) ? payload.ccusage_daily_report : undefined,
    ccusage_session_report: isRecord(payload.ccusage_session_report) ? payload.ccusage_session_report : undefined,
    ccusage_blocks_report: isRecord(payload.ccusage_blocks_report) ? payload.ccusage_blocks_report : undefined,
    mswusage_codex_hourly_report: isRecord(payload.mswusage_codex_hourly_report) ? payload.mswusage_codex_hourly_report : undefined,
    codex_hourly_status: isRecord(payload.codex_hourly_status) ? payload.codex_hourly_status : undefined,
    usage_hourly_facts: Array.isArray(usageHourlyFacts) ? usageHourlyFacts.filter(isRecord) : undefined,
    usage_ledger_runs: Array.isArray(usageLedgerRuns) ? usageLedgerRuns.filter(isRecord) : undefined,
    collection_status: String(payload.collection_status || "ok"),
    error_type: payload.error_type ? String(payload.error_type) : null,
    error_message: payload.error_message ? String(payload.error_message) : null,
  };
}

async function buildAccuracyPlans(db: D1Database, req: IngestRequest, acceptedAt: string): Promise<AccuracyPlan[]> {
  const plans: AccuracyPlan[] = [];
  for (const run of req.usage_ledger_runs ?? []) {
    const collector = isRecord(run.collector) ? run.collector : {};
    const counts = isRecord(collector.counts) ? collector.counts : {};
    const coverage = isRecord(collector.coverage) ? collector.coverage : {};
    const sourceId = req.source_id;
    const agent = String(run.agent);
    const provenance = String(run.provenance);
    const version = String(collector.version ?? "");
    const parserSchema = intField(collector, "parser_schema_version");
    const mode = String(collector.mode ?? "unknown");
    const digest = String(collector.report_digest ?? "");
    const claimedFactsDigest = String(run.facts_digest ?? "");
    const coverageStart = coverage.start ? String(coverage.start) : null;
    const coverageEnd = coverage.end ? String(coverage.end) : null;
    const readErrors = intField(counts, "read_errors");
    const unresolvedMismatch = intField(counts, "unresolved_mismatch");
    const scanComplete = collector.scan_complete === true;
    const computedFactsDigest = await factsDigestForRun(req, agent, provenance, coverageStart, coverageEnd);
    const factsDigestMatches = !!claimedFactsDigest && claimedFactsDigest === computedFactsDigest;
    const completeFullScan = mode === "full-rescan" && scanComplete && readErrors === 0 && unresolvedMismatch === 0 && !!version && parserSchema > 0 && !!digest && factsDigestMatches;
    const previous = await db.prepare(`
      SELECT provenance, collector_version, parser_schema_version, mode, coverage_start, coverage_end,
             report_digest, facts_digest, scan_complete, read_errors, unresolved_mismatch,
             matching_full_scans, accuracy_status, verified_at, observed_at
      FROM source_accuracy
      WHERE source_id = ? AND agent = ?
    `).bind(sourceId, agent).first<AnyRecord>();
    const sameCompleteScan = completeFullScan && !!previous &&
      String(previous.provenance ?? "") === provenance &&
      String(previous.collector_version ?? "") === version &&
      Number(previous.parser_schema_version ?? 0) === parserSchema &&
      String(previous.report_digest ?? "") === digest &&
      String(previous.facts_digest ?? "") === claimedFactsDigest &&
      (previous.coverage_start ?? null) === coverageStart &&
      (previous.coverage_end ?? null) === coverageEnd &&
      Number(previous.scan_complete ?? 0) === 1 &&
      Number(previous.read_errors ?? 0) === 0 &&
      Number(previous.unresolved_mismatch ?? 0) === 0;
    const replayedScan = sameCompleteScan && String(previous?.observed_at ?? "") === acceptedAt;
    let matching = replayedScan
      ? Number(previous?.matching_full_scans ?? 0)
      : completeFullScan
        ? (sameCompleteScan ? Math.min(Number(previous?.matching_full_scans ?? 0) + 1, 2) : 1)
        : 0;
    const hasAuthoritativeCoverage = !!coverageStart && !!coverageEnd && coverageStart < coverageEnd;
    let accuracyStatus: "unverified" | "verified" = replayedScan
      ? (previous?.accuracy_status === "verified" ? "verified" : "unverified")
      : matching >= 2 && hasAuthoritativeCoverage ? "verified" : "unverified";
    let verifiedAt = accuracyStatus === "verified" ? String(previous?.verified_at ?? acceptedAt) : null;
    if (mode === "incremental" && previous?.accuracy_status === "verified" &&
        String(previous.provenance ?? "") === provenance &&
        String(previous.collector_version ?? "") === version && Number(previous.parser_schema_version ?? 0) === parserSchema) {
      matching = Number(previous.matching_full_scans ?? 2);
      accuracyStatus = "verified";
      verifiedAt = String(previous.verified_at ?? acceptedAt);
    }
    plans.push({
      source_id: sourceId,
      agent,
      provenance,
      collector,
      facts_digest: claimedFactsDigest,
      coverage_start: coverageStart,
      coverage_end: coverageEnd,
      matching_full_scans: matching,
      accuracy_status: accuracyStatus,
      verified_at: verifiedAt,
      can_reconcile: completeFullScan && matching >= 2 && hasAuthoritativeCoverage,
    });
  }
  return plans;
}

function filterFactsByLedgerCoverage(req: IngestRequest, facts: UsageHourlyFact[]): UsageHourlyFact[] {
  const authoritativeRuns = (req.usage_ledger_runs ?? []).filter((run) => {
    const collector = isRecord(run.collector) ? run.collector : {};
    const coverage = isRecord(collector.coverage) ? collector.coverage : {};
    return collector.mode === "full-rescan" && !!coverage.start && !!coverage.end && String(coverage.start) < String(coverage.end);
  });
  if (!authoritativeRuns.length) return facts;
  return facts.filter((fact) => {
    const run = authoritativeRuns.find((candidate) =>
      String(candidate.agent ?? "") === fact.agent && String(candidate.provenance ?? "") === fact.provenance,
    );
    if (!run) return true;
    const collector = isRecord(run.collector) ? run.collector : {};
    const coverage = isRecord(collector.coverage) ? collector.coverage : {};
    return fact.window_start >= String(coverage.start) && fact.window_start < String(coverage.end);
  });
}

async function factsDigestForRun(
  req: IngestRequest,
  agent: string,
  provenance: string,
  coverageStart: string | null,
  coverageEnd: string | null,
): Promise<string> {
  const canonical = (req.usage_hourly_facts ?? [])
    .filter((fact) => String(fact.agent ?? "") === agent && String(fact.provenance ?? "") === provenance)
    .filter((fact) => !coverageStart || String(fact.window_start ?? "") >= coverageStart)
    .filter((fact) => !coverageEnd || String(fact.window_start ?? "") < coverageEnd)
    .map((fact) => ({
      fact_id: fact.fact_id,
      agent: fact.agent,
      client: fact.client,
      window_start: fact.window_start,
      window_end: fact.window_end,
      usage: fact.usage,
      event_count: fact.event_count,
      session_count: fact.session_count,
      attribution_confidence: fact.attribution_confidence,
      provenance: fact.provenance,
    }))
    .sort((left, right) => String(left.fact_id).localeCompare(String(right.fact_id)));
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(stableStringify(canonical)));
  return Array.from(new Uint8Array(digest)).map((value) => value.toString(16).padStart(2, "0")).join("");
}

function accuracyWriteStatements(
  db: D1Database,
  plans: AccuracyPlan[],
  facts: UsageHourlyFact[],
  acceptedAt: string,
  sourceId: string,
): D1PreparedStatement[] {
  const statements: D1PreparedStatement[] = [];
  const reportedAgents = plans.map((plan) => plan.agent);
  if (!reportedAgents.length) {
    statements.push(db.prepare(`
      UPDATE source_accuracy
      SET accuracy_status = 'unknown', mode = 'legacy', matching_full_scans = 0,
          scan_complete = 0, observed_at = ?, last_seen_at = ?
      WHERE source_id = ?
    `).bind(acceptedAt, acceptedAt, sourceId));
  } else {
    statements.push(db.prepare(`
      UPDATE source_accuracy
      SET accuracy_status = 'unknown', mode = 'legacy', matching_full_scans = 0,
          scan_complete = 0, observed_at = ?, last_seen_at = ?
      WHERE source_id = ? AND agent NOT IN (${reportedAgents.map(() => "?").join(", ")})
    `).bind(acceptedAt, acceptedAt, sourceId, ...reportedAgents));
  }
  for (const plan of plans) {
    const collector = plan.collector;
    const counts = isRecord(collector.counts) ? collector.counts : {};
    statements.push(db.prepare(`
      INSERT INTO source_accuracy (
        source_id, agent, provenance, collector_version, parser_schema_version, mode,
        lookback_hours, coverage_start, coverage_end, report_digest, facts_digest, scan_complete,
        read_errors, unresolved_mismatch, matching_full_scans, accuracy_status,
        verified_at, metadata_json, observed_at, first_seen_at, last_seen_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(source_id, agent) DO UPDATE SET
        provenance = excluded.provenance,
        collector_version = excluded.collector_version,
        parser_schema_version = excluded.parser_schema_version,
        mode = excluded.mode,
        lookback_hours = excluded.lookback_hours,
        coverage_start = excluded.coverage_start,
        coverage_end = excluded.coverage_end,
        report_digest = excluded.report_digest,
        facts_digest = excluded.facts_digest,
        scan_complete = excluded.scan_complete,
        read_errors = excluded.read_errors,
        unresolved_mismatch = excluded.unresolved_mismatch,
        matching_full_scans = excluded.matching_full_scans,
        accuracy_status = excluded.accuracy_status,
        verified_at = excluded.verified_at,
        metadata_json = excluded.metadata_json,
        observed_at = excluded.observed_at,
        last_seen_at = excluded.last_seen_at
    `).bind(
      plan.source_id, plan.agent, plan.provenance, String(collector.version ?? ""),
      intField(collector, "parser_schema_version"), String(collector.mode ?? "unknown"),
      optionalFloat(collector, "lookback_hours"), plan.coverage_start, plan.coverage_end,
      String(collector.report_digest ?? ""), plan.facts_digest, collector.scan_complete === true ? 1 : 0,
      intField(counts, "read_errors"), intField(counts, "unresolved_mismatch"),
      plan.matching_full_scans, plan.accuracy_status, plan.verified_at,
      stableStringify(collector), acceptedAt, acceptedAt, acceptedAt,
    ));
    if (!plan.can_reconcile) continue;
    const matchingFacts = facts.filter((fact) => fact.source_id === plan.source_id && fact.agent === plan.agent && fact.provenance === plan.provenance &&
      fact.window_start >= String(plan.coverage_start) && fact.window_start < String(plan.coverage_end));
    for (const fact of matchingFacts) {
      statements.push(db.prepare("UPDATE usage_hourly_facts SET last_seen_at = ? WHERE fact_id = ?").bind(acceptedAt, fact.fact_id));
    }
    statements.push(db.prepare(`
      DELETE FROM usage_hourly_models
      WHERE fact_id IN (
        SELECT fact_id FROM usage_hourly_facts
        WHERE source_id = ? AND agent = ? AND provenance = ?
          AND window_start >= ? AND window_start < ? AND last_seen_at IS NOT ?
      )
    `).bind(plan.source_id, plan.agent, plan.provenance, plan.coverage_start, plan.coverage_end, acceptedAt));
    statements.push(db.prepare(`
      DELETE FROM usage_hourly_facts
      WHERE source_id = ? AND agent = ? AND provenance = ?
        AND window_start >= ? AND window_start < ? AND last_seen_at IS NOT ?
    `).bind(plan.source_id, plan.agent, plan.provenance, plan.coverage_start, plan.coverage_end, acceptedAt));
  }
  return statements;
}

function validateLimitsPayload(payload: unknown): { observedAt: string; windows: LimitWindow[] } {
  if (!isRecord(payload)) throw new WriteValidationError(400, "limit_schema_invalid", "limits payload must be an object");
  rejectSensitiveLimitKeys(payload);
  if (payload.schema_version !== 1) throw new WriteValidationError(400, "limit_schema_invalid", "schema_version must be 1");
  const observedAt = requireIsoString(payload, "observed_at");
  if (!Array.isArray(payload.windows)) throw new WriteValidationError(400, "limit_schema_invalid", "windows must be a list");
  return {
    observedAt,
    windows: payload.windows.map((item) => {
      if (!isRecord(item)) throw new WriteValidationError(400, "limit_schema_invalid", "limit window must be an object");
      rejectSensitiveLimitKeys(item);
      return parseLimitWindow(item);
    }),
  };
}

function parseLimitWindow(payload: AnyRecord): LimitWindow {
  for (const field of ["provider", "window", "reset_at", "observed_at"]) {
    if (!(field in payload)) throw new WriteValidationError(400, "limit_schema_invalid", `missing required limit field: ${field}`);
  }
  const provider = nonEmptyString(payload, "provider");
  const window = {
    provider,
    source_id: optionalString(payload, "source_id", provider),
    window: nonEmptyString(payload, "window"),
    used_percent: percent(payload, "used_percent"),
    remaining_percent: percent(payload, "remaining_percent"),
    reset_at: requireIsoString(payload, "reset_at"),
    window_duration_minutes: positiveInt(payload, "window_duration_minutes"),
    observed_at: requireIsoString(payload, "observed_at"),
    source_type: optionalString(payload, "source_type", "unknown"),
    confidence: optionalString(payload, "confidence", "unknown"),
    status: optionalString(payload, "status", "unknown"),
  };
  if (window.source_type === "active_limits_cache" && (window.confidence === "observed" || window.status === "ok")) {
    throw new WriteValidationError(400, "limit_schema_invalid", "active_limits_cache cannot claim observed or current status");
  }
  if (window.status === "ok" && new Date(window.reset_at).getTime() <= new Date(window.observed_at).getTime()) {
    throw new WriteValidationError(400, "limit_schema_invalid", "reset_at must be later than observed_at when status is ok");
  }
  return window;
}

function normalizeFacts(req: IngestRequest): UsageHourlyFact[] {
  const device = {
    machine_id: req.machine ?? req.host ?? req.source_id,
    machine_name: req.machine ?? req.host ?? req.source_id,
    host: req.host,
    platform: req.platform,
    os_user: req.os_user,
  };
  const seen = new Map<string, UsageHourlyFact>();
  for (const row of req.usage_hourly_facts ?? []) {
    const rowDevice = isRecord(row.device) ? row.device : {};
    const aiAccount = isRecord(row.ai_account) ? row.ai_account : {};
    const usage = isRecord(row.usage) ? row.usage : {};
    const fact: UsageHourlyFact = {
      fact_id: String(row.fact_id),
      source_id: req.source_id,
      machine_id: String(rowDevice.machine_id ?? device.machine_id),
      machine_name: String(rowDevice.machine_name ?? device.machine_name),
      host: String(rowDevice.host ?? device.host ?? ""),
      os_user: String(rowDevice.os_user ?? device.os_user),
      platform: String(rowDevice.platform ?? device.platform),
      ai_provider: String(aiAccount.provider ?? "unknown"),
      ai_account_id: String(aiAccount.account_id ?? "unknown"),
      ai_account_label: String(aiAccount.label ?? aiAccount.account_id ?? "unknown"),
      ai_account_display_name: aiAccount.display_name !== undefined && aiAccount.display_name !== null ? String(aiAccount.display_name) : null,
      ai_account_subscription: aiAccount.subscription !== undefined && aiAccount.subscription !== null ? String(aiAccount.subscription) : null,
      agent: String(row.agent ?? "unknown"),
      client: String(row.client ?? row.agent ?? "unknown"),
      window_start: String(row.window_start),
      window_end: String(row.window_end),
      timezone: req.timezone,
      input_tokens: intField(usage, "input_tokens"),
      output_tokens: intField(usage, "output_tokens"),
      cache_creation_tokens: intField(usage, "cache_creation_tokens"),
      cache_read_tokens: intField(usage, "cache_read_tokens"),
      reasoning_output_tokens: intField(usage, "reasoning_output_tokens"),
      total_tokens: intField(usage, "total_tokens"),
      total_cost: optionalFloat(usage, "total_cost"),
      event_count: intField(row, "event_count"),
      session_count: intField(row, "session_count"),
      attribution_confidence: String(row.attribution_confidence ?? "account_unknown"),
      provenance: String(row.provenance ?? "unknown"),
      account_evidence: isRecord(row.account_evidence) ? row.account_evidence : {},
      metadata: isRecord(row.metadata) ? row.metadata : {},
      model_breakdowns: Array.isArray(row.model_breakdowns) ? row.model_breakdowns.filter(isRecord) : [],
    };
    seen.set(fact.fact_id, fact);
  }
  return Array.from(seen.values());
}

async function upsertHourlyFact(db: D1Database, fact: UsageHourlyFact, seenAt: string): Promise<number> {
  let written = 0;
  written += await upsertMachine(db, fact, seenAt);
  written += await upsertOsIdentity(db, fact, seenAt);
  written += await upsertAiAccount(db, fact, seenAt);
  const existing = await db.prepare(`
    SELECT fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
           window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
           cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
           session_count, attribution_confidence, provenance, account_evidence_json, metadata_json
    FROM usage_hourly_facts
    WHERE source_id = ? AND agent = ? AND client = ? AND window_start = ? AND window_end = ?
      AND ai_provider = ? AND ai_account_id = ? AND attribution_confidence = ? AND provenance = ?
  `).bind(
    fact.source_id, fact.agent, fact.client, fact.window_start, fact.window_end,
    fact.ai_provider, fact.ai_account_id, fact.attribution_confidence, fact.provenance,
  ).first<AnyRecord>();
  const compare = factCompare(fact);
  const existingFactId = existing?.fact_id ? String(existing.fact_id) : null;
  if (!existing) {
    await insertFact(db, fact, seenAt);
    written += 1;
  } else if (!rowMatches(existing, compare)) {
    await updateFact(db, fact, seenAt, existingFactId);
    written += 1;
  }
  written += await syncHourlyFactModels(db, fact, existingFactId, seenAt);
  return written;
}

async function upsertMachine(db: D1Database, fact: UsageHourlyFact, seenAt: string): Promise<number> {
  return upsertIfChanged(db, {
    select: "SELECT machine_name, host, platform FROM machines WHERE machine_id = ?",
    keyParams: [fact.machine_id],
    compare: { machine_name: fact.machine_name, host: fact.host, platform: fact.platform },
    insert: "INSERT INTO machines (machine_id, machine_name, host, platform, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?)",
    insertParams: [fact.machine_id, fact.machine_name, fact.host, fact.platform, seenAt, seenAt],
    update: "UPDATE machines SET machine_name = ?, host = ?, platform = ?, last_seen_at = ? WHERE machine_id = ?",
    updateParams: [fact.machine_name, fact.host, fact.platform, seenAt, fact.machine_id],
  });
}

async function upsertOsIdentity(db: D1Database, fact: UsageHourlyFact, seenAt: string): Promise<number> {
  const display = `${fact.machine_name} · ${fact.os_user}`;
  return upsertIfChanged(db, {
    select: "SELECT display_name FROM os_identities WHERE machine_id = ? AND os_user = ?",
    keyParams: [fact.machine_id, fact.os_user],
    compare: { display_name: display },
    insert: "INSERT INTO os_identities (machine_id, os_user, display_name, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?)",
    insertParams: [fact.machine_id, fact.os_user, display, seenAt, seenAt],
    update: "UPDATE os_identities SET display_name = ?, last_seen_at = ? WHERE machine_id = ? AND os_user = ?",
    updateParams: [display, seenAt, fact.machine_id, fact.os_user],
  });
}

async function upsertAiAccount(db: D1Database, fact: UsageHourlyFact, seenAt: string): Promise<number> {
  return upsertIfChanged(db, {
    select: "SELECT account_label, display_name, subscription FROM ai_accounts WHERE provider = ? AND account_id = ?",
    keyParams: [fact.ai_provider, fact.ai_account_id],
    compare: {
      account_label: fact.ai_account_label,
      display_name: fact.ai_account_display_name,
      subscription: fact.ai_account_subscription,
    },
    insert: "INSERT INTO ai_accounts (provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
    insertParams: [
      fact.ai_provider, fact.ai_account_id, fact.ai_account_label,
      fact.ai_account_display_name, fact.ai_account_subscription, seenAt, seenAt,
    ],
    update: "UPDATE ai_accounts SET account_label = ?, display_name = ?, subscription = ?, last_seen_at = ? WHERE provider = ? AND account_id = ?",
    updateParams: [
      fact.ai_account_label, fact.ai_account_display_name, fact.ai_account_subscription,
      seenAt, fact.ai_provider, fact.ai_account_id,
    ],
  });
}

function factCompare(fact: UsageHourlyFact): AnyRecord {
  return {
    fact_id: fact.fact_id,
    source_id: fact.source_id,
    machine_id: fact.machine_id,
    os_user: fact.os_user,
    ai_provider: fact.ai_provider,
    ai_account_id: fact.ai_account_id,
    agent: fact.agent,
    client: fact.client,
    window_start: fact.window_start,
    window_end: fact.window_end,
    timezone: fact.timezone,
    input_tokens: fact.input_tokens,
    output_tokens: fact.output_tokens,
    cache_creation_tokens: fact.cache_creation_tokens,
    cache_read_tokens: fact.cache_read_tokens,
    reasoning_output_tokens: fact.reasoning_output_tokens,
    total_tokens: fact.total_tokens,
    total_cost: fact.total_cost,
    event_count: fact.event_count,
    session_count: fact.session_count,
    attribution_confidence: fact.attribution_confidence,
    provenance: fact.provenance,
    account_evidence_json: stableStringify(fact.account_evidence),
    metadata_json: stableStringify(fact.metadata),
  };
}

async function insertFact(db: D1Database, fact: UsageHourlyFact, seenAt: string): Promise<void> {
  await db.prepare(`
    INSERT INTO usage_hourly_facts (
      fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
      window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
      cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
      session_count, attribution_confidence, provenance, account_evidence_json, metadata_json,
      first_seen_at, last_seen_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).bind(...factParams(fact), seenAt, seenAt).run();
}

async function updateFact(db: D1Database, fact: UsageHourlyFact, seenAt: string, existingFactId: string | null): Promise<void> {
  if (existingFactId && existingFactId !== fact.fact_id) {
    await db.prepare("DELETE FROM usage_hourly_models WHERE fact_id = ?").bind(existingFactId).run();
  }
  await db.prepare(`
    UPDATE usage_hourly_facts
    SET fact_id = ?, source_id = ?, machine_id = ?, os_user = ?, ai_provider = ?,
        ai_account_id = ?, agent = ?, client = ?, window_start = ?, window_end = ?,
        timezone = ?, input_tokens = ?, output_tokens = ?, cache_creation_tokens = ?,
        cache_read_tokens = ?, reasoning_output_tokens = ?, total_tokens = ?, total_cost = ?,
        event_count = ?, session_count = ?, attribution_confidence = ?, provenance = ?,
        account_evidence_json = ?, metadata_json = ?, last_seen_at = ?
    WHERE source_id = ? AND agent = ? AND client = ? AND window_start = ? AND window_end = ?
      AND ai_provider = ? AND ai_account_id = ? AND attribution_confidence = ? AND provenance = ?
  `).bind(
    ...factParams(fact), seenAt,
    fact.source_id, fact.agent, fact.client, fact.window_start, fact.window_end,
    fact.ai_provider, fact.ai_account_id, fact.attribution_confidence, fact.provenance,
  ).run();
}

function factParams(fact: UsageHourlyFact): unknown[] {
  return [
    fact.fact_id, fact.source_id, fact.machine_id, fact.os_user, fact.ai_provider,
    fact.ai_account_id, fact.agent, fact.client, fact.window_start, fact.window_end,
    fact.timezone, fact.input_tokens, fact.output_tokens, fact.cache_creation_tokens,
    fact.cache_read_tokens, fact.reasoning_output_tokens, fact.total_tokens, fact.total_cost,
    fact.event_count, fact.session_count, fact.attribution_confidence, fact.provenance,
    stableStringify(fact.account_evidence), stableStringify(fact.metadata),
  ];
}

async function syncHourlyFactModels(db: D1Database, fact: UsageHourlyFact, existingFactId: string | null, seenAt: string): Promise<number> {
  const expected = new Map<string, AnyRecord>();
  for (const model of fact.model_breakdowns) {
    const name = String(model.model ?? model.model_name ?? "unknown");
    expected.set(name, {
      input_tokens: Number(model.input_tokens ?? 0),
      output_tokens: Number(model.output_tokens ?? 0),
      cache_creation_tokens: Number(model.cache_creation_tokens ?? 0),
      cache_read_tokens: Number(model.cache_read_tokens ?? 0),
      reasoning_output_tokens: Number(model.reasoning_output_tokens ?? 0),
      total_tokens: Number(model.total_tokens ?? 0),
      total_cost: model.total_cost === undefined || model.total_cost === null ? null : Number(model.total_cost),
      metadata_json: stableStringify(model),
    });
  }
  let written = 0;
  for (const id of new Set([existingFactId, fact.fact_id].filter(Boolean))) {
    const rows = await db.prepare("SELECT model FROM usage_hourly_models WHERE fact_id = ?").bind(id).all<{ model: string }>();
    for (const row of rows.results ?? []) {
      if (id === fact.fact_id && expected.has(row.model)) continue;
      await db.prepare("DELETE FROM usage_hourly_models WHERE fact_id = ? AND model = ?").bind(id, row.model).run();
      written += 1;
    }
  }
  for (const [model, values] of expected.entries()) {
    written += await upsertIfChanged(db, {
      select: `SELECT input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
                      reasoning_output_tokens, total_tokens, total_cost, metadata_json
               FROM usage_hourly_models WHERE fact_id = ? AND model = ?`,
      keyParams: [fact.fact_id, model],
      compare: values,
      insert: `
        INSERT INTO usage_hourly_models (
          fact_id, model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
          reasoning_output_tokens, total_tokens, total_cost, metadata_json, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `,
      insertParams: [
        fact.fact_id, model, values.input_tokens, values.output_tokens, values.cache_creation_tokens,
        values.cache_read_tokens, values.reasoning_output_tokens, values.total_tokens,
        values.total_cost, values.metadata_json, seenAt, seenAt,
      ],
      update: `
        UPDATE usage_hourly_models
        SET input_tokens = ?, output_tokens = ?, cache_creation_tokens = ?, cache_read_tokens = ?,
            reasoning_output_tokens = ?, total_tokens = ?, total_cost = ?, metadata_json = ?, last_seen_at = ?
        WHERE fact_id = ? AND model = ?
      `,
      updateParams: [
        values.input_tokens, values.output_tokens, values.cache_creation_tokens, values.cache_read_tokens,
        values.reasoning_output_tokens, values.total_tokens, values.total_cost, values.metadata_json,
        seenAt, fact.fact_id, model,
      ],
    });
  }
  return written;
}

async function insertCollectionRun(db: D1Database, collectedAt: string, timezone: string, status: string): Promise<number> {
  const result = await db.prepare(
    "INSERT INTO collection_runs (collected_at, timezone, collector_version, status) VALUES (?, ?, ?, ?)",
  ).bind(collectedAt, timezone, "0.1.0", status).run();
  return Number(result.meta.last_row_id);
}

async function insertSourceReport(db: D1Database, runId: number, report: AnyRecord): Promise<void> {
  await db.prepare(`
    INSERT INTO source_reports (
      run_id, source_id, report_type, command, status, ccusage_version,
      first_period, last_period, error_type, error_message
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).bind(
    runId, report.source_id, report.report_type, report.command, report.status,
    report.ccusage_version, report.first_period, report.last_period, report.error_type, report.error_message,
  ).run();
}

async function latestSourceReportState(db: D1Database, report: AnyRecord): Promise<SourceReportState> {
  const existing = await db.prepare(`
    SELECT source_id, report_type, command, status, ccusage_version, first_period, last_period, error_type, error_message
    FROM source_report_states
    WHERE source_id = ?
  `).bind(report.source_id).first<AnyRecord>();
  if (!existing) return { hasExisting: false, changed: true };
  return { hasExisting: true, changed: !rowMatches(existing, report) };
}

async function sourceHasNewerReport(db: D1Database, sourceId: string, observedAt: string): Promise<boolean> {
  const observed = new Date(observedAt);
  if (Number.isNaN(observed.getTime())) return false;
  const existing = await db.prepare(`
    SELECT collected_at
    FROM source_report_states
    WHERE source_id = ?
  `).bind(sourceId).first<{ collected_at: string | null }>();
  if (!existing?.collected_at) return false;
  const latest = new Date(existing.collected_at);
  return !Number.isNaN(latest.getTime()) && latest.getTime() > observed.getTime();
}

function sourceReport(req: IngestRequest, hourlyFacts: UsageHourlyFact[]): AnyRecord {
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
  };
}

async function upsertIfChanged(
  db: D1Database,
  statement: {
    select: string;
    keyParams: unknown[];
    compare: AnyRecord;
    insert: string;
    insertParams: unknown[];
    update: string;
    updateParams: unknown[];
  },
): Promise<number> {
  const existing = await db.prepare(statement.select).bind(...statement.keyParams).first<AnyRecord>();
  if (!existing) {
    await db.prepare(statement.insert).bind(...statement.insertParams).run();
    return 1;
  }
  if (rowMatches(existing, statement.compare)) return 0;
  await db.prepare(statement.update).bind(...statement.updateParams).run();
  return 1;
}

function rowMatches(row: AnyRecord, expected: AnyRecord): boolean {
  for (const [key, value] of Object.entries(expected)) {
    if (!sameValue(row[key], value)) return false;
  }
  return true;
}

function sameValue(left: unknown, right: unknown): boolean {
  if (left === null || left === undefined || right === null || right === undefined) return (left ?? null) === (right ?? null);
  if (typeof left === "number" || typeof right === "number") return Number(left) === Number(right);
  return String(left) === String(right);
}

function newerOrSameIso(candidate: string, existing: string): boolean {
  if (!existing) return true;
  const candidateTime = new Date(candidate).getTime();
  const existingTime = new Date(existing).getTime();
  if (Number.isNaN(candidateTime) || Number.isNaN(existingTime)) return candidate >= existing;
  return candidateTime >= existingTime;
}

function scanIngestSensitive(value: unknown): void {
  if (typeof value === "string") {
    const lower = value.toLowerCase();
    if (lower.includes(".claude") || lower.includes(".codex")) {
      throw new WriteValidationError(400, "http_schema_invalid", `Sensitive logs path or pattern detected in payload: ${value}`);
    }
    return;
  }
  if (Array.isArray(value)) {
    for (const item of value) scanIngestSensitive(item);
    return;
  }
  if (isRecord(value)) {
    for (const [key, item] of Object.entries(value)) {
      const lowerKey = key.toLowerCase();
      if (lowerKey.includes("ssh")) throw new WriteValidationError(400, "http_schema_invalid", `SSH parameters are forbidden in payload key: ${key}`);
      if (lowerKey.includes(".claude") || lowerKey.includes(".codex")) {
        throw new WriteValidationError(400, "http_schema_invalid", `Sensitive logs key detected in payload: ${key}`);
      }
      scanIngestSensitive(item);
    }
  }
}

function rejectSensitiveLimitKeys(payload: AnyRecord): void {
  const present = ["token", "auth_file", "api_key", "secret", "env", "raw_json", "raw"].filter((key) => key in payload);
  if (present.length) {
    throw new WriteValidationError(400, "limit_schema_invalid", `sensitive fields are not accepted: ${present.sort().join(", ")}`);
  }
}

function acceptedAtFromEnv(env: Env): string {
  return env.AIUSAGE_NOW || new Date().toISOString();
}

function intField(row: AnyRecord, name: string): number {
  return row[name] === undefined || row[name] === null ? 0 : Number(row[name]);
}

function optionalFloat(row: AnyRecord, name: string): number | null {
  return row[name] === undefined || row[name] === null ? null : Number(row[name]);
}

function nonEmptyString(payload: AnyRecord, field: string): string {
  const value = payload[field];
  if (typeof value !== "string" || !value.trim()) throw new WriteValidationError(400, "limit_schema_invalid", `${field} must be a non-empty string`);
  return value.trim();
}

function optionalString(payload: AnyRecord, field: string, fallback: string): string {
  const value = payload[field] ?? fallback;
  if (value === null) return fallback;
  if (typeof value !== "string" || !value.trim()) throw new WriteValidationError(400, "limit_schema_invalid", `${field} must be a string`);
  return value.trim();
}

function requireIsoString(payload: AnyRecord, field: string): string {
  const value = nonEmptyString(payload, field);
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) throw new WriteValidationError(400, "limit_schema_invalid", `${field} must be an ISO 8601 datetime`);
  return value;
}

function percent(payload: AnyRecord, field: string): number {
  const value = payload[field] ?? 0;
  if (typeof value === "boolean" || typeof value !== "number") throw new WriteValidationError(400, "limit_schema_invalid", `${field} must be a number`);
  if (value < 0 || value > 100) throw new WriteValidationError(400, "limit_schema_invalid", `${field} must be between 0 and 100`);
  return value;
}

function positiveInt(payload: AnyRecord, field: string): number {
  const value = payload[field] ?? 0;
  if (typeof value !== "number" || !Number.isInteger(value)) throw new WriteValidationError(400, "limit_schema_invalid", `${field} must be an integer`);
  if (value < 0) throw new WriteValidationError(400, "limit_schema_invalid", `${field} must be positive`);
  return value;
}

function isRecord(value: unknown): value is AnyRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  const entries = Object.entries(value as AnyRecord).sort(([left], [right]) => left.localeCompare(right));
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${stableStringify(item)}`).join(",")}}`;
}
