/** #183-a：计算内核的输入/输出类型。纯数据形状，不含逻辑。 */
import type { Provider } from "./constants";

/** 一条官方额度读数（来自 `limit_window_history`，`window` 已按 session/week 等筛好后传入）。 */
export interface LimitObservation {
  source_id: string;
  provider: Provider;
  observed_at: string; // ISO 8601
  reset_at: string; // ISO 8601
  used_percent: number; // 0-100
  window_duration_minutes: number;
}

/**
 * 「小时 × 模型族 × token 类型」聚合事实行。这是 SQL 预聚合（生产）或导出脚本（fixture）
 * 产出的输入形状——模型名到族的映射已经做完，calibration 内核不再看原始模型名。
 * `model_family` 为 null 表示这一行来自未知模型（映射失败或缺模型行），调用方按整段丢弃
 * 处理，不参与任何族的系数拟合。
 */
export interface HourlyFamilyFact {
  provider: Provider;
  model_family: string | null;
  window_start: string; // ISO 8601
  window_end: string; // ISO 8601
  input_tokens: number;
  output_tokens: number;
  cache_creation_tokens: number;
  cache_read_tokens: number;
}

/** 一个由两条相邻官方读数合并出的区间：额度从 u0 涨到 u1，分摊到的各族价格加权 token 量。 */
export interface Interval {
  sourceId: string;
  cycleIndex: number;
  t0: string;
  t1: string;
  u0: number;
  u1: number;
  deltaU: number;
  /** 每个族的价格加权 token 量（按区间与小时事实重叠比例分摊后累加）。 */
  familyPricedTokens: Record<string, number>;
}

export type Grade = "A" | "B" | "none";

export interface CalibrationResult {
  provider: Provider;
  model_family: string;
  coef: number;
  effective_delta_u: number;
  backtest_max_err: number | null;
  grade: Grade;
  sample_intervals: number;
  formula_version: string;
}

/** `calibrate()` 的整体返回：每族一条系数结果，外加数据完整性剔除统计。 */
export interface CalibrationOutput {
  results: CalibrationResult[];
  /** 因 unattributed（缺 model 行）占比过高被整段剔除的区间数，不参与拟合与回测。 */
  unattributedDroppedIntervals: number;
}

export interface CalibrateOptions {
  /** 计算时刻，用于近期加权与突变检测的窗口边界；测试里固定传入，生产传 Date.now()。 */
  now: Date;
  /** 训练窗口天数，默认 28。 */
  windowDays?: number;
  /** 近期加权半衰期天数，默认 7。 */
  halfLifeDays?: number;
}
