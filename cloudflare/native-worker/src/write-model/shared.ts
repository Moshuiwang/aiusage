/** #126：write-model 内部共享的类型、错误类与纯工具。叶子模块。 */
import type { Env } from "../index";

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
  // `ccusage_blocks_report` 已由 #91 从采集端摘除（#78 摘的是 `ccusage_daily_status`）。
  // 老版本采集端仍会发这两个字段，一律当未知顶层字段忽略：不声明、不校验、不解析、不落库。
  mswusage_codex_hourly_report?: AnyRecord;
  codex_hourly_status?: AnyRecord;
  usage_hourly_facts?: AnyRecord[];
  usage_ledger_runs?: AnyRecord[];
  collector_release: AnyRecord | null;
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

function acceptedAtFromEnv(env: Env): string {
  return env.AIUSAGE_NOW || new Date().toISOString();
}

function intField(row: AnyRecord, name: string): number {
  return row[name] === undefined || row[name] === null ? 0 : Number(row[name]);
}

function optionalFloat(row: AnyRecord, name: string): number | null {
  return row[name] === undefined || row[name] === null ? null : Number(row[name]);
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

export {
  acceptedAtFromEnv,
  intField,
  isRecord,
  newerOrSameIso,
  optionalFloat,
  rowMatches,
  sameValue,
  stableStringify,
};
export type {
  AccuracyPlan,
  AnyRecord,
  IngestRequest,
  LimitWindow,
  SourceReportState,
  UsageHourlyFact,
};
