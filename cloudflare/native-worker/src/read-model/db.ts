/** #126：D1 数据访问与行整形（SQL 只出现在这里）。 */
import { bestLimitWindows, limitWindowExpired, withoutSupersededActiveCache } from "./limits-select";
import {
  accountHourlyRowInPeriod, accountHourlyRowMatchesFilter, addDays, formatDate, int, itemKey,
  localDateFromWindowStart, localEstimateSourceTypes, parseDateOnly, periodWindowBounds, str,
} from "./shared";
import type { LimitRow, ModelRow, SourceIdentity } from "./shared";
import type { QuotaCalibrationRow } from "./quota-estimate";

async function all<T>(db: D1Database, sql: string, params: unknown[] = []): Promise<T[]> {
  const result = await db.prepare(sql).bind(...params).all<T>();
  return result.results ?? [];
}

async function fetchSourceIdentities(db: D1Database): Promise<Record<string, SourceIdentity>> {
  const rows = await all<Record<string, string | null>>(
    db,
    `
      SELECT source_id, host, machine, os_user, platform, last_seen_at
      FROM source_identities
      ORDER BY last_seen_at DESC
    `,
  );
  const result: Record<string, SourceIdentity> = {};
  for (const row of rows) {
    const sourceId = str(row.source_id);
    if (sourceId in result) continue;
    result[sourceId] = {
      host: row.host,
      machine: row.machine ?? row.host,
      os_user: row.os_user,
      platform: row.platform,
    };
  }
  return result;
}

async function fetchLimitWindows(db: D1Database, refTime: Date | null): Promise<LimitRow[]> {
  const rows = await all<Omit<LimitRow, "official">>(
    db,
    `
      SELECT source_id, provider, window, used_percent, remaining_percent, reset_at,
             window_duration_minutes, observed_at, source_type, confidence, status
      FROM limit_windows
      ORDER BY source_id ASC, provider ASC, window ASC, source_type ASC
    `,
  );
  let limits: LimitRow[] = rows.map((row) => ({
    source_id: row.source_id,
    provider: row.provider,
    window: row.window,
    used_percent: Number(row.used_percent),
    remaining_percent: Number(row.remaining_percent),
    reset_at: row.reset_at,
    window_duration_minutes: int(row.window_duration_minutes),
    observed_at: row.observed_at,
    source_type: row.source_type,
    confidence: row.confidence,
    status: row.status,
    official: row.status === "ok" && row.confidence === "observed" && !localEstimateSourceTypes.has(row.source_type),
  }));
  if (refTime) {
    limits = limits.filter((limit) => !limitWindowExpired(limit, refTime));
  }
  return withoutSupersededActiveCache(bestLimitWindows(limits));
}

/**
 * #190：账户小时行 + 逐条目 total_cost 一次拿齐。
 *
 * costsByItem 一律从这里已经读到的、去重前的行上直接汇总（对齐 itemKey(source_id, date,
 * agent)），不再对 usage_hourly_facts 单独发一次 fetchFactRows：rollup 的 total_cost 是
 * facts.total_cost 按更细的分组键（含 client/attribution_confidence/provenance）求和的结果，
 * SUM 满足结合律——按 itemKey 对全部去重前 rollup 行再求一次和，与直接对 facts 按 itemKey
 * 求和在浮点精度内相等（同一批底层 fact 行，只是中间分组粒度不同、累加顺序不同，不保证
 * 逐位相等，但两条实现都不对 total_cost 做四舍五入直接下发，测试用 toBeCloseTo 而不是
 * toBe）。归档 daily fallback 分支不参与这次求和：旧实现的 fetchFactRows 只读
 * usage_hourly_facts，从不读 usage_daily_rollups，历史 fallback 覆盖的日期本来就没有
 * facts 级 total_cost，这里保持同样的缺省。
 *
 * machineFilter/accountFilter 在求和之前应用（而不是让调用方在返回的 costsByItem 上
 * 自己过滤）：旧实现里 summary.ts 是先用 accountHourlyRowMatchesFilter 过滤 factRows，
 * 再调 factCostsByItem——itemKey 本身不含 machine/account，如果某个 source_id 的行分布在
 * 不止一个 machine_id/os_user 上（schema 不禁止，虽然实践中 source_id 通常一机一用户），
 * 求和前不过滤会把请求过滤范围之外的机器/账户的成本也算进同一个 itemKey，与旧行为不符。
 */
async function fetchAccountHourlyRows(
  db: D1Database, startDate: string | null, endDate: string, timezone: string,
  machineFilter?: string | null, accountFilter?: string | null,
): Promise<{ rows: Record<string, unknown>[]; costsByItem: Map<string, number> }> {
  const [startInclusive, endExclusive] = periodWindowBounds(startDate, endDate);
  const rollupTable = startDate === endDate ? "usage_hourly_rollups" : "usage_daily_rollups";
  const pending = await hasPendingRollups(db, startDate, endDate);
  const rollupRows = pending ? [] : await fetchAccountRowsFromTable(db, rollupTable, startInclusive, endExclusive);
  if (rollupRows.length > 0) {
    const inPeriod = rollupRows.filter((row) =>
      accountHourlyRowInPeriod(row, startDate, endDate, timezone)
    );
    const rows = rollupTable === "usage_daily_rollups"
      ? preferHistoricalDailyFallbackRows(inPeriod)
      : preferLegacyHourlyBackfillRows(inPeriod);
    const filteredForCost = inPeriod.filter((row) => accountHourlyRowMatchesFilter(row, machineFilter, accountFilter));
    return { rows, costsByItem: factCostsByItem(filteredForCost) };
  }
  const rawFacts = (await fetchAccountRowsFromTable(db, "usage_hourly_facts", startInclusive, endExclusive))
    .filter((row) => accountHourlyRowInPeriod(row, startDate, endDate, timezone));
  const costsByItem = factCostsByItem(rawFacts.filter((row) => accountHourlyRowMatchesFilter(row, machineFilter, accountFilter)));
  const facts = preferLegacyHourlyBackfillRows(rawFacts);
  if (rollupTable === "usage_daily_rollups") {
    // Archived daily totals are themselves the retained historical source and
    // may have no hourly facts. Keep their existing precedence during recovery.
    const archived = (await fetchAccountRowsFromTable(db, "usage_daily_rollups", startInclusive, endExclusive))
      .filter(row => row.provenance === "historical_ccusage_fallback_v1"
        && accountHourlyRowInPeriod(row, startDate, endDate, timezone));
    const archiveKeys = new Set(archived.map(row => itemKey(str(row.source_id), localDateFromWindowStart(row.window_start) ?? "", str(row.agent))));
    const uncoveredFacts = facts.filter(row => !archiveKeys.has(itemKey(str(row.source_id), localDateFromWindowStart(row.window_start) ?? "", str(row.agent))));
    return { rows: preferHistoricalDailyFallbackRows([...uncoveredFacts, ...archived]), costsByItem };
  }
  return { rows: facts, costsByItem };
}

export async function hasPendingRollups(db: D1Database, startDate: string | null = null, endDate: string | null = null): Promise<boolean> {
  const row = await db.prepare(
    "SELECT date FROM usage_rollup_dirty_days WHERE (? IS NULL OR date >= ?) AND (? IS NULL OR date <= ?) LIMIT 1",
  ).bind(startDate, startDate, endDate, endDate).first();
  return row !== null;
}

function preferHistoricalDailyFallbackRows(rows: Record<string, unknown>[]): Record<string, unknown>[] {
  const fallbackKeys = new Set(
    rows
      .filter((row) => row.provenance === "historical_ccusage_fallback_v1")
      .map((row) => {
        const date = localDateFromWindowStart(row.window_start);
        return date ? itemKey(str(row.source_id), date, str(row.agent)) : "";
      })
      .filter(Boolean),
  );
  const sourceDateFallbackKeys = new Set(
    rows
      .filter((row) =>
        row.provenance === "historical_ccusage_fallback_v1"
        && str(row.agent).toLowerCase() === "all"
      )
      .map((row) => {
        const date = localDateFromWindowStart(row.window_start);
        return date ? `${str(row.source_id)}\u0000${date}` : "";
      })
      .filter(Boolean),
  );
  if (!fallbackKeys.size) return rows;
  return rows.filter((row) => {
    const date = localDateFromWindowStart(row.window_start);
    if (!date) return true;
    const sourceDateKey = `${str(row.source_id)}\u0000${date}`;
    if (sourceDateFallbackKeys.has(sourceDateKey)) {
      return row.provenance === "historical_ccusage_fallback_v1";
    }
    const key = itemKey(str(row.source_id), date, str(row.agent));
    return !fallbackKeys.has(key) || row.provenance === "historical_ccusage_fallback_v1";
  });
}

function preferLegacyHourlyBackfillRows(rows: Record<string, unknown>[]): Record<string, unknown>[] {
  const keys = new Set(
    rows
      .filter((row) => row.provenance === "legacy_hourly_archive_backfill_v1")
      .map((row) =>
        `${str(row.source_id)}\u0000${str(row.window_start)}\u0000${str(row.agent)}`
      ),
  );
  if (!keys.size) return rows;
  return rows.filter((row) => {
    const key = `${str(row.source_id)}\u0000${str(row.window_start)}\u0000${str(row.agent)}`;
    return !keys.has(key) || row.provenance === "legacy_hourly_archive_backfill_v1";
  });
}

async function fetchAccountRowsFromTable(
  db: D1Database,
  table: "usage_hourly_rollups" | "usage_daily_rollups" | "usage_hourly_facts",
  startInclusive: string | null,
  endExclusive: string,
): Promise<Record<string, unknown>[]> {
  const periodWhere = startInclusive === null
    ? "julianday(f.window_start) < julianday(?)"
    : "julianday(f.window_start) >= julianday(?) AND julianday(f.window_start) < julianday(?)";
  const params = startInclusive === null ? [endExclusive] : [startInclusive, endExclusive];
  const source = table === "usage_hourly_facts"
    ? "usage_hourly_facts f"
    : `(SELECT NULL AS fact_id, bucket_start AS window_start, bucket_end AS window_end,
               source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
               attribution_confidence, provenance, input_tokens, output_tokens,
               cache_creation_tokens, cache_read_tokens, reasoning_output_tokens,
               total_tokens, total_cost, event_count, session_count, fact_count
        FROM ${table}) f`;
  const rows = await all<Record<string, unknown>>(
    db,
    `
      SELECT f.fact_id, f.source_id, f.machine_id, COALESCE(m.machine_name, f.machine_id) AS machine_name,
             f.os_user, f.ai_provider, f.ai_account_id,
             COALESCE(a.account_label, f.ai_account_id) AS account_label,
             a.display_name, a.subscription, f.agent, f.client, f.window_start, f.window_end,
             f.input_tokens, f.output_tokens, f.cache_creation_tokens, f.cache_read_tokens,
             f.reasoning_output_tokens, f.total_tokens, f.total_cost, f.event_count, f.session_count,
             f.attribution_confidence, f.provenance
      FROM ${source}
      LEFT JOIN machines m ON m.machine_id = f.machine_id
      LEFT JOIN ai_accounts a ON a.provider = f.ai_provider AND a.account_id = f.ai_account_id
      WHERE ${periodWhere}
      ORDER BY f.window_start ASC, f.source_id ASC, f.agent ASC
    `,
    params,
  );
  return rows;
}

function factCostsByItem(rows: Record<string, unknown>[]): Map<string, number> {
  const totals = new Map<string, number>();
  for (const row of rows) {
    if (row.total_cost === null || row.total_cost === undefined) continue;
    const date = localDateFromWindowStart(row.window_start);
    if (!date) continue;
    const key = itemKey(str(row.source_id), date, str(row.agent));
    totals.set(key, (totals.get(key) ?? 0) + Number(row.total_cost));
  }
  return totals;
}

async function fetchHourlyModelRows(
  db: D1Database,
  startDate: string | null,
  endDate: string,
  timezone: string,
  machineFilter?: string | null,
  accountFilter?: string | null,
): Promise<ModelRow[]> {
  const [startInclusive, endExclusive] = periodWindowBounds(startDate, endDate);
  const periodWhere = startInclusive === null
    ? "julianday(f.window_start) < julianday(?)"
    : "julianday(f.window_start) >= julianday(?) AND julianday(f.window_start) < julianday(?)";
  const params = startInclusive === null ? [endExclusive] : [startInclusive, endExclusive];
  const rows = await all<Record<string, unknown>>(
    db,
    `
      SELECT f.source_id, f.window_start, f.agent, f.machine_id,
             COALESCE(m.machine_name, f.machine_id) AS machine_name, f.os_user,
             hm.model AS model_name, hm.input_tokens, hm.output_tokens,
             hm.cache_creation_tokens, hm.cache_read_tokens, hm.total_tokens, hm.total_cost AS cost
      FROM usage_hourly_models hm
      JOIN usage_hourly_facts f ON f.fact_id = hm.fact_id
      LEFT JOIN machines m ON m.machine_id = f.machine_id
      WHERE ${periodWhere}
      ORDER BY f.window_start ASC, f.source_id ASC, f.agent ASC, hm.model ASC
    `,
    params,
  );
  const aggregated = new Map<string, ModelRow>();
  for (const row of rows) {
    if (!accountHourlyRowInPeriod(row, startDate, endDate, timezone)) continue;
    if (!accountHourlyRowMatchesFilter(row, machineFilter, accountFilter)) continue;
    const date = localDateFromWindowStart(row.window_start);
    if (!date) continue;
    const sourceId = str(row.source_id);
    const agent = str(row.agent);
    const modelName = str(row.model_name || "unknown");
    const key = `${itemKey(sourceId, date, agent)}\u0000${modelName}`;
    const current = aggregated.get(key) ?? {
      source_id: sourceId,
      date,
      agent,
      model_name: modelName,
      input_tokens: 0,
      output_tokens: 0,
      cache_creation_tokens: 0,
      cache_read_tokens: 0,
      total_tokens: 0,
      cost: null,
    };
    current.input_tokens += int(row.input_tokens);
    current.output_tokens += int(row.output_tokens);
    current.cache_creation_tokens += int(row.cache_creation_tokens);
    current.cache_read_tokens += int(row.cache_read_tokens);
    current.total_tokens += int(row.total_tokens);
    if (row.cost !== null && row.cost !== undefined) {
      current.cost = Number(current.cost ?? 0) + Number(row.cost);
    }
    aggregated.set(key, current);
  }
  return Array.from(aggregated.values()).sort((lhs, rhs) =>
    `${lhs.date}:${lhs.source_id}:${lhs.agent}:${lhs.model_name}`
      .localeCompare(`${rhs.date}:${rhs.source_id}:${rhs.agent}:${rhs.model_name}`),
  );
}

async function fetchAiAccounts(db: D1Database): Promise<Record<string, unknown>[]> {
  const rows = await all<Record<string, unknown>>(
    db,
    `
      SELECT provider, account_id, account_label, display_name, subscription, last_seen_at
      FROM ai_accounts
      ORDER BY provider ASC, account_id ASC
    `,
  );
  return rows.map((row) => ({
    provider: row.provider,
    account_id: row.account_id,
    label: row.account_label,
    display_name: row.display_name,
    subscription: row.subscription,
    last_seen_at: row.last_seen_at,
  }));
}

/** #183-b：quota_calibration 是每日 cron 覆盖写的十几行，summary 每次请求整表读一遍。 */
async function fetchQuotaCalibration(db: D1Database): Promise<QuotaCalibrationRow[]> {
  const rows = await all<Record<string, unknown>>(
    db,
    "SELECT provider, model_family, coef, grade, fitted_at, formula_version, backtest_max_err, sample_intervals FROM quota_calibration",
  );
  return rows.map((row) => ({
    provider: str(row.provider),
    model_family: str(row.model_family),
    coef: Number(row.coef),
    grade: str(row.grade),
    fitted_at: str(row.fitted_at),
    formula_version: str(row.formula_version),
    backtest_max_err: row.backtest_max_err == null ? null : Number(row.backtest_max_err),
    sample_intervals: Number(row.sample_intervals),
  }));
}

export {
  all,
  fetchAccountHourlyRows,
  fetchAccountRowsFromTable,
  fetchAiAccounts,
  fetchHourlyModelRows,
  fetchLimitWindows,
  fetchQuotaCalibration,
  fetchSourceIdentities,
  preferHistoricalDailyFallbackRows,
  preferLegacyHourlyBackfillRows,
};
