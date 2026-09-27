/**
 * #183-a：`fitted_at` 过期判断。
 *
 * 计算内核本身不写库、不知道「现在」是不是很久没跑过一次每日 cron——但下游（#183-b 接线、
 * summary 下发）需要一个纯函数来判断某一批已经落库的系数是不是太旧了。约定：`fitted_at`
 * 距 `now` 超过 3 天就算过期，过期时该账户所有族一律降级成「—」（不下发数值），不能让
 * 一次 cron 失败后台面上悄悄展示一份越来越不准的旧系数。
 */

const DEFAULT_STALE_AFTER_DAYS = 3;

export function isStale(fittedAt: string, now: Date, staleAfterDays: number = DEFAULT_STALE_AFTER_DAYS): boolean {
  const ageMs = now.getTime() - Date.parse(fittedAt);
  return ageMs > staleAfterDays * 24 * 60 * 60 * 1000;
}
