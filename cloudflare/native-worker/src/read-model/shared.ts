/** #126：read-model 内部共享的类型、常量与纯工具。叶子模块，不 import 兄弟模块。 */

export type Period = "today" | "week" | "month" | "all";

export interface SummaryRequest {
  date: string;
  period: string;
  timezone: string;
  machine?: string | null;
  account?: string | null;
  currentTime?: string | null;
  backendMode?: string | null;
  offset?: number;
}

type DailyRow = {
  source_id: string;
  date: string;
  agent: string;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  total_tokens: number;
  total_cost: number | null;
  metadata_json: string | null;
};

type ModelRow = {
  source_id: string;
  date: string;
  agent: string;
  model_name: string;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  total_tokens: number;
  cost: number | null;
};

type TimedRow = {
  source_id: string;
  hour?: string;
  start_time?: string;
  end_time?: string;
  agent: string;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  total_tokens: number;
  total_cost: number | null;
  metadata_json: string | null;
};

type SourceIdentity = {
  host?: string | null;
  machine?: string | null;
  os_user?: string | null;
  platform?: string | null;
};

type LimitRow = {
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
  official: boolean;
};

const localEstimateSourceTypes = new Set([
  "active_limits_cache",
  "local_history_estimate",
  "ccusage_daily",
  "ccusage_blocks",
  "session_log_estimate",
]);

// Issue #61：客户端固定展示的 provider 槽位。用量与额度分别是两个独立字段，
// 任一缺失都不影响另一个；缺失的额度只暴露「最近一次验证时间」，绝不暴露历史百分比或过期 reset。
// 与 src/ai_usage_widget/verify_cloud.py 的 SLOT_PROVIDERS 保持逐字一致。
const slotProviders = ["claude", "codex", "antigravity"] as const;

// pusher 真实会写出来的「跨 agent 聚合」与「来源不明」两个 agent 名，不代表任何 provider。
const aggregateAgentNames = new Set(["", "all", "unknown"]);

const limitStaleAfterMs = 120 * 60 * 1000;

type ProviderUsageTotals = {
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cache_tokens: number;
};

function periodWindowBounds(startDate: string | null, endDate: string): [string | null, string] {
  return [
    startDate === null ? null : `${startDate}T00:00:00+08:00`,
    `${formatDate(addDays(parseDateOnly(endDate), 1))}T00:00:00+08:00`,
  ];
}

function localDateFromWindowStart(value: unknown): string | null {
  const parsed = parseDate(str(value));
  return parsed ? formatDateInShanghai(parsed) : null;
}

function localHourFromWindowStart(value: unknown): string | null {
  const parsed = parseDate(str(value));
  if (!parsed) return null;
  const local = toOffsetIso(parsed);
  return `${local.slice(0, 13)}:00:00+08:00`;
}

function hasTimezoneDesignator(value: unknown): boolean {
  return /(?:Z|[+-]\d{2}:?\d{2})$/.test(str(value).trim());
}

function periodBounds(date: string, period: string, offset?: number): [Period, string | null, string] {
  const periodId: Period = ["today", "week", "month", "all"].includes(period) ? period as Period : "today";
  if (offset !== undefined) {
    // Offset navigation selects calendar periods. Existing date-only requests
    // continue to describe their established rolling reporting windows.
    const anchor = new Date(`${date}T12:00:00Z`);
    let start: Date;
    let end: Date;
    if (periodId === "today") {
      start = end = addDays(anchor, offset);
    } else if (periodId === "week") {
      start = addDays(anchor, -((anchor.getUTCDay() + 6) % 7) + offset * 7);
      end = offset === 0 ? anchor : addDays(start, 6);
    } else {
      start = new Date(Date.UTC(anchor.getUTCFullYear(), anchor.getUTCMonth() + offset, 1, 12));
      end = offset === 0 ? anchor : new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 0, 12));
    }
    return [periodId, formatDate(start), formatDate(end)];
  }
  const end = parseDateOnly(date);
  if (periodId === "today") return [periodId, date, date];
  if (periodId === "week") return [periodId, formatDate(addDays(end, -6)), date];
  if (periodId === "month") return [periodId, formatDate(addDays(end, -29)), date];
  return [periodId, null, date];
}

function dateAxis(startDate: string | null, endDate: string, rows: DailyRow[]): string[] {
  if (startDate === null) return Array.from(new Set(rows.map((row) => row.date))).sort();
  const result: string[] = [];
  let current = parseDateOnly(startDate);
  const end = parseDateOnly(endDate);
  while (current <= end) {
    result.push(formatDate(current));
    current = addDays(current, 1);
  }
  return result;
}

function hourAxis(date: string): string[] {
  return Array.from({ length: 24 }, (_, index) => `${date}T${String(index).padStart(2, "0")}:00:00+08:00`);
}

function identityMatchesFilter(identity: SourceIdentity | undefined, machineFilter?: string | null, accountFilter?: string | null): boolean {
  const machine = str(identity?.machine ?? identity?.host ?? "");
  const account = str(identity?.os_user ?? "");
  if (machineFilter && machine !== machineFilter) return false;
  if (accountFilter && account !== accountFilter) return false;
  return true;
}

function accountHourlyRowInPeriod(row: Record<string, unknown>, startDate: string | null, endDate: string, _timezone: string): boolean {
  const windowStart = parseDate(str(row.window_start));
  if (!windowStart) return false;
  const localDate = formatDateInShanghai(windowStart);
  if (localDate > endDate) return false;
  if (startDate === null) return true;
  return localDate >= startDate;
}

function accountHourlyRowMatchesFilter(row: Record<string, unknown>, machineFilter?: string | null, accountFilter?: string | null): boolean {
  const machineName = str(row.machine_name ?? row.machine_id ?? "");
  const machineId = str(row.machine_id ?? "");
  const osUser = str(row.os_user ?? "");
  if (machineFilter && !new Set([machineId, machineName]).has(machineFilter)) return false;
  if (accountFilter && osUser !== accountFilter) return false;
  return true;
}

function metadataFromStr(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return isRecord(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function sumTokenType(trend: Record<string, unknown>, tokenType: string): number {
  for (const row of asArray<Record<string, unknown>>(trend.by_token_type)) {
    if (row.type === tokenType) return asArray<number>(row.values).reduce((sum, value) => sum + int(value), 0);
  }
  return 0;
}

function emptyTokenTotals(): Record<string, number> {
  return { input: 0, output: 0, cache: 0, total: 0 };
}

function isCodexAgent(agent: unknown): boolean {
  const raw = str(agent).toLowerCase();
  return raw.includes("codex") || raw.includes("gpt") || raw.includes("openai");
}

function itemKey(sourceId: string, date: string, agent: string): string {
  return `${sourceId}\u0000${date}\u0000${agent}`;
}

function nowInTimezone(_timezone: string, currentTime?: string | null): Date {
  if (currentTime) {
    const parsed = new Date(currentTime);
    if (!Number.isNaN(parsed.getTime())) return parsed;
  }
  return new Date();
}

function toOffsetIso(date: Date): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const hour = String(Number(values.hour ?? "0") % 24).padStart(2, "0");
  return `${formatDateInShanghai(date)}T${hour}:${values.minute ?? "00"}:${values.second ?? "00"}+08:00`;
}

function formatDateInShanghai(date: Date): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function parseDateOnly(value: string): Date {
  return new Date(`${value}T00:00:00+08:00`);
}

function parseDate(value: string): Date | null {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function addDays(date: Date, days: number): Date {
  return new Date(date.getTime() + days * 86400000);
}

function addHours(value: string, hours: number): string {
  const parsed = parseDate(value);
  return parsed ? toOffsetIso(new Date(parsed.getTime() + hours * 3600000)) : value;
}

function formatDate(date: Date): string {
  return formatDateInShanghai(date);
}

function int(value: unknown): number {
  if (typeof value === "boolean") return 0;
  if (typeof value === "number") return Math.round(value);
  return 0;
}

function str(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

function asArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export {
  accountHourlyRowInPeriod,
  accountHourlyRowMatchesFilter,
  addDays,
  addHours,
  aggregateAgentNames,
  asArray,
  dateAxis,
  emptyTokenTotals,
  formatDate,
  formatDateInShanghai,
  hasTimezoneDesignator,
  hourAxis,
  identityMatchesFilter,
  int,
  isCodexAgent,
  isRecord,
  itemKey,
  limitStaleAfterMs,
  localDateFromWindowStart,
  localEstimateSourceTypes,
  localHourFromWindowStart,
  metadataFromStr,
  nowInTimezone,
  parseDate,
  parseDateOnly,
  periodBounds,
  periodWindowBounds,
  slotProviders,
  str,
  sumTokenType,
  toOffsetIso,
};
/**
 * #130：/api/summary 快照的顶层结构——「read-model 输出 ↔ mobile-summary 输入」的内部合同。
 * 渐进类型化：顶层键全量声明（改名/删键在编译期被抓），深层值先保持宽类型由消费方 coerce。
 * 用 type 而非 interface：对象字面量类型带隐式索引签名，可无摩擦传给既有的
 * `Record<string, unknown>` 工具函数。
 */
type SummaryPeriodBlock = {
  date: string;
  period: Period;
  start_date: string | null;
  end_date: string;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
  machine?: string;
  account?: string;
};

type SummarySnapshot = {
  schema_version: number;
  generated_at: string;
  timezone: string;
  summary: SummaryPeriodBlock;
  groups: {
    by_machine: Record<string, unknown>[];
    by_account: { name: string; total_tokens: number }[];
    by_agent: { name: string; total_tokens: number }[];
  };
  items: Record<string, unknown>[];
  trend: Record<string, unknown>;
  source_status: Record<string, unknown>[];
  version_health: Record<string, unknown>;
  limits: LimitRow[];
  limit_status: Record<string, unknown>[];
  provider_slots: Record<string, unknown>[];
  provider_usage_coverage: Record<string, unknown>;
  account_hourly: Record<string, unknown>;
  ai_accounts: Record<string, unknown>[];
  metadata: Record<string, unknown>;
};

export type {
  DailyRow,
  LimitRow,
  ModelRow,
  ProviderUsageTotals,
  SourceIdentity,
  SummaryPeriodBlock,
  SummarySnapshot,
  TimedRow,
};
