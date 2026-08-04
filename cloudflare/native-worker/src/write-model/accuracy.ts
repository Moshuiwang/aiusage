/** #126：账本对账（accuracy）计划与写入。 */
import { upsertIfChanged } from "./upsert";
import { intField, isRecord, optionalFloat, stableStringify } from "./shared";
import type { AccuracyPlan, AnyRecord, IngestRequest, UsageHourlyFact } from "./shared";

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

export {
  accuracyWriteStatements,
  buildAccuracyPlans,
  factsDigestForRun,
};
