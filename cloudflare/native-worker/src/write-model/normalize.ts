/** #126：把已校验的请求归一化成 canonical facts。 */
import { WriteValidationError, intField, isRecord, optionalFloat } from "./shared";
import { nonEmptyString, optionalString } from "./validate";
import type { AnyRecord, IngestRequest, UsageHourlyFact } from "./shared";

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

export {
  filterFactsByLedgerCoverage,
  normalizeFacts,
};
