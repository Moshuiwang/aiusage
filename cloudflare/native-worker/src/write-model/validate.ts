/** #126：payload 校验与敏感字段边界（版本块 wire 归一化在这里）。 */
import { COLLECTOR_RELEASE_FIELD, VersionContractError, normalizeCollectorRelease } from "../version-contract";
import { WriteValidationError, intField, isRecord, optionalFloat } from "./shared";
import type { AnyRecord, IngestRequest, LimitWindow } from "./shared";

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
  for (const key of ["ccusage_daily_report", "ccusage_session_report", "mswusage_codex_hourly_report", "codex_hourly_status"]) {
    if (payload[key] !== undefined && !isRecord(payload[key])) {
      throw new WriteValidationError(400, "http_schema_invalid", `${key} must be an object`);
    }
  }
  // 采集端版本块：缺整块只降级为 null，不抛错；出现不合法值才明确拒绝。
  // 错误信息只带字段名，不回显值，避免疑似凭据进入日志或错误响应。
  let collectorRelease: AnyRecord | null;
  try {
    collectorRelease = normalizeCollectorRelease(payload[COLLECTOR_RELEASE_FIELD]);
  } catch (exc) {
    if (exc instanceof VersionContractError) {
      throw new WriteValidationError(400, "http_schema_invalid", exc.message);
    }
    throw exc;
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
    mswusage_codex_hourly_report: isRecord(payload.mswusage_codex_hourly_report) ? payload.mswusage_codex_hourly_report : undefined,
    codex_hourly_status: isRecord(payload.codex_hourly_status) ? payload.codex_hourly_status : undefined,
    usage_hourly_facts: Array.isArray(usageHourlyFacts) ? usageHourlyFacts.filter(isRecord) : undefined,
    usage_ledger_runs: Array.isArray(usageLedgerRuns) ? usageLedgerRuns.filter(isRecord) : undefined,
    collector_release: collectorRelease,
    collection_status: String(payload.collection_status || "ok"),
    error_type: payload.error_type ? String(payload.error_type) : null,
    error_message: payload.error_message ? String(payload.error_message) : null,
  };
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

export {
  nonEmptyString,
  optionalString,
  parseLimitWindow,
  percent,
  positiveInt,
  rejectSensitiveLimitKeys,
  requireIsoString,
  scanIngestSensitive,
  validateIngestPayload,
  validateLimitsPayload,
};
