/** #126：账户小时事实的汇总与日/时投影。 */
import { int, itemKey, localDateFromWindowStart, localHourFromWindowStart, str } from "./shared";
import type { DailyRow, TimedRow } from "./shared";

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

export {
  accountHourlyRowsToDailyRows,
  accountHourlyRowsToHourlyRows,
  accountHourlySummary,
  emptyAccountHourlySummary,
};
