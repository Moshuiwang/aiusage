/**
 * #183-b：给 breakdown 里每个模型行挂 `quota_estimate`。计算内核（`src/calibration/`）
 * 只产出系数，客户端只读展示（AGENTS.md 关键不变量）——这一层是唯一把系数变成
 * 「这个模型这段时间大约用了这个账户官方额度的百分之几」这个数字的地方。
 *
 * 缺省而不是给 null：grade=none、系数过期（`isStale`）、模型族未知、或这个族在
 * `quota_calibration` 里压根没有一行——任何一种情况都不下发这个字段，不伪造一个数字。
 */
import { FORMULA_VERSION, familyForModel, priceWeightedTokens } from "../calibration/constants";
import type { Provider } from "../calibration/constants";
import { isStale } from "../calibration/staleness";
import { B_MAX_DEVIATION } from "../calibration/backtest";
import { formatDate, parseDateOnly } from "./shared";
import type { Period } from "./shared";

const KNOWN_PROVIDERS = new Set<Provider>(["claude", "codex", "antigravity"]);

export interface QuotaCalibrationRow {
  provider: string;
  model_family: string;
  coef: number;
  grade: string;
  fitted_at: string;
  formula_version: string;
  backtest_max_err?: number | null;
  sample_intervals?: number;
}

export interface ModelTokenTotals {
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
}

export interface QuotaEstimate {
  percent: number;
  grade: string;
  basis: "week" | "weekly_average";
}

/**
 * 原因独立于额度估算。v1 曾下发 `backtest_max_error`（单日最大误差）；v2（#271）改用多天总偏差
 * 判定原因、不再计算单日最大误差，该字段随之停发——客户端把它当可选字段，缺省时提示不带数字。
 */
export interface QuotaEstimateUnavailable {
  reason: "backtest_failed" | "insufficient_data" | "stale" | "formula_changed"
    | "not_calibrated" | "unsupported_model" | "unsupported_period";
  sample_intervals?: number;
}

export function quotaEstimateUnavailableForModel(
  provider: string, modelName: string, periodId: Period, refTime: Date,
  calibrationByKey: Map<string, QuotaCalibrationRow>,
): QuotaEstimateUnavailable | undefined {
  if (periodId === "all") return { reason: "unsupported_period" };
  if (!isProvider(provider)) return { reason: "unsupported_model" };
  const family = familyForModel(provider, modelName);
  if (family === null) return { reason: "unsupported_model" };
  const row = calibrationByKey.get(`${provider}:${family}`);
  if (!row) return { reason: "not_calibrated" };
  const details: Omit<QuotaEstimateUnavailable, "reason"> = {};
  if (typeof row.sample_intervals === "number" && Number.isInteger(row.sample_intervals) && row.sample_intervals >= 0) {
    details.sample_intervals = row.sample_intervals;
  }
  if (row.formula_version !== FORMULA_VERSION) return { reason: "formula_changed", ...details };
  if (isStale(row.fitted_at, refTime)) return { reason: "stale", ...details };
  if (row.grade === "none") {
    const deviation = typeof row.backtest_max_err === "number" && Number.isFinite(row.backtest_max_err)
      ? Math.abs(row.backtest_max_err) : 0;
    const reason = deviation > B_MAX_DEVIATION ? "backtest_failed" : "insufficient_data";
    return { reason, ...details };
  }
  if (row.grade !== "A" && row.grade !== "B") return { reason: "not_calibrated", ...details };
  return undefined;
}

function isProvider(value: string): value is Provider {
  return KNOWN_PROVIDERS.has(value as Provider);
}

/** `provider:model_family` 索引，供每个模型行 O(1) 查找当天/这批系数。 */
export function indexQuotaCalibration(rows: QuotaCalibrationRow[]): Map<string, QuotaCalibrationRow> {
  const byKey = new Map<string, QuotaCalibrationRow>();
  for (const row of rows) byKey.set(`${row.provider}:${row.model_family}`, row);
  return byKey;
}

/** 周期起点到 min(周期终点, 今天) 之间的天数（含首尾两端），用于月视图的周均折算。 */
function elapsedDaysInPeriod(startDate: string, endDate: string, refTime: Date): number | null {
  const today = formatDate(refTime);
  const effectiveEnd = endDate < today ? endDate : today;
  const startMs = parseDateOnly(startDate).getTime();
  const endMs = parseDateOnly(effectiveEnd).getTime();
  if (Number.isNaN(startMs) || Number.isNaN(endMs) || endMs < startMs) return null;
  return Math.round((endMs - startMs) / 86400000) + 1;
}

/**
 * @param periodId "today"/"week" 直接给一周内的原始百分比（basis="week"）；
 *   "month" 按周均折算（basis="weekly_average"）；"all" 口径未定义，不下发。
 */
export function quotaEstimateForModel(
  provider: string,
  modelName: string,
  tokens: ModelTokenTotals,
  periodId: Period,
  startDate: string | null,
  endDate: string,
  refTime: Date,
  calibrationByKey: Map<string, QuotaCalibrationRow>,
): QuotaEstimate | undefined {
  if (quotaEstimateUnavailableForModel(provider, modelName, periodId, refTime, calibrationByKey)) return undefined;
  if (!isProvider(provider)) return undefined;
  const family = familyForModel(provider, modelName);
  if (family === null) return undefined;
  const calibration = calibrationByKey.get(`${provider}:${family}`);
  if (!calibration) return undefined;

  const rawPercent = calibration.coef * priceWeightedTokens(provider, tokens);

  if (periodId === "today" || periodId === "week") {
    return { percent: rawPercent, grade: calibration.grade, basis: "week" };
  }
  if (periodId === "month") {
    if (startDate === null) return undefined;
    const days = elapsedDaysInPeriod(startDate, endDate, refTime);
    if (days === null || days <= 0) return undefined;
    const weeks = days / 7;
    return { percent: rawPercent / weeks, grade: calibration.grade, basis: "weekly_average" };
  }
  return undefined; // "all" 周期的折算口径未定义，宁可不下发也不编造。
}
