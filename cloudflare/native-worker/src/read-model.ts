import { buildMobileSummary } from "./mobile-summary";
import { buildVersionHealth, evaluateCollectorRelease, publicVersionView } from "./version-contract";

export type Period = "today" | "week" | "month" | "all";

export interface SummaryRequest {
  date: string;
  period: string;
  timezone: string;
  machine?: string | null;
  account?: string | null;
  currentTime?: string | null;
  backendMode?: string | null;
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
// 与 src/ai_usage_widget/snapshot_builder.py 的 SLOT_PROVIDERS 保持逐字一致。
const slotProviders = ["claude", "codex"] as const;
// pusher 真实会写出来的「跨 agent 聚合」与「来源不明」两个 agent 名，不代表任何 provider。
const aggregateAgentNames = new Set(["", "all", "unknown"]);
const limitStaleAfterMs = 120 * 60 * 1000;

type ProviderUsageTotals = {
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cache_tokens: number;
};

export async function buildSummary(db: D1Database, request: SummaryRequest): Promise<Record<string, unknown>> {
  const refTime = nowInTimezone(request.timezone, request.currentTime);
  const [periodId, startDate, endDate] = periodBounds(request.date, request.period);
  const hourAxisValues = periodId === "today" ? hourAxis(endDate) : [];
  const identities = await fetchSourceIdentities(db);
  const statusRows = await all<Record<string, string | null>>(
    db,
    `
      SELECT source_id, status, collected_at, error_message, collector_version
      FROM source_report_states
      ORDER BY source_id ASC
    `,
  );
  const accuracyRows = await all<Record<string, unknown>>(
    db,
    `
      SELECT source_id, agent, accuracy_status, collector_version, parser_schema_version,
             mode, lookback_hours, coverage_start, coverage_end, matching_full_scans,
             scan_complete, read_errors, unresolved_mismatch, verified_at, observed_at
      FROM source_accuracy
      ORDER BY source_id ASC, agent ASC
    `,
  );
  const limits = await fetchLimitWindows(
    db,
    periodId === "today" && endDate === formatDate(refTime) ? refTime : null,
  );
  const allLimits = await fetchLimitWindows(db, null);
  const accountHourlyRows = await fetchAccountHourlyRows(db, startDate, endDate, request.timezone);
  const aiAccounts = await fetchAiAccounts(db);

  const filteredAccountHourlyRows = accountHourlyRows.filter((row) =>
    accountHourlyRowMatchesFilter(row, request.machine, request.account),
  );
  const historicalFallbackKeys = new Set(
    filteredAccountHourlyRows
      .filter((row) => row.provenance === "historical_ccusage_fallback_v1")
      .map((row) => {
        const date = localDateFromWindowStart(row.window_start);
        return date ? itemKey(str(row.source_id), date, str(row.agent)) : "";
      })
      .filter(Boolean),
  );
  const factRows = (await fetchFactRows(db, startDate, endDate, request.timezone))
    .filter((row) => accountHourlyRowMatchesFilter(row, request.machine, request.account));
  const canonicalProviderTokens = providerTokensByItem(filteredAccountHourlyRows);
  const costsByItem = factCostsByItem(factRows);
  const rows = accountHourlyRowsToDailyRows(filteredAccountHourlyRows).map((row) => ({
    ...row,
    total_cost: costsByItem.get(itemKey(row.source_id, row.date, row.agent)) ?? null,
  }));
  const modelRows = await fetchHourlyModelRows(
    db, startDate, endDate, request.timezone, request.machine, request.account,
  );
  const allowed = new Set(rows.map((row) => itemKey(row.source_id, row.date, row.agent)));
  const allowedModelRows = modelRows.filter((row) => {
    const key = itemKey(row.source_id, row.date, row.agent);
    return allowed.has(key) && !historicalFallbackKeys.has(key);
  });
  const hourlyRows = periodId === "today"
    ? accountHourlyRowsToHourlyRows(filteredAccountHourlyRows)
    : [];
  const blockRows: TimedRow[] = [];
  const accountHourly = accountHourlySummary(filteredAccountHourlyRows);

  const modelsByItem = new Map<string, Record<string, unknown>[]>();
  for (const row of allowedModelRows) {
    const key = itemKey(row.source_id, row.date, row.agent);
    const breakdown = {
      model_name: row.model_name,
      input_tokens: int(row.input_tokens),
      output_tokens: int(row.output_tokens),
      cache_creation_tokens: int(row.cache_creation_tokens),
      cache_read_tokens: int(row.cache_read_tokens),
      total_tokens: int(row.total_tokens),
      cost: row.cost,
    };
    const list = modelsByItem.get(key) ?? [];
    list.push(breakdown);
    modelsByItem.set(key, list);
  }

  const items: Record<string, unknown>[] = [];
  let totalTokens = 0;
  let inputTokens = 0;
  let outputTokens = 0;
  let cacheCreationTokens = 0;
  let cacheReadTokens = 0;
  const machineTotals = new Map<string, {
    name: string;
    total_tokens: number;
    source_ids: Set<string>;
    users: Map<string, { account: string; machine: string; total_tokens: number; source_ids: Set<string> }>;
  }>();
  const accountTotals = new Map<string, number>();
  const agentTotals = new Map<string, number>();
  const providerUsage = new Map<string, ProviderUsageTotals>();
  const trendDates = dateAxis(startDate, endDate, rows);
  const trendByAgent = new Map<string, Map<string, number>>();
  const trendByTokenType = {
    input: new Map(trendDates.map((day) => [day, 0])),
    output: new Map(trendDates.map((day) => [day, 0])),
    cache: new Map(trendDates.map((day) => [day, 0])),
  };
  const trendPoints = new Map(trendDates.map((day) => [day, {
    date: day,
    input_tokens: 0,
    output_tokens: 0,
    cache_tokens: 0,
    total_tokens: 0,
  }]));

  for (const row of rows) {
    const metadata = metadataFromStr(row.metadata_json);
    const machine = str(metadata.machine ?? row.source_id);
    const account = str(metadata.account ?? "unknown");
    const total = int(row.total_tokens);
    const input = int(row.input_tokens);
    const output = int(row.output_tokens);
    const cacheCreation = int(row.cache_creation_tokens);
    const cacheRead = int(row.cache_read_tokens);
    totalTokens += total;
    inputTokens += input;
    outputTokens += output;
    cacheCreationTokens += cacheCreation;
    cacheReadTokens += cacheRead;

    let machineEntry = machineTotals.get(machine);
    if (!machineEntry) {
      machineEntry = { name: machine, total_tokens: 0, source_ids: new Set(), users: new Map() };
      machineTotals.set(machine, machineEntry);
    }
    machineEntry.total_tokens += total;
    machineEntry.source_ids.add(row.source_id);
    let userEntry = machineEntry.users.get(account);
    if (!userEntry) {
      userEntry = { account, machine, total_tokens: 0, source_ids: new Set() };
      machineEntry.users.set(account, userEntry);
    }
    userEntry.total_tokens += total;
    userEntry.source_ids.add(row.source_id);
    accountTotals.set(account, (accountTotals.get(account) ?? 0) + total);
    agentTotals.set(row.agent, (agentTotals.get(row.agent) ?? 0) + total);
    accumulateProviderUsage(
      providerUsage,
      canonicalProviderTokens.get(itemKey(row.source_id, row.date, row.agent)),
      row.agent, input, output, cacheCreation, cacheRead, total,
    );

    if (!trendByAgent.has(row.agent)) {
      trendByAgent.set(row.agent, new Map(trendDates.map((day) => [day, 0])));
    }
    trendByAgent.get(row.agent)?.set(row.date, (trendByAgent.get(row.agent)?.get(row.date) ?? 0) + total);
    const cacheTokens = cacheCreation + cacheRead;
    if (trendByTokenType.input.has(row.date)) {
      trendByTokenType.input.set(row.date, (trendByTokenType.input.get(row.date) ?? 0) + input);
      trendByTokenType.output.set(row.date, (trendByTokenType.output.get(row.date) ?? 0) + output);
      trendByTokenType.cache.set(row.date, (trendByTokenType.cache.get(row.date) ?? 0) + cacheTokens);
      const point = trendPoints.get(row.date);
      if (point) {
        point.input_tokens += input;
        point.output_tokens += output;
        point.cache_tokens += cacheTokens;
        point.total_tokens += total;
      }
    }

    items.push({
      source_id: row.source_id,
      machine,
      account,
      agent: row.agent,
      date: row.date,
      input_tokens: input,
      output_tokens: output,
      cache_creation_tokens: cacheCreation,
      cache_read_tokens: cacheRead,
      total_tokens: total,
      total_cost: row.total_cost,
      model_breakdowns: modelsByItem.get(itemKey(row.source_id, row.date, row.agent)) ?? [],
    });
  }

  for (const [sourceId, identity] of Object.entries(identities)) {
    const machine = str(identity.machine ?? identity.host ?? sourceId);
    const account = str(identity.os_user ?? "unknown");
    if (!identityMatchesFilter(identity, request.machine, request.account)) continue;
    let machineEntry = machineTotals.get(machine);
    if (!machineEntry) {
      machineEntry = { name: machine, total_tokens: 0, source_ids: new Set(), users: new Map() };
      machineTotals.set(machine, machineEntry);
    }
    machineEntry.source_ids.add(sourceId);
    let userEntry = machineEntry.users.get(account);
    if (!userEntry) {
      userEntry = { account, machine, total_tokens: 0, source_ids: new Set() };
      machineEntry.users.set(account, userEntry);
    }
    userEntry.source_ids.add(sourceId);
  }

  const byMachine = Array.from(machineTotals.values()).map((entry) => {
    const users = Array.from(entry.users.values()).map((user) => ({
      account: user.account,
      machine: user.machine,
      display_name: `${user.machine} · ${user.account}`,
      total_tokens: user.total_tokens,
      source_ids: Array.from(user.source_ids).sort(),
    }));
    users.sort((lhs, rhs) => rhs.total_tokens - lhs.total_tokens);
    return {
      name: entry.name,
      display_name: entry.name,
      total_tokens: entry.total_tokens,
      source_ids: Array.from(entry.source_ids).sort(),
      users,
    };
  });
  byMachine.sort((lhs, rhs) => rhs.total_tokens - lhs.total_tokens);

  const byAccount = Array.from(accountTotals.entries())
    .map(([name, total]) => ({ name, total_tokens: total }))
    .sort((lhs, rhs) => rhs.total_tokens - lhs.total_tokens);
  const byAgent = Array.from(agentTotals.entries())
    .map(([name, total]) => ({ name, total_tokens: total }))
    .sort((lhs, rhs) => rhs.total_tokens - lhs.total_tokens);

  const codexContext = codexHourlyContext(rows, hourlyRows);
  let trend: Record<string, unknown>;
  if (periodId === "today") {
    trend = hourlyTrend(hourAxisValues, hourlyRows, blockRows);
    fillTodayHourlyResidual(trend, refTime, {
      total_tokens: totalTokens,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      cache_tokens: cacheCreationTokens + cacheReadTokens,
      excluded_daily: codexContext.skip_residual ? codexContext.daily : undefined,
      excluded_hourly: codexContext.skip_residual ? codexContext.hourly : undefined,
    });
    capTodayHourlyToPeriodTotals(trend, {
      total_tokens: totalTokens,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      cache_tokens: cacheCreationTokens + cacheReadTokens,
    });
  } else {
    trend = {
      period: periodId,
      granularity: "day",
      start_date: startDate,
      end_date: endDate,
      axis: trendDates,
      by_token_type: [
        { type: "input", label: "Input", values: trendDates.map((day) => trendByTokenType.input.get(day) ?? 0) },
        { type: "output", label: "Output", values: trendDates.map((day) => trendByTokenType.output.get(day) ?? 0) },
        { type: "cache", label: "Cache", values: trendDates.map((day) => trendByTokenType.cache.get(day) ?? 0) },
      ],
      points: trendDates.map((day) => trendPoints.get(day)),
      by_agent: Array.from(trendByAgent.entries())
        .sort(([left], [right]) => (agentTotals.get(right) ?? 0) - (agentTotals.get(left) ?? 0))
        .map(([agent, values]) => ({
          agent,
          total_tokens: agentTotals.get(agent) ?? 0,
          values: trendDates.map((day) => values.get(day) ?? 0),
        })),
    };
  }

  const limitStatus = buildLimitStatus(allLimits, refTime);
  const sourceStatus = buildSourceStatus(
    statusRows, accuracyRows, identities, refTime, request.machine, request.account,
  );
  const snapshot: Record<string, unknown> = {
    schema_version: 1,
    generated_at: toOffsetIso(refTime),
    timezone: request.timezone,
    summary: {
      date: request.date,
      period: periodId,
      start_date: startDate,
      end_date: endDate,
      total_tokens: totalTokens,
      input_tokens: inputTokens,
      output_tokens: outputTokens,
      cache_creation_tokens: cacheCreationTokens,
      cache_read_tokens: cacheReadTokens,
    },
    groups: {
      by_machine: byMachine,
      by_account: byAccount,
      by_agent: byAgent,
    },
    items,
    trend,
    source_status: sourceStatus,
    // 键位与 src/ai_usage_widget/snapshot_builder.py 的 `version_health` 一致：紧跟 source_status。
    // 空库同样走这条路径，此时 sourceStatus 是 []，产出全零 counts 与空 needs_attention，
    // 对应 Python 降级快照里的 `build_version_health([])`。
    version_health: buildVersionHealth(sourceStatus),
    limits,
    limit_status: limitStatus,
    provider_slots: buildProviderSlots(providerUsage, allLimits, limitStatus, refTime),
    provider_usage_coverage: buildProviderUsageCoverage(providerUsage, totalTokens),
    account_hourly: accountHourly,
    ai_accounts: aiAccounts,
    metadata: {
      ...summaryMetadata(refTime, limits, normalizedBackendMode(request.backendMode), "cloudflare_d1"),
      codex_hourly: {
        drift: codexContext.drift,
      },
    },
  };
  if (request.machine) (snapshot.summary as Record<string, unknown>).machine = request.machine;
  if (request.account) (snapshot.summary as Record<string, unknown>).account = request.account;
  return snapshot;
}

export async function buildMobile(db: D1Database, request: SummaryRequest): Promise<Record<string, unknown>> {
  return buildMobileSummary(await buildSummary(db, request));
}

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

async function fetchAccountHourlyRows(db: D1Database, startDate: string | null, endDate: string, timezone: string): Promise<Record<string, unknown>[]> {
  const [startInclusive, endExclusive] = periodWindowBounds(startDate, endDate);
  const rollupTable = startDate === endDate ? "usage_hourly_rollups" : "usage_daily_rollups";
  const rollupRows = await fetchAccountRowsFromTable(db, rollupTable, startInclusive, endExclusive);
  if (rollupRows.length > 0) {
    const inPeriod = rollupRows.filter((row) =>
      accountHourlyRowInPeriod(row, startDate, endDate, timezone)
    );
    return rollupTable === "usage_daily_rollups"
      ? preferHistoricalDailyFallbackRows(inPeriod)
      : preferLegacyHourlyBackfillRows(inPeriod);
  }
  return fetchAccountRowsFromTable(db, "usage_hourly_facts", startInclusive, endExclusive)
    .then((rows) => preferLegacyHourlyBackfillRows(
      rows.filter((row) => accountHourlyRowInPeriod(row, startDate, endDate, timezone))
    ));
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

async function fetchFactRows(
  db: D1Database,
  startDate: string | null,
  endDate: string,
  timezone: string,
): Promise<Record<string, unknown>[]> {
  const [startInclusive, endExclusive] = periodWindowBounds(startDate, endDate);
  return fetchAccountRowsFromTable(db, "usage_hourly_facts", startInclusive, endExclusive)
    .then((rows) => rows.filter((row) => accountHourlyRowInPeriod(row, startDate, endDate, timezone)));
}

function periodWindowBounds(startDate: string | null, endDate: string): [string | null, string] {
  return [
    startDate === null ? null : `${startDate}T00:00:00+08:00`,
    `${formatDate(addDays(parseDateOnly(endDate), 1))}T00:00:00+08:00`,
  ];
}

async function fetchAccountRowsFromTable(
  db: D1Database,
  table: "usage_hourly_rollups" | "usage_daily_rollups" | "usage_hourly_facts",
  startInclusive: string | null,
  endExclusive: string,
): Promise<Record<string, unknown>[]> {
  const periodWhere = startInclusive === null
    ? "f.window_start < ?"
    : "f.window_start >= ? AND f.window_start < ?";
  const params = startInclusive === null ? [endExclusive] : [startInclusive, endExclusive];
  const source = table === "usage_hourly_facts"
    ? "usage_hourly_facts f"
    : `(SELECT NULL AS fact_id, bucket_start AS window_start, bucket_end AS window_end,
               source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
               attribution_confidence, provenance, input_tokens, output_tokens,
               cache_creation_tokens, cache_read_tokens, reasoning_output_tokens,
               total_tokens, NULL AS total_cost, event_count, session_count, fact_count
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
    ? "f.window_start < ?"
    : "f.window_start >= ? AND f.window_start < ?";
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

function buildSourceStatus(
  statusRows: Record<string, string | null>[],
  accuracyRows: Record<string, unknown>[],
  identities: Record<string, SourceIdentity>,
  refTime: Date,
  machineFilter?: string | null,
  accountFilter?: string | null,
): Record<string, unknown>[] {
  const accuracyBySource = new Map<string, Record<string, unknown>[]>();
  for (const row of accuracyRows) {
    const sourceId = str(row.source_id);
    const entries = accuracyBySource.get(sourceId) ?? [];
    entries.push(row);
    accuracyBySource.set(sourceId, entries);
  }
  const rows = statusRows
    .filter((row) => identityMatchesFilter(identities[str(row.source_id)], machineFilter, accountFilter))
    .map((row) => {
      const identity = identities[str(row.source_id)] ?? {};
      const status = statusWithStaleness(str(row.status), str(row.collected_at), refTime, 120);
      const machine = identity.machine ?? identity.host;
      const host = identity.host ?? identity.machine;
      const osUser = identity.os_user;
      const result: Record<string, unknown> = {
        source_id: row.source_id,
        status,
        observed_at: row.collected_at,
        error_message: row.error_message,
      };
      if (machine) result.machine = String(machine);
      if (host) result.host = String(host);
      if (osUser) result.os_user = String(osUser);
      if (identity.platform) result.platform = String(identity.platform);
      if (machine && osUser) result.display_name = `${machine} · ${osUser}`;
      else if (machine) result.display_name = String(machine);
      else result.display_name = str(row.source_id || "unknown-source");
      result.accuracy = sourceAccuracySummary(accuracyBySource.get(str(row.source_id)) ?? []);
      result.version = sourceVersionView(row.collector_version);
      return result;
    });
  return rows;
}

/**
 * 某个来源的对外版本块。
 *
 * 物化下来的只有 `collector_version` 一个字段，其余采集端字段一律为 null——
 * 与 `snapshot_builder.py` 的 `source_versions = {source_id: {"collector_version": row[4]}}` 逐字一致。
 * **不得**从 `source_accuracy` 补 `collector_version` / `parser_schema_version`：Python 侧的
 * `source_versions` 是单键 dict，一旦在这里"丰富"，两套实现立刻分叉。
 *
 * 没有版本时传 `null` 而不是 `{collector_version: null}`：前者判成
 * `collector_release_missing`（Python 侧 `if row[4]` 过滤掉空值的行为），后者是
 * `collector_version_missing`。0007 迁移后存量行的该列全是 NULL，这是常态路径。
 */
function sourceVersionView(collectorVersion: unknown): Record<string, unknown> {
  const release = collectorVersion ? { collector_version: collectorVersion } : null;
  return publicVersionView(evaluateCollectorRelease(release));
}

/**
 * `/api/health` 的来源条目。
 *
 * 只吃 `source_report_states` + `source_identities` 两张表的行，**不调用 `buildSummary`**：
 * 那会把 usage_daily / usage_hourly_facts / limit_windows / source_accuracy 全拉进一个
 * 健康检查端点，是实打实的 D1 读取量回退。
 *
 * 条目成形逻辑复用 `buildSourceStatus`，于是 `/api/health` 的 `source_status.counts`、
 * `versions` 与 `/api/summary` 的 `source_status` 是同一份产物：status 一律带 120 分钟
 * 过期折算（Python 侧 `snapshot_source_health._status_with_staleness()` 的同一口径）。
 */
export function buildHealthSourceStatus(
  rows: Record<string, string | null>[],
  currentTime?: string | null,
): Record<string, unknown>[] {
  const refTime = nowInTimezone("Asia/Shanghai", currentTime);
  const identities: Record<string, SourceIdentity> = {};
  for (const row of rows) {
    identities[str(row.source_id)] = {
      host: row.host,
      machine: row.machine ?? row.host,
      os_user: row.os_user,
      platform: row.platform,
    };
  }
  return buildSourceStatus(rows, [], identities, refTime);
}

function sourceAccuracySummary(rows: Record<string, unknown>[]): Record<string, unknown> {
  if (!rows.length) return { status: "unknown", agents: [] };
  const agents = rows.map((row) => ({
    agent: row.agent,
    status: row.accuracy_status || "unknown",
    collector_version: row.collector_version,
    parser_schema_version: int(row.parser_schema_version),
    mode: row.mode,
    lookback_hours: row.lookback_hours,
    coverage: { start: row.coverage_start, end: row.coverage_end },
    matching_full_scans: int(row.matching_full_scans),
    scan_complete: int(row.scan_complete) === 1,
    read_errors: int(row.read_errors),
    unresolved_mismatch: int(row.unresolved_mismatch),
    verified_at: row.verified_at,
    observed_at: row.observed_at,
  }));
  const statuses = agents.map((row) => str(row.status));
  const status = statuses.every((value) => value === "verified") ? "verified" : "unverified";
  const primary = agents.length === 1 ? agents[0] : null;
  return {
    status,
    collector_version: primary?.collector_version ?? null,
    matching_full_scans: primary?.matching_full_scans ?? Math.min(...agents.map((row) => int(row.matching_full_scans))),
    verified_at: primary?.verified_at ?? null,
    agents,
  };
}

function statusWithStaleness(status: string, collectedAt: string, refTime: Date, staleMinutes: number): string {
  const collected = new Date(collectedAt);
  if (Number.isNaN(collected.getTime())) return status;
  const diffMinutes = (refTime.getTime() - collected.getTime()) / 60000;
  return diffMinutes > staleMinutes ? "stale" : status;
}

function hourlyTrend(axis: string[], rows: TimedRow[], blockRows: TimedRow[]): Record<string, unknown> {
  const byTokenType = {
    input: new Map(axis.map((hour) => [hour, 0])),
    output: new Map(axis.map((hour) => [hour, 0])),
    cache: new Map(axis.map((hour) => [hour, 0])),
  };
  const points = new Map(axis.map((hour) => [hour, {
    date: hour,
    hour,
    input_tokens: 0,
    output_tokens: 0,
    cache_tokens: 0,
    total_tokens: 0,
  }]));
  const agentTotals = new Map<string, number>();
  const byAgent = new Map<string, Map<string, number>>();
  blockRows = dedupeCumulativeBlockRows(blockRows);
  const blockSources = new Set(blockRows.map((row) => row.source_id));

  for (const row of rows) {
    const hour = str(row.hour);
    if (!points.has(hour)) continue;
    if (blockSources.has(row.source_id) && !isCodexAgent(row.agent)) continue;
    addTimedPoint(axis, hour, row, byTokenType, points, agentTotals, byAgent);
  }
  for (const row of blockRows) {
    addBlockToHourBuckets(axis, row, byTokenType, points, agentTotals, byAgent);
  }

  return {
    period: "today",
    granularity: "hour",
    start_date: axis.length ? axis[0].slice(0, 10) : null,
    end_date: axis.length ? axis[axis.length - 1].slice(0, 10) : null,
    axis,
    by_token_type: [
      { type: "input", label: "Input", values: axis.map((hour) => Math.round(byTokenType.input.get(hour) ?? 0)) },
      { type: "output", label: "Output", values: axis.map((hour) => Math.round(byTokenType.output.get(hour) ?? 0)) },
      { type: "cache", label: "Cache", values: axis.map((hour) => Math.round(byTokenType.cache.get(hour) ?? 0)) },
    ],
    points: axis.map((hour) => points.get(hour)),
    by_agent: Array.from(byAgent.entries())
      .sort(([left], [right]) => (agentTotals.get(right) ?? 0) - (agentTotals.get(left) ?? 0))
      .map(([agent, values]) => ({
        agent,
        total_tokens: Math.round(agentTotals.get(agent) ?? 0),
        values: axis.map((hour) => Math.round(values.get(hour) ?? 0)),
      })),
  };
}

function addTimedPoint(
  axis: string[],
  hour: string,
  row: TimedRow,
  byTokenType: Record<"input" | "output" | "cache", Map<string, number>>,
  points: Map<string, Record<string, number | string>>,
  agentTotals: Map<string, number>,
  byAgent: Map<string, Map<string, number>>,
): void {
  const cache = int(row.cache_creation_tokens) + int(row.cache_read_tokens);
  byTokenType.input.set(hour, (byTokenType.input.get(hour) ?? 0) + int(row.input_tokens));
  byTokenType.output.set(hour, (byTokenType.output.get(hour) ?? 0) + int(row.output_tokens));
  byTokenType.cache.set(hour, (byTokenType.cache.get(hour) ?? 0) + cache);
  const point = points.get(hour);
  if (point) {
    point.input_tokens = int(point.input_tokens) + int(row.input_tokens);
    point.output_tokens = int(point.output_tokens) + int(row.output_tokens);
    point.cache_tokens = int(point.cache_tokens) + cache;
    point.total_tokens = int(point.total_tokens) + int(row.total_tokens);
  }
  agentTotals.set(row.agent, (agentTotals.get(row.agent) ?? 0) + int(row.total_tokens));
  if (!byAgent.has(row.agent)) byAgent.set(row.agent, new Map(axis.map((item) => [item, 0])));
  byAgent.get(row.agent)?.set(hour, (byAgent.get(row.agent)?.get(hour) ?? 0) + int(row.total_tokens));
}

function addBlockToHourBuckets(
  axis: string[],
  row: TimedRow,
  byTokenType: Record<"input" | "output" | "cache", Map<string, number>>,
  points: Map<string, Record<string, number | string>>,
  agentTotals: Map<string, number>,
  byAgent: Map<string, Map<string, number>>,
): void {
  const start = parseDate(str(row.start_time));
  const end = parseDate(str(row.end_time));
  if (!start || !end || end <= start) return;
  const duration = end.getTime() - start.getTime();
  if (!byAgent.has(row.agent)) byAgent.set(row.agent, new Map(axis.map((hour) => [hour, 0])));
  for (const hour of axis) {
    const hourStart = parseDate(hour);
    if (!hourStart) continue;
    const hourEnd = new Date(hourStart.getTime() + 3600000);
    const overlap = Math.max(0, Math.min(end.getTime(), hourEnd.getTime()) - Math.max(start.getTime(), hourStart.getTime()));
    if (overlap <= 0) continue;
    const ratio = overlap / duration;
    const input = int(row.input_tokens) * ratio;
    const output = int(row.output_tokens) * ratio;
    const cache = (int(row.cache_creation_tokens) + int(row.cache_read_tokens)) * ratio;
    const total = int(row.total_tokens) * ratio;
    byTokenType.input.set(hour, (byTokenType.input.get(hour) ?? 0) + input);
    byTokenType.output.set(hour, (byTokenType.output.get(hour) ?? 0) + output);
    byTokenType.cache.set(hour, (byTokenType.cache.get(hour) ?? 0) + cache);
    const point = points.get(hour);
    if (point) {
      point.input_tokens = Math.round(int(point.input_tokens) + input);
      point.output_tokens = Math.round(int(point.output_tokens) + output);
      point.cache_tokens = Math.round(int(point.cache_tokens) + cache);
      point.total_tokens = Math.round(int(point.total_tokens) + total);
    }
    agentTotals.set(row.agent, (agentTotals.get(row.agent) ?? 0) + total);
    byAgent.get(row.agent)?.set(hour, (byAgent.get(row.agent)?.get(hour) ?? 0) + total);
  }
}

function dedupeCumulativeBlockRows(rows: TimedRow[]): TimedRow[] {
  const latestByKey = new Map<string, TimedRow>();
  for (const row of rows) {
    const key = blockDedupeKey(row);
    const current = latestByKey.get(key);
    if (!current || blockRowSortKey(row).localeCompare(blockRowSortKey(current)) >= 0) {
      latestByKey.set(key, row);
    }
  }
  return Array.from(latestByKey.values())
    .sort((lhs, rhs) =>
      `${lhs.start_time || ""}:${lhs.source_id}:${lhs.agent}:${lhs.end_time || ""}`
        .localeCompare(`${rhs.start_time || ""}:${rhs.source_id}:${rhs.agent}:${rhs.end_time || ""}`),
    );
}

function blockDedupeKey(row: TimedRow): string {
  const rawBlock = metadataObject(row.metadata_json).ccusage_block_row;
  const blockId = isRecord(rawBlock) ? str(rawBlock.id) : "";
  if (blockId) return `${row.source_id}\u0000${row.agent}\u0000${blockId}`;
  return `${row.source_id}\u0000${row.agent}\u0000${row.start_time || ""}\u0000${row.end_time || ""}`;
}

function blockRowSortKey(row: TimedRow): string {
  return `${row.end_time || ""}\u0000${String(int(row.total_tokens)).padStart(16, "0")}`;
}

function metadataObject(raw: unknown): Record<string, unknown> {
  if (!raw) return {};
  try {
    const parsed = JSON.parse(str(raw));
    return isRecord(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function fillTodayHourlyResidual(trend: Record<string, unknown>, refTime: Date, totals: {
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cache_tokens: number;
  excluded_daily?: Record<string, number>;
  excluded_hourly?: Record<string, number>;
}): void {
  const points = asArray<Record<string, unknown>>(trend.points);
  const axis = asArray<string>(trend.axis);
  if (!points.length || !axis.length) return;
  const excludedDaily = totals.excluded_daily ?? emptyTokenTotals();
  const excludedHourly = totals.excluded_hourly ?? emptyTokenTotals();
  const currentTotal = points.reduce((sum, point) => sum + int(point.total_tokens), 0) - excludedHourly.total;
  const residualTotal = Math.max(int(totals.total_tokens) - excludedDaily.total - currentTotal, 0);
  const tokenResiduals = {
    input: Math.max(int(totals.input_tokens) - excludedDaily.input - (sumTokenType(trend, "input") - excludedHourly.input), 0),
    output: Math.max(int(totals.output_tokens) - excludedDaily.output - (sumTokenType(trend, "output") - excludedHourly.output), 0),
    cache: Math.max(int(totals.cache_tokens) - excludedDaily.cache - (sumTokenType(trend, "cache") - excludedHourly.cache), 0),
  };
  if (residualTotal <= 0 && Object.values(tokenResiduals).every((value) => value <= 0)) return;
  const refHour = toOffsetIso(new Date(Math.floor(refTime.getTime() / 3600000) * 3600000));
  const targetHour = axis.includes(refHour) ? refHour : axis[axis.length - 1];
  const index = axis.indexOf(targetHour);
  const point = points[index];
  point.input_tokens = int(point.input_tokens) + tokenResiduals.input;
  point.output_tokens = int(point.output_tokens) + tokenResiduals.output;
  point.cache_tokens = int(point.cache_tokens) + tokenResiduals.cache;
  point.total_tokens = int(point.total_tokens) + residualTotal;
  for (const row of asArray<Record<string, unknown>>(trend.by_token_type)) {
    const tokenType = str(row.type) as "input" | "output" | "cache";
    const values = asArray<number>(row.values);
    if (tokenType in tokenResiduals && index < values.length) values[index] += tokenResiduals[tokenType];
  }
}

function capTodayHourlyToPeriodTotals(trend: Record<string, unknown>, totals: {
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cache_tokens: number;
}): void {
  const points = asArray<Record<string, unknown>>(trend.points);
  if (!points.length) return;
  const pointTotals = points.map((point) => int(point.total_tokens));
  const cappedTotals = scaleDownInts(pointTotals, int(totals.total_tokens));
  if (JSON.stringify(cappedTotals) !== JSON.stringify(pointTotals)) {
    points.forEach((point, index) => {
      point.total_tokens = cappedTotals[index];
    });
    scaleAgentRows(trend, int(totals.total_tokens));
  }
  const targets = { input: int(totals.input_tokens), output: int(totals.output_tokens), cache: int(totals.cache_tokens) };
  const pointFields = { input: "input_tokens", output: "output_tokens", cache: "cache_tokens" };
  for (const row of asArray<Record<string, unknown>>(trend.by_token_type)) {
    const tokenType = str(row.type) as "input" | "output" | "cache";
    if (!(tokenType in targets)) continue;
    const values = asArray<number>(row.values).map((value) => int(value));
    const capped = scaleDownInts(values, targets[tokenType]);
    row.values = capped;
    points.forEach((point, index) => {
      point[pointFields[tokenType]] = capped[index];
    });
  }
}

function scaleDownInts(values: number[], target: number): number[] {
  const current = values.reduce((sum, value) => sum + value, 0);
  if (current <= target || current <= 0) return values;
  if (target <= 0) return values.map(() => 0);
  const scaled = values.map((value) => value * target / current);
  const floors = scaled.map((value) => Math.floor(value));
  let remainder = target - floors.reduce((sum, value) => sum + value, 0);
  const fractions = scaled.map((value, index) => ({ fraction: value - floors[index], index }))
    .sort((lhs, rhs) => rhs.fraction - lhs.fraction || rhs.index - lhs.index);
  for (const item of fractions) {
    if (remainder <= 0) break;
    floors[item.index] += 1;
    remainder -= 1;
  }
  return floors;
}

function scaleAgentRows(trend: Record<string, unknown>, totalTokens: number): void {
  for (const row of asArray<Record<string, unknown>>(trend.by_agent)) {
    const values = asArray<number>(row.values).map((value) => int(value));
    const capped = scaleDownInts(values, totalTokens);
    row.values = capped;
    row.total_tokens = capped.reduce((sum, value) => sum + value, 0);
  }
}

function codexHourlyContext(dailyRows: DailyRow[], hourlyRows: TimedRow[]): {
  drift: Record<string, unknown>;
  daily: Record<string, number>;
  hourly: Record<string, number>;
  skip_residual: boolean;
} {
  let drift: Record<string, unknown> = { status: "comparison_unavailable" };
  let daily = emptyTokenTotals();
  const allDaily = emptyTokenTotals();
  const hourly = emptyTokenTotals();
  for (const row of dailyRows) {
    let target: Record<string, number> | null = null;
    if (isCodexAgent(row.agent)) target = daily;
    else if (row.agent.toLowerCase() === "all") target = allDaily;
    if (!target) continue;
    target.input += int(row.input_tokens);
    target.output += int(row.output_tokens);
    target.cache += int(row.cache_creation_tokens) + int(row.cache_read_tokens);
    target.total += int(row.total_tokens);
  }
  for (const row of hourlyRows) {
    const metadata = metadataFromStr(row.metadata_json);
    if (!isCodexAgent(row.agent) || metadata.provenance !== "mswusage_codex_token_count") continue;
    hourly.input += int(row.input_tokens);
    hourly.output += int(row.output_tokens);
    hourly.cache += int(row.cache_creation_tokens) + int(row.cache_read_tokens);
    hourly.total += int(row.total_tokens);
    if (isRecord(metadata.drift)) drift = { ...metadata.drift };
  }
  if (daily.total === 0 && drift.baseline_agent === "all") daily = allDaily;
  const status = str(drift.status);
  return {
    drift,
    daily,
    hourly,
    skip_residual: ["drift_detected", "comparison_unavailable"].includes(status) && hourly.total > 0,
  };
}

function accountHourlySummary(rows: Record<string, unknown>[]): Record<string, unknown> {
  if (!rows.length) return emptyAccountHourlySummary();
  let totalTokens = 0;
  const byAiAccount = new Map<string, Record<string, unknown>>();
  const byMachine = new Map<string, Record<string, unknown>>();
  const byOsUser = new Map<string, Record<string, unknown>>();
  const byAgent = new Map<string, number>();
  const byConfidence = new Map<string, number>();
  for (const row of rows) {
    const tokens = int(row.total_tokens);
    totalTokens += tokens;
    const provider = str(row.ai_provider);
    const accountId = str(row.ai_account_id);
    const accountKey = `${provider}:${accountId}`;
    const account = byAiAccount.get(accountKey) ?? {
      provider,
      account_id: accountId,
      label: row.account_label,
      display_name: row.display_name,
      subscription: row.subscription,
      total_tokens: 0,
      input_tokens: 0,
      output_tokens: 0,
      cache_tokens: 0,
      reasoning_output_tokens: 0,
      confidence: new Map<string, number>(),
      source_ids: new Set<string>(),
    };
    account.total_tokens = int(account.total_tokens) + tokens;
    account.input_tokens = int(account.input_tokens) + int(row.input_tokens);
    account.output_tokens = int(account.output_tokens) + int(row.output_tokens);
    account.cache_tokens = int(account.cache_tokens) + int(row.cache_creation_tokens) + int(row.cache_read_tokens);
    account.reasoning_output_tokens = int(account.reasoning_output_tokens) + int(row.reasoning_output_tokens);
    const confidence = str(row.attribution_confidence);
    (account.confidence as Map<string, number>).set(confidence, ((account.confidence as Map<string, number>).get(confidence) ?? 0) + tokens);
    (account.source_ids as Set<string>).add(str(row.source_id));
    byAiAccount.set(accountKey, account);

    const machineId = str(row.machine_id);
    const machine = byMachine.get(machineId) ?? { machine_id: machineId, machine_name: row.machine_name, total_tokens: 0 };
    machine.total_tokens = int(machine.total_tokens) + tokens;
    byMachine.set(machineId, machine);

    const userKey = `${machineId}:${str(row.os_user)}`;
    const user = byOsUser.get(userKey) ?? {
      machine_id: machineId,
      machine_name: row.machine_name,
      os_user: row.os_user,
      display_name: `${row.machine_name} · ${row.os_user}`,
      total_tokens: 0,
    };
    user.total_tokens = int(user.total_tokens) + tokens;
    byOsUser.set(userKey, user);

    byAgent.set(str(row.agent), (byAgent.get(str(row.agent)) ?? 0) + tokens);
    byConfidence.set(confidence, (byConfidence.get(confidence) ?? 0) + tokens);
  }
  const accounts: Record<string, unknown>[] = Array.from(byAiAccount.values()).map((entry) => {
    const confidenceMap = entry.confidence as Map<string, number>;
    const confidenceBreakdown = Array.from(confidenceMap.entries())
      .map(([confidence, total]) => ({ confidence, total_tokens: total }))
      .sort((lhs, rhs) => rhs.total_tokens - lhs.total_tokens);
    const sourceIds = Array.from(entry.source_ids as Set<string>).sort();
    const { confidence, source_ids, ...rest } = entry;
    return {
      ...rest,
      confidence_breakdown: confidenceBreakdown,
      attribution_confidence: confidenceBreakdown.length === 1 ? confidenceBreakdown[0].confidence : "mixed",
      source_ids: sourceIds,
    };
  });
  return {
    total_tokens: totalTokens,
    facts: rows.reduce((total, row) => total + Math.max(1, int(row.fact_count ?? 1)), 0),
    by_ai_account: accounts.sort((lhs, rhs) => int(rhs.total_tokens) - int(lhs.total_tokens)),
    by_machine: Array.from(byMachine.values()).sort((lhs, rhs) => int(rhs.total_tokens) - int(lhs.total_tokens)),
    by_os_user: Array.from(byOsUser.values()).sort((lhs, rhs) => int(rhs.total_tokens) - int(lhs.total_tokens)),
    by_agent: Array.from(byAgent.entries()).sort((lhs, rhs) => rhs[1] - lhs[1]).map(([name, tokens]) => ({ name, total_tokens: tokens })),
    confidence_breakdown: Array.from(byConfidence.entries()).sort((lhs, rhs) => rhs[1] - lhs[1]).map(([confidence, tokens]) => ({ confidence, total_tokens: tokens })),
  };
}

function accountHourlyRowsToDailyRows(rows: Record<string, unknown>[]): DailyRow[] {
  const buckets = new Map<string, {
    source_id: string;
    date: string;
    agent: string;
    input_tokens: number;
    output_tokens: number;
    cache_creation_tokens: number;
    cache_read_tokens: number;
    total_tokens: number;
    machine: string;
    account: string;
    provenances: Set<string>;
  }>();
  for (const row of rows) {
    const date = localDateFromWindowStart(row.window_start);
    if (!date) continue;
    const sourceId = str(row.source_id);
    const agent = str(row.agent);
    const key = itemKey(sourceId, date, agent);
    const bucket = buckets.get(key) ?? {
      source_id: sourceId,
      date,
      agent,
      input_tokens: 0,
      output_tokens: 0,
      cache_creation_tokens: 0,
      cache_read_tokens: 0,
      total_tokens: 0,
      machine: str(row.machine_name || row.machine_id || sourceId),
      account: str(row.os_user || "unknown"),
      provenances: new Set(),
    };
    bucket.input_tokens += int(row.input_tokens);
    bucket.output_tokens += int(row.output_tokens);
    bucket.cache_creation_tokens += int(row.cache_creation_tokens);
    bucket.cache_read_tokens += int(row.cache_read_tokens);
    bucket.total_tokens += int(row.total_tokens);
    bucket.provenances.add(str(row.provenance || "usage_hourly_facts"));
    buckets.set(key, bucket);
  }
  return Array.from(buckets.values())
    .sort((lhs, rhs) => `${lhs.date}:${lhs.source_id}:${lhs.agent}`.localeCompare(`${rhs.date}:${rhs.source_id}:${rhs.agent}`))
    .map((bucket) => ({
      source_id: bucket.source_id,
      date: bucket.date,
      agent: bucket.agent,
      input_tokens: bucket.input_tokens,
      output_tokens: bucket.output_tokens,
      cache_creation_tokens: bucket.cache_creation_tokens,
      cache_read_tokens: bucket.cache_read_tokens,
      total_tokens: bucket.total_tokens,
      total_cost: null,
      metadata_json: JSON.stringify({
        machine: bucket.machine,
        account: bucket.account,
        os_user: bucket.account,
        provenance: "usage_ledger_hourly_facts",
        source_provenances: Array.from(bucket.provenances).sort(),
      }),
    }));
}

function accountHourlyRowsToHourlyRows(rows: Record<string, unknown>[]): TimedRow[] {
  const buckets = new Map<string, {
    source_id: string;
    hour: string;
    agent: string;
    input_tokens: number;
    output_tokens: number;
    cache_creation_tokens: number;
    cache_read_tokens: number;
    total_tokens: number;
    machine: string;
    account: string;
    provenances: Set<string>;
  }>();
  for (const row of rows) {
    const hour = localHourFromWindowStart(row.window_start);
    if (!hour) continue;
    const sourceId = str(row.source_id);
    const agent = str(row.agent);
    const key = `${sourceId}\u0000${hour}\u0000${agent}`;
    const bucket = buckets.get(key) ?? {
      source_id: sourceId,
      hour,
      agent,
      input_tokens: 0,
      output_tokens: 0,
      cache_creation_tokens: 0,
      cache_read_tokens: 0,
      total_tokens: 0,
      machine: str(row.machine_name || row.machine_id || sourceId),
      account: str(row.os_user || "unknown"),
      provenances: new Set(),
    };
    bucket.input_tokens += int(row.input_tokens);
    bucket.output_tokens += int(row.output_tokens);
    bucket.cache_creation_tokens += int(row.cache_creation_tokens);
    bucket.cache_read_tokens += int(row.cache_read_tokens);
    bucket.total_tokens += int(row.total_tokens);
    bucket.provenances.add(str(row.provenance || "usage_hourly_facts"));
    buckets.set(key, bucket);
  }
  return Array.from(buckets.values())
    .sort((lhs, rhs) => `${lhs.hour}:${lhs.source_id}:${lhs.agent}`.localeCompare(`${rhs.hour}:${rhs.source_id}:${rhs.agent}`))
    .map((bucket) => ({
      source_id: bucket.source_id,
      hour: bucket.hour,
      agent: bucket.agent,
      input_tokens: bucket.input_tokens,
      output_tokens: bucket.output_tokens,
      cache_creation_tokens: bucket.cache_creation_tokens,
      cache_read_tokens: bucket.cache_read_tokens,
      total_tokens: bucket.total_tokens,
      total_cost: null,
      metadata_json: JSON.stringify({
        machine: bucket.machine,
        account: bucket.account,
        os_user: bucket.account,
        provenance: "usage_ledger_hourly_facts",
        source_provenances: Array.from(bucket.provenances).sort(),
      }),
    }));
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

function emptyAccountHourlySummary(): Record<string, unknown> {
  return {
    total_tokens: 0,
    facts: 0,
    by_ai_account: [],
    by_machine: [],
    by_os_user: [],
    by_agent: [],
    confidence_breakdown: [],
  };
}

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

function summaryMetadata(
  refTime: Date,
  limits: LimitRow[],
  backendMode: string,
  canonicalStore: string,
): Record<string, unknown> {
  const effective = limits.filter((limit) => effectiveLimitWindow(limit));
  const observed = effective
    .map((limit) => limit.observed_at || "")
    .filter(Boolean)
    .sort();
  return {
    backend_mode: backendMode,
    canonical_store: canonicalStore,
    read_model_generated_at: toOffsetIso(refTime),
    freshness_status: effective.length ? "ok" : "unknown",
    limits_observed_at: observed.length ? observed[observed.length - 1] : null,
  };
}

function normalizedBackendMode(value: string | null | undefined): string {
  const configured = String(value ?? "").trim();
  return configured || "native_d1_unknown";
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

function slotProviderKey(value: unknown): string {
  const provider = str(value).trim().toLowerCase();
  if (provider === "claude" || provider === "anthropic") return "claude";
  if (provider === "codex" || provider === "openai") return "codex";
  return provider;
}

// agent 名字只是**兜底**归属，权威字段是 usage_hourly_facts.ai_provider。
// `all` / `unknown` 表示「跨 agent / 来源不明」，不能被硬塞进任何一个 provider 槽位。
// 与 src/ai_usage_widget/snapshot_builder.py 的 _usage_provider_key 保持一致。
function usageProviderKey(agent: unknown): string {
  const name = str(agent).trim().toLowerCase();
  if (aggregateAgentNames.has(name)) return "";
  const key = slotProviderKey(name);
  if ((slotProviders as readonly string[]).includes(key)) return key;
  if (name.includes("claude")) return "claude";
  if (name.includes("codex") || name.includes("openai") || name.includes("gpt")) return "codex";
  return name;
}

// 按 canonical ai_provider 把每个 (source_id, date, agent) 的用量拆开。ledger 行整条替换
// 同 key 的行，所以分项之和恒等于该 item 的总量，归属是精确切分而不是估算。
function providerTokensByItem(rows: Record<string, unknown>[]): Map<string, Map<string, ProviderUsageTotals>> {
  const result = new Map<string, Map<string, ProviderUsageTotals>>();
  for (const row of rows) {
    const date = localDateFromWindowStart(row.window_start);
    if (!date) continue;
    const key = itemKey(str(row.source_id), date, str(row.agent));
    const provider = slotProviderKey(row.ai_provider);
    const byProvider = result.get(key) ?? new Map<string, ProviderUsageTotals>();
    const entry = byProvider.get(provider)
      ?? { total_tokens: 0, input_tokens: 0, output_tokens: 0, cache_tokens: 0 };
    entry.total_tokens += int(row.total_tokens);
    entry.input_tokens += int(row.input_tokens);
    entry.output_tokens += int(row.output_tokens);
    entry.cache_tokens += int(row.cache_creation_tokens) + int(row.cache_read_tokens);
    byProvider.set(provider, entry);
    result.set(key, byProvider);
  }
  return result;
}

function accumulateProviderUsage(
  providerUsage: Map<string, ProviderUsageTotals>,
  canonicalBreakdown: Map<string, ProviderUsageTotals> | undefined,
  agent: unknown,
  inputTokens: number,
  outputTokens: number,
  cacheCreationTokens: number,
  cacheReadTokens: number,
  totalTokens: number,
): void {
  if (canonicalBreakdown && canonicalBreakdown.size) {
    for (const [provider, totals] of canonicalBreakdown) {
      addProviderUsage(
        providerUsage, provider,
        totals.input_tokens, totals.output_tokens, totals.cache_tokens, totals.total_tokens,
      );
    }
    return;
  }
  addProviderUsage(
    providerUsage, usageProviderKey(agent),
    inputTokens, outputTokens, cacheCreationTokens + cacheReadTokens, totalTokens,
  );
}

function addProviderUsage(
  providerUsage: Map<string, ProviderUsageTotals>,
  provider: string,
  inputTokens: number,
  outputTokens: number,
  cacheTokens: number,
  totalTokens: number,
): void {
  // provider === "" 表示无法归属，同样要入账，否则用量会静默消失。
  const entry = providerUsage.get(provider)
    ?? { total_tokens: 0, input_tokens: 0, output_tokens: 0, cache_tokens: 0 };
  entry.total_tokens += totalTokens;
  entry.input_tokens += inputTokens;
  entry.output_tokens += outputTokens;
  entry.cache_tokens += cacheTokens;
  providerUsage.set(provider, entry);
}

// 把「用户能看到的」和「看不到的」分开点名。固定槽位只有 claude / codex，
// 进不了槽位的 token 分两类各自报出来：other_provider_tokens（有 canonical provider
// 但没槽位，例如 antigravity）、unattributed_tokens（连 provider 都定不了）。
// 恒等式：attributed + other_provider + unattributed == total，attributed 就是槽位之和。
// 与 src/ai_usage_widget/snapshot_builder.py 的 _build_provider_usage_coverage 一致。
function buildProviderUsageCoverage(
  providerUsage: Map<string, ProviderUsageTotals>,
  totalTokens: number,
): Record<string, unknown> {
  let attributed = 0;
  for (const provider of slotProviders) {
    attributed += providerUsage.get(provider)?.total_tokens ?? 0;
  }
  const unattributed = providerUsage.get("")?.total_tokens ?? 0;
  let other = 0;
  for (const [provider, totals] of providerUsage) {
    if (provider && !(slotProviders as readonly string[]).includes(provider)) {
      other += totals.total_tokens;
    }
  }
  return {
    status: other === 0 && unattributed === 0 ? "complete" : "partial",
    total_tokens: totalTokens,
    attributed_tokens: attributed,
    other_provider_tokens: other,
    unattributed_tokens: unattributed,
  };
}

function buildProviderSlots(
  providerUsage: Map<string, ProviderUsageTotals>,
  allLimits: LimitRow[],
  limitStatus: Record<string, unknown>[],
  refTime: Date,
): Record<string, unknown>[] {
  const statusByProvider = new Map<string, Record<string, unknown>>();
  for (const row of limitStatus) statusByProvider.set(slotProviderKey(row.provider), row);
  const rowsByProvider = new Map<string, LimitRow[]>();
  for (const limit of allLimits) {
    const key = slotProviderKey(limit.provider);
    rowsByProvider.set(key, [...(rowsByProvider.get(key) ?? []), limit]);
  }
  return slotProviders.map((provider) => ({
    provider,
    usage: providerUsageSlot(providerUsage.get(provider)),
    quota: providerQuotaSlot(rowsByProvider.get(provider) ?? [], statusByProvider.get(provider), refTime),
  }));
}

function providerUsageSlot(totals: ProviderUsageTotals | undefined): Record<string, unknown> {
  const total = int(totals?.total_tokens ?? 0);
  return {
    status: total > 0 ? "available" : "missing",
    total_tokens: total,
    input_tokens: int(totals?.input_tokens ?? 0),
    output_tokens: int(totals?.output_tokens ?? 0),
    cache_tokens: int(totals?.cache_tokens ?? 0),
  };
}

function providerQuotaSlot(
  rows: LimitRow[],
  statusRow: Record<string, unknown> | undefined,
  refTime: Date,
): Record<string, unknown> {
  const selectedSourceId = statusRow ? statusRow.source_id : undefined;
  const lastVerifiedAt = lastVerifiedAtOf(rows, selectedSourceId);
  // 缺失态只暴露「最近一次验证时间」和来源标识，绝不带任何百分比或 reset 时间。
  const missing = (reason: string, sourceId: unknown = null, sourceType: unknown = null) => ({
    status: "missing",
    reason,
    last_verified_at: lastVerifiedAt,
    source_id: sourceId || null,
    source_type: sourceType || null,
    windows: [] as LimitRow[],
  });

  if (!statusRow) return missing(rows.length ? "unverified" : "no_data");

  const sourceId = statusRow.source_id;
  const sourceType = statusRow.source_type;
  const state = str(statusRow.status);
  if (state !== "ok") return missing(state || "unverified", sourceId, sourceType);

  const windows = rows.filter((row) =>
    str(row.source_id) === str(sourceId) &&
    effectiveLimitWindow(row) &&
    !limitWindowStale(row, refTime) &&
    !limitWindowExpired(row, refTime));
  if (!windows.length) return missing("unverified", sourceId, sourceType);
  return {
    status: "available",
    reason: null,
    last_verified_at: lastVerifiedAt,
    source_id: sourceId || null,
    source_type: sourceType || null,
    windows,
  };
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

function hasTimezoneDesignator(value: unknown): boolean {
  return /(?:Z|[+-]\d{2}:?\d{2})$/.test(str(value).trim());
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

function periodBounds(date: string, period: string): [Period, string | null, string] {
  const periodId: Period = ["today", "week", "month", "all"].includes(period) ? period as Period : "today";
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
