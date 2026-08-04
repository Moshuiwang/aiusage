/** #126：/api/summary 编排（原 buildSummary 所在）。 */
import { buildMobileSummary } from "../mobile-summary";
import { buildVersionHealth } from "../version-contract";
import { accountHourlyRowsToDailyRows, accountHourlyRowsToHourlyRows, accountHourlySummary } from "./account-hourly";
import {
  all, factCostsByItem, fetchAccountHourlyRows, fetchAiAccounts, fetchFactRows,
  fetchHourlyModelRows, fetchLimitWindows, fetchSourceIdentities,
} from "./db";
import { buildLimitStatus, effectiveLimitWindow } from "./limits-select";
import { accumulateProviderUsage, buildProviderSlots, buildProviderUsageCoverage, providerTokensByItem } from "./provider-slots";
import { buildSourceStatus } from "./source-status";
import { capTodayHourlyToPeriodTotals, codexHourlyContext, fillTodayHourlyResidual, hourlyTrend } from "./trend";
import {
  accountHourlyRowMatchesFilter, dateAxis, formatDate, hourAxis, identityMatchesFilter, int,
  itemKey, localDateFromWindowStart, metadataFromStr, nowInTimezone, periodBounds, str, toOffsetIso,
} from "./shared";
import type { LimitRow, ProviderUsageTotals, SummaryRequest, SummarySnapshot } from "./shared";
import type { MobileSummary } from "../mobile-summary";

/** 阶段 1：读取 D1 输入与时间/周期边界。所有 SELECT 都发生在这里或 db.ts。 */
async function loadSummaryInputs(db: D1Database, request: SummaryRequest) {
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
  return {
    refTime, periodId, startDate, endDate, hourAxisValues, identities,
    statusRows, accuracyRows, limits, allLimits, accountHourlyRows, aiAccounts,
  };
}

type SummaryInputs = Awaited<ReturnType<typeof loadSummaryInputs>>;

/** 阶段 2：过滤与投影——把账户小时行派生成日行/时行/模型分解等视图输入。 */
async function deriveUsageRows(db: D1Database, request: SummaryRequest, inputs: SummaryInputs) {
  const { periodId, startDate, endDate, accountHourlyRows } = inputs;
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
  return { filteredAccountHourlyRows, canonicalProviderTokens, rows, hourlyRows, accountHourly, modelsByItem };
}

type DerivedRows = Awaited<ReturnType<typeof deriveUsageRows>>;

/** 阶段 3：单遍聚合——items、总量、机器/账户/agent 分组与趋势累计器一次填齐。 */
function aggregateUsage(request: SummaryRequest, inputs: SummaryInputs, derived: DerivedRows) {
  const { startDate, endDate, identities } = inputs;
  const { rows, canonicalProviderTokens, modelsByItem } = derived;
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

  return {
    items, totalTokens, inputTokens, outputTokens, cacheCreationTokens, cacheReadTokens,
    byMachine, byAccount, byAgent, providerUsage, agentTotals,
    trendDates, trendByAgent, trendByTokenType, trendPoints,
  };
}

type UsageAggregates = ReturnType<typeof aggregateUsage>;

/** 阶段 4：趋势区块——today 走小时轴（残差回填 + 守恒封顶），其余周期走日轴。 */
function buildTrendSection(inputs: SummaryInputs, derived: DerivedRows, aggregates: UsageAggregates) {
  const { periodId, startDate, endDate, hourAxisValues, refTime } = inputs;
  const { rows, hourlyRows } = derived;
  const {
    totalTokens, inputTokens, outputTokens, cacheCreationTokens, cacheReadTokens,
    agentTotals, trendDates, trendByAgent, trendByTokenType, trendPoints,
  } = aggregates;
  const codexContext = codexHourlyContext(rows, hourlyRows);
  let trend: Record<string, unknown>;
  if (periodId === "today") {
    trend = hourlyTrend(hourAxisValues, hourlyRows);
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
  return { trend, codexContext };
}

/** 阶段 5：装配快照。键位顺序与拆分前逐字一致，不得调整。 */
function assembleSnapshot(
  request: SummaryRequest,
  inputs: SummaryInputs,
  derived: DerivedRows,
  aggregates: UsageAggregates,
  trendSection: ReturnType<typeof buildTrendSection>,
): SummarySnapshot {
  const { refTime, periodId, startDate, endDate, statusRows, accuracyRows, identities, limits, allLimits, aiAccounts } = inputs;
  const { accountHourly } = derived;
  const {
    items, totalTokens, inputTokens, outputTokens, cacheCreationTokens, cacheReadTokens,
    byMachine, byAccount, byAgent, providerUsage,
  } = aggregates;
  const { trend, codexContext } = trendSection;
  const limitStatus = buildLimitStatus(allLimits, refTime);
  const sourceStatus = buildSourceStatus(
    statusRows, accuracyRows, identities, refTime, request.machine, request.account,
  );
  const snapshot: SummarySnapshot = {
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
  if (request.machine) snapshot.summary.machine = request.machine;
  if (request.account) snapshot.summary.account = request.account;
  return snapshot;
}

export async function buildSummary(db: D1Database, request: SummaryRequest): Promise<SummarySnapshot> {
  const inputs = await loadSummaryInputs(db, request);
  const derived = await deriveUsageRows(db, request, inputs);
  const aggregates = aggregateUsage(request, inputs, derived);
  const trendSection = buildTrendSection(inputs, derived, aggregates);
  return assembleSnapshot(request, inputs, derived, aggregates, trendSection);
}

export async function buildMobile(db: D1Database, request: SummaryRequest): Promise<MobileSummary> {
  return buildMobileSummary(await buildSummary(db, request));
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

export {
  normalizedBackendMode,
  summaryMetadata,
};
