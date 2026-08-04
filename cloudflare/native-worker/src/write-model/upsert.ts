/** #126：读-比-写的幂等 upsert 与模型行同步。 */
import { factParams, hourlyFactModelStatement, staleCurrentFactModelsStatement, staleFactModelStatement } from "./statements";
import { isRecord, newerOrSameIso, rowMatches, sameValue, stableStringify } from "./shared";
import type { AnyRecord, SourceReportState, UsageHourlyFact } from "./shared";

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

async function latestSourceReportState(db: D1Database, report: AnyRecord): Promise<SourceReportState> {
  const existing = await db.prepare(`
    SELECT source_id, report_type, command, status, ccusage_version, first_period, last_period, error_type, error_message,
           collector_version
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

export {
  factCompare,
  insertFact,
  latestSourceReportState,
  sourceHasNewerReport,
  syncHourlyFactModels,
  updateFact,
  upsertAiAccount,
  upsertHourlyFact,
  upsertIfChanged,
  upsertMachine,
  upsertOsIdentity,
};
