/**
 * #183-a：周期切分与重置识别。
 *
 * 同一来源（source_id + provider + window）的官方读数按时间排序后，`reset_at` 相对上一条
 * 变化超过 2 分钟时切出新周期。
 *
 * `reset_at` 不变而 `used_percent` 下降是上游纠正（#206：Codex 2026-09-30 本地 0 token 时
 * 22→43，数小时后同一 `reset_at` 下纠正回 24），不是重置——生产全部历史里这类下降没有一次
 * 是真实重置，真实重置都会把 `reset_at` 推后一个窗口。此时回溯丢弃本周期内高于纠正值的
 * 读数（被撤销的计费），不切周期；否则被撤销的涨幅会作为一段「没有 token 却涨了额度」的
 * 区间留在训练集里。
 *
 * 但 `used_percent == 0` 时 `reset_at` 本身会每隔一段时间滚动（观察到 Codex 在 used=0 时
 * 每 30 分钟滚动一次 reset_at，不代表真的发生了重置）——这类「全零 + 读数条数很少」的段落
 * 要整体丢弃，不当成一个独立周期参与拟合，否则会在没有任何真实用量变化的窗口里硬造出
 * 一堆 ΔU=0 的区间，稀释真实信号。
 */
import type { LimitObservation } from "./types";

const RESET_AT_DRIFT_TOLERANCE_MS = 2 * 60 * 1000;
/** 全零段落的读数条数阈值：不超过这个条数就当滚动噪音丢弃，不当成周期。 */
const ROLLING_ZERO_SEGMENT_MAX_READINGS = 8;

export interface Cycle {
  index: number;
  readings: LimitObservation[];
}

/** 按 `source_id` 分组、时间排序，切出周期，丢弃 used=0 的滚动噪音段。 */
export function splitCycles(observations: LimitObservation[]): Cycle[] {
  const sorted = [...observations].sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at));
  const rawSegments: LimitObservation[][] = [];
  let current: LimitObservation[] = [];
  for (const reading of sorted) {
    if (current.length > 0) {
      const prev = current[current.length - 1];
      const resetDriftMs = Math.abs(Date.parse(reading.reset_at) - Date.parse(prev.reset_at));
      if (resetDriftMs > RESET_AT_DRIFT_TOLERANCE_MS) {
        rawSegments.push(current);
        current = [];
      } else {
        // 上游纠正：周期内读数单调不减，高于纠正值的只会在末尾。
        while (current.length > 0 && current[current.length - 1].used_percent > reading.used_percent + 0.01) current.pop();
      }
    }
    current.push(reading);
  }
  if (current.length > 0) rawSegments.push(current);

  const cycles: Cycle[] = [];
  for (const segment of rawSegments) {
    const allZero = segment.every((r) => r.used_percent === 0);
    if (allZero && segment.length <= ROLLING_ZERO_SEGMENT_MAX_READINGS) continue; // 滚动噪音，整段丢弃
    cycles.push({ index: cycles.length, readings: segment });
  }
  return cycles;
}

/**
 * 给每个新周期（第一个周期之外）在 `reset_at − window_duration_minutes` 处补一个 used=0 的
 * 锚点，前提是这个锚点确实早于该周期第一条真实读数、且离上一个周期结束不太远（<30 小时，
 * 避免在长时间没有采集的空档里凭空造出一大段假设的零点区间）。
 */
export function withResetAnchors(cycles: Cycle[]): Cycle[] {
  return cycles.map((cycle, i) => {
    if (i === 0 || cycle.readings.length === 0) return cycle;
    const first = cycle.readings[0];
    const anchorTime = Date.parse(first.reset_at) - first.window_duration_minutes * 60 * 1000;
    const firstReadingTime = Date.parse(first.observed_at);
    const prevCycle = cycles[i - 1];
    const prevLastTime = Date.parse(prevCycle.readings[prevCycle.readings.length - 1].observed_at);
    const withinGap = anchorTime < firstReadingTime && firstReadingTime - anchorTime < 30 * 60 * 60 * 1000;
    const afterPrevCycle = anchorTime >= prevLastTime - 60 * 1000;
    if (!withinGap || !afterPrevCycle) return cycle;
    const anchor: LimitObservation = {
      ...first,
      observed_at: new Date(anchorTime).toISOString(),
      used_percent: 0,
    };
    return { ...cycle, readings: [anchor, ...cycle.readings] };
  });
}
