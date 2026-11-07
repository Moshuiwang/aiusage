/**
 * #287：额度与用量按「账户」分格。
 *
 * 用户有多个 Claude / OpenAI 账户，套餐也会变；固定「每个 provider 一格」会把不同账户的
 * 百分比互相顶掉（实测：Tony 账户的额度从未出现）。这里把格子的键从 provider 换成账户：
 *
 * - 账户身份来自 account_observations（来源 → 指纹，额度侧与用量侧同表）与
 *   account_profiles（展示名 + 套餐时间段）。
 * - 同一账户被多台机器读到时合成一格，组内选来源的规则与 provider 口径完全一致
 *   （buildLimitStatusBy），不跨账户混合百分比。
 * - 读不到任何账户身份的 provider（目前是 Antigravity）退回一个 provider 级格子。
 * - 有账户身份的 provider 下，归属不了账户的用量单独计数（coverage），不猜归属。
 * - 超过 7 天没有新读数、本期也没有用量的来源不出格（停用的旧机器）。
 */
import { buildLimitStatusBy } from "./limits-select";
import { providerQuotaSlot, providerUsageSlot, slotProviderKey, usageProviderKey } from "./provider-slots";
import { int, parseDate, slotProviders, str } from "./shared";
import type { LimitRow, ProviderUsageTotals } from "./shared";

const ACCOUNT_SLOT_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;

type ObservationRow = {
  source_id: unknown; provider: unknown; account_fingerprint: unknown; first_seen_at: unknown; last_seen_at: unknown;
};
type ProfileRow = {
  provider: unknown; account_fingerprint: unknown; plan: unknown; label: unknown; first_seen_at: unknown; last_seen_at: unknown;
};

type AccountProfileView = {
  label: string | null;
  plan: string | null;
  plan_since: string | null;
  previous_plan: string | null;
};

type AccountDirectory = {
  accountFor(provider: string, sourceId: string): string | null;
  profileOf(fingerprint: string): AccountProfileView;
};

function time(value: unknown): number {
  return parseDate(str(value))?.getTime() ?? Number.NEGATIVE_INFINITY;
}

function knownPlan(value: unknown): string | null {
  const plan = str(value);
  return plan && plan !== "unknown" ? plan : null;
}

function accountDirectoryFrom(observations: ObservationRow[], profiles: ProfileRow[]): AccountDirectory {
  // 来源 → 最近一次观测到的账户。用 max(first_seen, last_seen) 比较：来源换了账户时，
  // 新指纹行的 first_seen 就是换账户的时刻，不必等旧行的 6 小时节流窗口过去。
  const latestBySource = new Map<string, { fingerprint: string; seen: number }>();
  for (const row of observations) {
    const key = `${slotProviderKey(row.provider)}\u0000${str(row.source_id)}`;
    const seen = Math.max(time(row.first_seen_at), time(row.last_seen_at));
    const existing = latestBySource.get(key);
    if (!existing || seen > existing.seen) latestBySource.set(key, { fingerprint: str(row.account_fingerprint), seen });
  }
  const byAccount = new Map<string, ProfileRow[]>();
  for (const row of profiles) {
    const fingerprint = str(row.account_fingerprint);
    byAccount.set(fingerprint, [...(byAccount.get(fingerprint) ?? []), row]);
  }
  const views = new Map<string, AccountProfileView>();
  for (const [fingerprint, rows] of byAccount) {
    const ordered = [...rows].sort((left, right) => time(left.first_seen_at) - time(right.first_seen_at));
    const current = [...rows].sort((left, right) =>
      Math.max(time(right.first_seen_at), time(right.last_seen_at)) - Math.max(time(left.first_seen_at), time(left.last_seen_at)))[0];
    const earlier = ordered.filter((row) => time(row.first_seen_at) < time(current.first_seen_at) && knownPlan(row.plan) && knownPlan(row.plan) !== knownPlan(current.plan));
    const previous = earlier.length ? earlier[earlier.length - 1] : null;
    const labelRow = [...rows].filter((row) => str(row.label))
      .sort((left, right) => time(right.last_seen_at) - time(left.last_seen_at))[0];
    views.set(fingerprint, {
      label: labelRow ? str(labelRow.label) : null,
      plan: knownPlan(current.plan),
      plan_since: previous ? str(current.first_seen_at) : null,
      previous_plan: previous ? knownPlan(previous.plan) : null,
    });
  }
  return {
    accountFor: (provider, sourceId) => latestBySource.get(`${slotProviderKey(provider)}\u0000${sourceId}`)?.fingerprint ?? null,
    profileOf: (fingerprint) => views.get(fingerprint) ?? { label: null, plan: null, plan_since: null, previous_plan: null },
  };
}

type SlotDraft = {
  key: string;
  provider: string;
  fingerprint: string | null;
  providerLevel: boolean;
  limits: LimitRow[];
  usage: ProviderUsageTotals | undefined;
  sourceIds: Set<string>;
};

function buildAccountSlots(
  limits: LimitRow[],
  usageRows: Record<string, unknown>[],
  directory: AccountDirectory,
  refTime: Date,
): { slots: Record<string, unknown>[]; coverage: Record<string, { unattributed_tokens: number }> } {
  const limitAccount = (limit: LimitRow) => directory.accountFor(limit.provider, limit.source_id);
  const usageProvider = (row: Record<string, unknown>) => {
    const fromProvider = slotProviderKey(row.ai_provider);
    return fromProvider && fromProvider !== "unknown" ? fromProvider : usageProviderKey(row.agent);
  };

  // 有任何账户身份的 provider 按账户分格；完全没有身份的 provider 退回 provider 级格子。
  const identified = new Set<string>();
  for (const limit of limits) if (limitAccount(limit)) identified.add(slotProviderKey(limit.provider));
  for (const row of usageRows) {
    const provider = usageProvider(row);
    if (provider && directory.accountFor(provider, str(row.source_id))) identified.add(provider);
  }

  const drafts = new Map<string, SlotDraft>();
  const draftFor = (provider: string, fingerprint: string | null, sourceId: string): SlotDraft => {
    const providerLevel = !identified.has(provider);
    const key = providerLevel ? provider : (fingerprint ? `${provider}:${fingerprint}` : `${provider}:source:${sourceId}`);
    let draft = drafts.get(key);
    if (!draft) {
      draft = { key, provider, fingerprint: providerLevel ? null : fingerprint, providerLevel, limits: [], usage: undefined, sourceIds: new Set() };
      drafts.set(key, draft);
    }
    return draft;
  };

  const slotKeyOfLimit = new Map<LimitRow, string>();
  for (const limit of limits) {
    const provider = slotProviderKey(limit.provider);
    const draft = draftFor(provider, limitAccount(limit), limit.source_id);
    draft.limits.push(limit);
    draft.sourceIds.add(limit.source_id);
    slotKeyOfLimit.set(limit, draft.key);
  }

  const coverage: Record<string, { unattributed_tokens: number }> = {};
  for (const row of usageRows) {
    const provider = usageProvider(row);
    if (!provider) continue;
    const sourceId = str(row.source_id);
    const fingerprint = directory.accountFor(provider, sourceId);
    if (identified.has(provider) && !fingerprint) {
      coverage[provider] = { unattributed_tokens: (coverage[provider]?.unattributed_tokens ?? 0) + int(row.total_tokens) };
      continue;
    }
    const draft = draftFor(provider, fingerprint, sourceId);
    draft.sourceIds.add(sourceId);
    const totals = draft.usage ?? { total_tokens: 0, input_tokens: 0, output_tokens: 0, cache_tokens: 0 };
    totals.total_tokens += int(row.total_tokens);
    totals.input_tokens += int(row.input_tokens);
    totals.output_tokens += int(row.output_tokens);
    totals.cache_tokens += int(row.cache_creation_tokens) + int(row.cache_read_tokens);
    draft.usage = totals;
  }

  const statusBySlot = new Map<string, Record<string, unknown>>();
  for (const row of buildLimitStatusBy(limits, refTime, (limit) => slotKeyOfLimit.get(limit) ?? "")) {
    statusBySlot.set(row.slot_key, row);
  }

  const retained = [...drafts.values()].filter((draft) => {
    if ((draft.usage?.total_tokens ?? 0) > 0) return true;
    const newest = Math.max(...draft.limits.map((limit) => time(limit.observed_at)));
    return refTime.getTime() - newest <= ACCOUNT_SLOT_RETENTION_MS;
  });

  const slots = retained.map((draft) => {
    const profile = draft.fingerprint ? directory.profileOf(draft.fingerprint) : null;
    const status = statusBySlot.get(draft.key);
    const { slot_key: _slotKey, ...statusRow } = status ?? { slot_key: "" };
    return {
      provider: draft.provider,
      account: draft.providerLevel ? null : {
        key: draft.key,
        fingerprint: draft.fingerprint,
        label: profile?.label ?? null,
        plan: profile?.plan ?? null,
        plan_since: profile?.plan_since ?? null,
        previous_plan: profile?.previous_plan ?? null,
        source_ids: [...draft.sourceIds].sort(),
      },
      usage: providerUsageSlot(draft.usage),
      quota: providerQuotaSlot(draft.limits, status ? statusRow : undefined, refTime),
    };
  });

  const providerOrder = (provider: string) => {
    const index = (slotProviders as readonly string[]).indexOf(provider);
    return index === -1 ? slotProviders.length : index;
  };
  for (const provider of slotProviders) {
    if (slots.some((slot) => slot.provider === provider)) continue;
    slots.push({ provider, account: null, usage: providerUsageSlot(undefined), quota: providerQuotaSlot([], undefined, refTime) });
  }
  slots.sort((left, right) =>
    providerOrder(left.provider) - providerOrder(right.provider)
    || (left.account?.label == null ? 1 : 0) - (right.account?.label == null ? 1 : 0)
    || str(left.account?.label).localeCompare(str(right.account?.label))
    || str(left.account?.key).localeCompare(str(right.account?.key)));
  return { slots, coverage };
}

export { accountDirectoryFrom, buildAccountSlots };
export type { AccountDirectory, ObservationRow, ProfileRow };
