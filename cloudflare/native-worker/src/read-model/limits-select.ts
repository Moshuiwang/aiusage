/** #126：额度窗口的甄选、排序与状态判定。 */
import { hasTimezoneDesignator, limitStaleAfterMs, parseDate, str } from "./shared";
import type { LimitRow } from "./shared";

function bestLimitWindows(limits: LimitRow[]): LimitRow[] {
  const best = new Map<string, LimitRow>();
  for (const limit of limits) {
    const key = `${limit.source_id || limit.provider}:${limit.provider}:${limit.window}`;
    const existing = best.get(key);
    if (!existing || compareLimitRank(limit, existing) > 0) best.set(key, limit);
  }
  return Array.from(best.values()).sort((lhs, rhs) =>
    `${lhs.source_id}:${lhs.provider}:${lhs.window}`.localeCompare(`${rhs.source_id}:${rhs.provider}:${rhs.window}`),
  );
}

function withoutSupersededActiveCache(limits: LimitRow[]): LimitRow[] {
  const effectiveKeys = new Set(
    limits
      .filter((limit) => effectiveLimitWindow(limit))
      .map((limit) => `${limit.provider}:${limit.window}`),
  );
  return limits.filter((limit) =>
    limit.source_type !== "active_limits_cache" || !effectiveKeys.has(`${limit.provider}:${limit.window}`),
  );
}

function effectiveLimitWindow(limit: LimitRow): boolean {
  return limit.official === true &&
    limit.confidence === "observed" &&
    limit.status === "ok" &&
    limit.source_type !== "active_limits_cache";
}

function compareLimitRank(lhs: LimitRow, rhs: LimitRow): number {
  const left = limitRank(lhs);
  const right = limitRank(rhs);
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] === right[index]) continue;
    return left[index] > right[index] ? 1 : -1;
  }
  return 0;
}

function limitRank(limit: LimitRow): (number | string)[] {
  const officialOk = limit.official && limit.confidence === "observed" && limit.status === "ok" ? 1 : 0;
  return [officialOk, limitSourceQuality(limit.source_type), limit.observed_at || ""];
}

function limitSourceQuality(sourceType: string): number {
  const quality: Record<string, number> = {
    oauth_usage_api: 5,
    runtime_api: 5,
    official_cli: 4,
    official_cli_limit_message: 3,
    official_cli_subscription: 2,
    active_limits_cache: 1,
  };
  return quality[sourceType] ?? 0;
}

function limitWindowExpired(limit: LimitRow, refTime: Date): boolean {
  const reset = parseDate(limit.reset_at);
  if (!reset) return false;
  // 没有时区标记就判断不了是否已 reset，按已过期处理（fail closed）。
  // 与 observedStale 同一套策略，也与 Python 侧一致。
  if (!hasTimezoneDesignator(limit.reset_at)) return true;
  return reset.getTime() <= refTime.getTime();
}

// 最近一次**成功的官方核对**时间。本地估算、失败的探测（provider_failed）、
// confidence != observed 的观测都不算核对，否则展示层会把「刚刚算过 / 刚刚失败过」
// 读成「官方额度刚刚核对过」。已选定来源时只看该来源，保证
// (source_id, source_type, last_verified_at) 指向同一条记录。与 Python 侧一致。
function lastVerifiedAtOf(rows: LimitRow[], sourceId?: unknown): string | null {
  let best: string | null = null;
  let bestTime = Number.NEGATIVE_INFINITY;
  for (const row of rows) {
    if (!row.observed_at) continue;
    if (!effectiveLimitWindow(row)) continue;
    if (sourceId !== undefined && str(row.source_id) !== str(sourceId)) continue;
    const time = parseDate(row.observed_at)?.getTime() ?? Number.NEGATIVE_INFINITY;
    if (time > bestTime) {
      bestTime = time;
      best = String(row.observed_at);
    }
  }
  return best;
}

function limitWindowStale(limit: LimitRow, refTime: Date): boolean {
  return observedStale(limit.observed_at, refTime);
}

// 观测时间超过阈值就是陈旧。没有时区标记时无法判断年龄，按陈旧处理（fail closed），
// 不让年龄不明的记录冒充当前官方额度。Python 侧 _observed_stale 同一套策略。
function observedStale(observedAt: unknown, refTime: Date): boolean {
  if (!hasTimezoneDesignator(observedAt)) return true;
  const observed = parseDate(str(observedAt));
  if (!observed) return true;
  return refTime.getTime() - observed.getTime() > limitStaleAfterMs;
}

function buildLimitStatus(limits: LimitRow[], refTime: Date): Record<string, unknown>[] {
  const bySource = new Map<string, LimitRow[]>();
  for (const limit of limits) {
    const key = `${limit.provider.toLowerCase()}\u0000${limit.source_id}`;
    bySource.set(key, [...(bySource.get(key) ?? []), limit]);
  }
  const selected = new Map<string, { newest: number; source: string; rows: LimitRow[] }>();
  for (const [key, rows] of bySource) {
    if (!rows.some((row) => effectiveLimitWindow(row) || row.status === "provider_failed")) continue;
    const [provider, source] = key.split("\u0000");
    const newest = Math.max(...rows.map((row) => parseDate(row.observed_at)?.getTime() ?? Number.NEGATIVE_INFINITY));
    const existing = selected.get(provider);
    if (!existing || newest > existing.newest || (newest === existing.newest && source > existing.source)) {
      selected.set(provider, { newest, source, rows });
    }
  }
  return [...selected.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([provider, value]) => {
    const successful = value.rows.filter(effectiveLimitWindow);
    const failures = value.rows.filter((row) => row.status === "provider_failed");
    const trustedRows = successful.length ? successful : failures;
    const freshest = [...trustedRows].sort((left, right) => {
      const time = (parseDate(right.observed_at)?.getTime() ?? Number.NEGATIVE_INFINITY)
        - (parseDate(left.observed_at)?.getTime() ?? Number.NEGATIVE_INFINITY);
      return time || right.source_type.localeCompare(left.source_type);
    })[0];
    const latestSuccess = Math.max(...successful.map((row) => parseDate(row.observed_at)?.getTime() ?? Number.NEGATIVE_INFINITY), Number.NEGATIVE_INFINITY);
    const latestFailure = Math.max(...failures.map((row) => parseDate(row.observed_at)?.getTime() ?? Number.NEGATIVE_INFINITY), Number.NEGATIVE_INFINITY);
    const stale = observedStale(freshest.observed_at, refTime);
    const unexpired = successful.some((row) => !limitWindowExpired(row, refTime));
    return {
      provider,
      source_id: value.source,
      observed_at: freshest.observed_at,
      source_type: freshest.source_type,
      status: latestFailure > latestSuccess ? "unavailable" : (stale ? "stale" : (unexpired ? "ok" : "expired")),
    };
  });
}

export {
  bestLimitWindows,
  buildLimitStatus,
  compareLimitRank,
  effectiveLimitWindow,
  lastVerifiedAtOf,
  limitRank,
  limitSourceQuality,
  limitWindowExpired,
  limitWindowStale,
  observedStale,
  withoutSupersededActiveCache,
};
