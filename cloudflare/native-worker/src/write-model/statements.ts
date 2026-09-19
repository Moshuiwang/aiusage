/** #126：D1 写语句构造（INSERT/UPDATE/DELETE 的 SQL 只出现在这里）。 */
import { newerOrSameIso, stableStringify } from "./shared";
import type { AnyRecord, LimitWindow, SourceReportState, UsageHourlyFact } from "./shared";

function ingestWriteStatements(
  db: D1Database,
  identity: AnyRecord,
  hourlyFacts: UsageHourlyFact[],
  seenAt: string,
): D1PreparedStatement[] {
  return [
    sourceIdentityStatement(db, identity, seenAt),
    ...factWriteStatements(db, hourlyFacts, seenAt),
  ];
}

function factWriteStatements(
  db: D1Database,
  hourlyFacts: UsageHourlyFact[],
  seenAt: string,
): D1PreparedStatement[] {
  return hourlyFacts.flatMap((fact) => hourlyFactStatements(db, fact, seenAt));
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
       OR CASE
            WHEN json_valid(usage_hourly_facts.account_evidence_json)
              THEN json_remove(usage_hourly_facts.account_evidence_json, '$.observed_at')
            ELSE usage_hourly_facts.account_evidence_json
          END IS NOT CASE
            WHEN json_valid(excluded.account_evidence_json)
              THEN json_remove(excluded.account_evidence_json, '$.observed_at')
            ELSE excluded.account_evidence_json
          END
       OR CASE
            WHEN json_valid(usage_hourly_facts.metadata_json)
              THEN json_remove(
                usage_hourly_facts.metadata_json,
                '$.observed_at', '$.collector.coverage', '$.collector.counts'
              )
            ELSE usage_hourly_facts.metadata_json
          END IS NOT CASE
            WHEN json_valid(excluded.metadata_json)
              THEN json_remove(
                excluded.metadata_json,
                '$.observed_at', '$.collector.coverage', '$.collector.counts'
              )
            ELSE excluded.metadata_json
          END
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
  collectorVersion: string | null,
): D1PreparedStatement[] {
  return [
    // collector_version 只写采集端真实上报的版本；没上报就留 NULL，
    // 读模型据此把该来源判成 unknown，而不是冒充某个版本。
    db.prepare(
      "INSERT INTO collection_runs (collected_at, timezone, collector_version, status) VALUES (?, ?, ?, ?)",
    ).bind(collectedAt, timezone, collectorVersion, status),
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
        first_period, last_period, error_type, error_message, collector_version
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(source_id) DO UPDATE SET
        collected_at = excluded.collected_at,
        report_type = excluded.report_type,
        command = excluded.command,
        status = excluded.status,
        ccusage_version = excluded.ccusage_version,
        first_period = excluded.first_period,
        last_period = excluded.last_period,
        error_type = excluded.error_type,
        error_message = excluded.error_message,
        collector_version = excluded.collector_version
      WHERE excluded.collected_at >= source_report_states.collected_at
    `).bind(
      report.source_id, collectedAt, report.report_type, report.command, report.status,
      report.ccusage_version, report.first_period, report.last_period, report.error_type, report.error_message,
      collectorVersion,
    ),
  ];
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

export {
  aiAccountStatement,
  collectionReportStatements,
  factParams,
  factWriteStatements,
  factStatement,
  hourlyFactModelStatement,
  hourlyFactStatements,
  ingestWriteStatements,
  limitWindowStatements,
  limitWriteStatements,
  machineStatement,
  osIdentityStatement,
  sourceIdentityStatement,
  staleCurrentFactModelsStatement,
  staleFactModelStatement,
};
