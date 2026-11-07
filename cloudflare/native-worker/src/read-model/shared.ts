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

// ---------------------------------------------------------------------------
// #287：统计时区。部署级常量（env.AIUSAGE_TIMEZONE），请求入口与 cron 入口各调用一次
// configureReportingTimezone。同一部署所有请求写入的值相同，所以模块级状态不会在并发请求
// 之间串值；测试里切换时区后须复位（undefined = 默认北京时间）。
// 偏移按具体时刻用 Intl 计算，夏令时日自动得到 23/25 小时。
// ---------------------------------------------------------------------------
const DEFAULT_REPORTING_TIMEZONE = "Asia/Shanghai";
let reportingTimezone = DEFAULT_REPORTING_TIMEZONE;

function configureReportingTimezone(timezone: string | undefined | null): string {
  const candidate = timezone && timezone.trim() ? timezone.trim() : DEFAULT_REPORTING_TIMEZONE;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: candidate });
    reportingTimezone = candidate;
  } catch (_invalidTimezone) {
    reportingTimezone = DEFAULT_REPORTING_TIMEZONE;
  }
  return reportingTimezone;
}

function currentReportingTimezone(): string {
  return reportingTimezone;
}

type LocalParts = { year: number; month: number; day: number; hour: number; minute: number; second: number };

function localParts(date: Date): LocalParts {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: reportingTimezone, hourCycle: "h23",
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return {
    year: Number(values.year), month: Number(values.month), day: Number(values.day),
    hour: Number(values.hour) % 24, minute: Number(values.minute), second: Number(values.second),
  };
}

/** 该时刻在统计时区的 UTC 偏移（分钟）。 */
function offsetMinutesAt(date: Date): number {
  const local = localParts(date);
  const asUtc = Date.UTC(local.year, local.month - 1, local.day, local.hour, local.minute, local.second);
  return Math.round((asUtc - Math.floor(date.getTime() / 1000) * 1000) / 60000);
}

function offsetSuffix(minutes: number): string {
  const sign = minutes < 0 ? "-" : "+";
  const absolute = Math.abs(minutes);
  return `${sign}${String(Math.floor(absolute / 60)).padStart(2, "0")}:${String(absolute % 60).padStart(2, "0")}`;
}

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

/** 纯日历运算：YYYY-MM-DD 加减天数，与时区和夏令时无关。 */
function shiftDate(value: string, days: number): string {
  const [year, month, day] = value.split("-").map(Number);
  const shifted = new Date(Date.UTC(year, month - 1, day + days));
  return `${shifted.getUTCFullYear()}-${pad2(shifted.getUTCMonth() + 1)}-${pad2(shifted.getUTCDate())}`;
}

function periodWindowBounds(startDate: string | null, endDate: string): [string | null, string] {
  return [
    startDate === null ? null : toOffsetIso(parseDateOnly(startDate)),
    toOffsetIso(parseDateOnly(shiftDate(endDate, 1))),
  ];
}

function localDateFromWindowStart(value: unknown): string | null {
  const parsed = parseDate(str(value));
  return parsed ? formatDate(parsed) : null;
}

function localHourFromWindowStart(value: unknown): string | null {
  const parsed = parseDate(str(value));
  if (!parsed) return null;
  const local = toOffsetIso(parsed);
  return `${local.slice(0, 13)}:00:00${local.slice(19)}`;
}

function hasTimezoneDesignator(value: unknown): boolean {
  return /(?:Z|[+-]\d{2}:?\d{2})$/.test(str(value).trim());
}

// #287：周期边界与日期轴全部是 YYYY-MM-DD 的纯日历运算，不经过「某时刻 + N×86400000 毫秒 → 本地日期」，
// 否则夏令时日（23/25 小时）与 ≥ +13 的时区会错一天。
function periodBounds(date: string, period: string, offset?: number): [Period, string | null, string] {
  const periodId: Period = ["today", "week", "month", "all"].includes(period) ? period as Period : "today";
  if (offset !== undefined) {
    // Offset navigation selects calendar periods. Existing date-only requests
    // continue to describe their established rolling reporting windows.
    if (periodId === "today") {
      const day = shiftDate(date, offset);
      return [periodId, day, day];
    }
    if (periodId === "week") {
      const [year, month, day] = date.split("-").map(Number);
      const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
      const start = shiftDate(date, -((weekday + 6) % 7) + offset * 7);
      return [periodId, start, offset === 0 ? date : shiftDate(start, 6)];
    }
    const [year, month] = date.split("-").map(Number);
    const first = new Date(Date.UTC(year, month - 1 + offset, 1));
    const start = `${first.getUTCFullYear()}-${pad2(first.getUTCMonth() + 1)}-01`;
    const last = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0));
    const end = `${last.getUTCFullYear()}-${pad2(last.getUTCMonth() + 1)}-${pad2(last.getUTCDate())}`;
    return [periodId, start, offset === 0 ? date : end];
  }
  if (periodId === "today") return [periodId, date, date];
  if (periodId === "week") return [periodId, shiftDate(date, -6), date];
  if (periodId === "month") return [periodId, shiftDate(date, -29), date];
  return [periodId, null, date];
}

function dateAxis(startDate: string | null, endDate: string, rows: DailyRow[]): string[] {
  if (startDate === null) return Array.from(new Set(rows.map((row) => row.date))).sort();
  const result: string[] = [];
  for (let current = startDate; current <= endDate; current = shiftDate(current, 1)) {
    result.push(current);
  }
  return result;
}

/** 统计时区里这一天的每个整点（夏令时日 23 或 25 个）。 */
function hourAxis(date: string): string[] {
  const end = parseDateOnly(shiftDate(date, 1)).getTime();
  const result: string[] = [];
  for (let time = parseDateOnly(date).getTime(); time < end; time += 3600000) {
    result.push(toOffsetIso(new Date(time)));
  }
  return result;
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
  const localDate = formatDate(windowStart);
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
  const local = localParts(date);
  return `${local.year}-${pad2(local.month)}-${pad2(local.day)}T${pad2(local.hour)}:${pad2(local.minute)}:${pad2(local.second)}`
    + offsetSuffix(offsetMinutesAt(date));
}

function formatDateInZone(date: Date): string {
  const local = localParts(date);
  return `${local.year}-${pad2(local.month)}-${pad2(local.day)}`;
}

/** 统计时区里这一天 00:00 的时刻。偏移取「当天午夜附近」的值，两次迭代覆盖夏令时切换。 */
function parseDateOnly(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  const naiveUtc = Date.UTC(year, month - 1, day);
  let instant = naiveUtc - offsetMinutesAt(new Date(naiveUtc)) * 60000;
  instant = naiveUtc - offsetMinutesAt(new Date(instant)) * 60000;
  return new Date(instant);
}

function parseDate(value: string): Date | null {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function addHours(value: string, hours: number): string {
  const parsed = parseDate(value);
  return parsed ? toOffsetIso(new Date(parsed.getTime() + hours * 3600000)) : value;
}

function formatDate(date: Date): string {
  return formatDateInZone(date);
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
  addHours,
  aggregateAgentNames,
  asArray,
  dateAxis,
  emptyTokenTotals,
  formatDate,
  configureReportingTimezone,
  currentReportingTimezone,
  formatDateInZone,
  offsetMinutesAt,
  shiftDate,
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
  //: #287：按账户分格的额度与用量（菜单栏 / iPhone 的主数据）。
  account_slots: Record<string, unknown>[];
  account_usage_coverage: Record<string, { unattributed_tokens: number }>;
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
