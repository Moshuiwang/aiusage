/** #126：today 小时趋势、残差回填与守恒封顶。 */
import {
  asArray, emptyTokenTotals, int, isCodexAgent, isRecord, metadataFromStr, str, sumTokenType, toOffsetIso,
} from "./shared";
import type { DailyRow, TimedRow } from "./shared";

function hourlyTrend(axis: string[], rows: TimedRow[]): Record<string, unknown> {
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
  for (const row of rows) {
    const hour = str(row.hour);
    if (!points.has(hour)) continue;
    addTimedPoint(axis, hour, row, byTokenType, points, agentTotals, byAgent);
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

export {
  addTimedPoint,
  capTodayHourlyToPeriodTotals,
  codexHourlyContext,
  fillTodayHourlyResidual,
  hourlyTrend,
  scaleAgentRows,
  scaleDownInts,
};
