/**
 * #183-b：给 breakdown 里每个模型行挂 `quota_estimate`。计算内核（`src/calibration/`）
 * 只产出系数，客户端只读展示（AGENTS.md 关键不变量）——这一层是唯一把系数变成
 * 「这个模型这段时间大约用了这个账户官方额度的百分之几」这个数字的地方。
 *
 * 缺省而不是给 null：grade=none、系数过期（`isStale`）、模型族未知、或这个族在
 * `quota_calibration` 里压根没有一行——任何一种情况都不下发这个字段，不伪造一个数字。
 */
import { familyForModel, priceWeightedTokens } from "../calibration/constants";
import type { Provider } from "../calibration/constants";
import { isStale } from "../calibration/staleness";
import { formatDate, parseDateOnly } from "./shared";
import type { Period } from "./shared";

const KNOWN_PROVIDERS = new Set<Provider>(["claude", "codex", "antigravity"]);

export interface QuotaCalibrationRow {
  provider: string;
  model_family: string;
  coef: number;
  grade: string;
  fitted_at: string;
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
  if (!isProvider(provider)) return undefined;
  const family = familyForModel(provider, modelName);
  if (family === null) return undefined;
  const calibration = calibrationByKey.get(`${provider}:${family}`);
  if (!calibration) return undefined;
  if (calibration.grade === "none") return undefined;
  if (isStale(calibration.fitted_at, refTime)) return undefined;

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
