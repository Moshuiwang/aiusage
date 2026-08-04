/** #126：provider 固定槽位（用量+额度）与归属覆盖度。 */
import { effectiveLimitWindow, lastVerifiedAtOf, limitWindowExpired, limitWindowStale } from "./limits-select";
import { aggregateAgentNames, int, itemKey, localDateFromWindowStart, slotProviders, str } from "./shared";
import type { LimitRow, ProviderUsageTotals } from "./shared";

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

export {
  accumulateProviderUsage,
  addProviderUsage,
  buildProviderSlots,
  buildProviderUsageCoverage,
  providerQuotaSlot,
  providerTokensByItem,
  providerUsageSlot,
  slotProviderKey,
  usageProviderKey,
};
