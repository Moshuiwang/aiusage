/**
 * #287：额度与用量按「账户」分格（取代每个 provider 固定一格）。
 *
 * 场景都对应 2026-11-07 实测事实：Claude 有 Zhipeng（Max 5x）与 Tony（Max 20x）两个账户，
 * OpenAI 账户同时被 Mac 与 TZ 读到；Antigravity 没有可读的账户身份。
 */
import { describe, expect, it } from "vitest";
import { accountDirectoryFrom, buildAccountSlots } from "../src/read-model/account-slots";
import type { LimitRow } from "../src/read-model/shared";

const now = new Date("2026-11-07T12:00:00Z");
const fpZ = "fp:claude:aaaaaaaaaaaaaaaaaaaaaaaa";
const fpT = "fp:claude:bbbbbbbbbbbbbbbbbbbbbbbb";
const fpO = "fp:codex:cccccccccccccccccccccccc";

function limit(source: string, provider: string, changes: Partial<LimitRow> = {}): LimitRow {
  return {
    source_id: source, provider, window: "week", used_percent: 40, remaining_percent: 60,
    reset_at: "2026-11-10T00:00:00Z", window_duration_minutes: 10080,
    observed_at: "2026-11-07T11:30:00Z", source_type: "official_cli", confidence: "observed",
    status: "ok", official: true, ...changes,
  };
}

function usage(source: string, provider: string, total: number): Record<string, unknown> {
  return {
    source_id: source, ai_provider: provider, agent: provider, total_tokens: total,
    input_tokens: total, output_tokens: 0, cache_creation_tokens: 0, cache_read_tokens: 0,
    window_start: "2026-11-07T10:00:00Z",
  };
}

const observations = [
  { source_id: "tz-wangzp", provider: "claude", account_fingerprint: fpZ, first_seen_at: "2026-11-01T00:00:00Z", last_seen_at: "2026-11-07T11:00:00Z" },
  { source_id: "tz-wangzhipeng-limits", provider: "claude", account_fingerprint: fpT, first_seen_at: "2026-11-01T00:00:00Z", last_seen_at: "2026-11-07T11:00:00Z" },
  { source_id: "tz-wangzhipeng", provider: "claude", account_fingerprint: fpT, first_seen_at: "2026-11-01T00:00:00Z", last_seen_at: "2026-11-07T11:00:00Z" },
  { source_id: "codex-main", provider: "codex", account_fingerprint: fpO, first_seen_at: "2026-11-01T00:00:00Z", last_seen_at: "2026-11-07T11:00:00Z" },
  { source_id: "tz-wangzp-codex", provider: "codex", account_fingerprint: fpO, first_seen_at: "2026-11-01T00:00:00Z", last_seen_at: "2026-11-07T11:00:00Z" },
];
const profiles = [
  { provider: "claude", account_fingerprint: fpZ, plan: "max_20x", label: "Zhipeng", first_seen_at: "2026-09-01T00:00:00Z", last_seen_at: "2026-10-20T00:00:00Z" },
  { provider: "claude", account_fingerprint: fpZ, plan: "max_5x", label: "Zhipeng", first_seen_at: "2026-10-21T00:00:00Z", last_seen_at: "2026-11-07T11:00:00Z" },
  { provider: "claude", account_fingerprint: fpT, plan: "max_20x", label: "Tony", first_seen_at: "2026-11-01T00:00:00Z", last_seen_at: "2026-11-07T11:00:00Z" },
  { provider: "codex", account_fingerprint: fpO, plan: "pro", label: "Em", first_seen_at: "2026-11-01T00:00:00Z", last_seen_at: "2026-11-07T11:00:00Z" },
];
const directory = accountDirectoryFrom(observations, profiles);

function slotOf(slots: Record<string, any>[], label: string | null, provider?: string) {
  const found = slots.filter((slot) => (slot.account?.label ?? null) === label && (!provider || slot.provider === provider));
  expect(found).toHaveLength(1);
  return found[0];
}

describe("按账户分格", () => {
  it("两个 Claude 账户各占一格，额度与套餐互不混合", () => {
    const { slots } = buildAccountSlots(
      [limit("tz-wangzp", "claude", { used_percent: 82, remaining_percent: 18 }),
        limit("tz-wangzhipeng-limits", "claude", { used_percent: 10, remaining_percent: 90 })],
      [], directory, now,
    );
    const zhipeng = slotOf(slots, "Zhipeng");
    const tony = slotOf(slots, "Tony");
    expect(zhipeng.account).toMatchObject({ fingerprint: fpZ, plan: "max_5x" });
    expect(tony.account).toMatchObject({ fingerprint: fpT, plan: "max_20x" });
    expect(zhipeng.quota.status).toBe("available");
    expect(zhipeng.quota.windows.map((w: LimitRow) => w.used_percent)).toEqual([82]);
    expect(tony.quota.windows.map((w: LimitRow) => w.used_percent)).toEqual([10]);
  });

  it("同一账户被两台机器读到合成一格，一台失败时用另一台的可信读数", () => {
    const { slots } = buildAccountSlots(
      [limit("tz-wangzp-codex", "codex", { status: "provider_failed", official: false, window: "unknown", observed_at: "2026-11-07T11:50:00Z" }),
        limit("codex-main", "codex", { used_percent: 55, remaining_percent: 45, source_type: "runtime_api" })],
      [], directory, now,
    );
    const codexSlots = slots.filter((slot) => slot.provider === "codex");
    expect(codexSlots).toHaveLength(1);
    expect(codexSlots[0].account.source_ids).toEqual(["codex-main", "tz-wangzp-codex"]);
    expect(codexSlots[0].quota).toMatchObject({ status: "available", source_id: "codex-main" });
    expect(codexSlots[0].quota.windows.map((w: LimitRow) => w.used_percent)).toEqual([55]);
  });

  it("套餐变化：当前套餐、变化时刻与上一个套餐", () => {
    const { slots } = buildAccountSlots([limit("tz-wangzp", "claude"), limit("tz-wangzhipeng-limits", "claude")], [], directory, now);
    expect(slotOf(slots, "Zhipeng").account).toMatchObject({
      plan: "max_5x", plan_since: "2026-10-21T00:00:00Z", previous_plan: "max_20x",
    });
    expect(slotOf(slots, "Tony").account).toMatchObject({ plan: "max_20x", plan_since: null, previous_plan: null });
  });

  it("用量按来源→账户归属；归属不了的单独计数，不塞进任何账户", () => {
    const { slots, coverage } = buildAccountSlots(
      [limit("tz-wangzp", "claude"), limit("tz-wangzhipeng-limits", "claude")],
      [usage("tz-wangzp", "claude", 100), usage("tz-wangzhipeng", "claude", 30), usage("mac-local", "claude", 7)],
      directory, now,
    );
    expect(slotOf(slots, "Zhipeng").usage.total_tokens).toBe(100);
    expect(slotOf(slots, "Tony").usage.total_tokens).toBe(30);
    expect(coverage).toEqual({ claude: { unattributed_tokens: 7 } });
    const allSlotTokens = slots.reduce((sum, slot) => sum + slot.usage.total_tokens, 0);
    expect(allSlotTokens + 7).toBe(137); // 守恒：分格合计 + 未归属 = 输入总量
  });

  it("读不到账户身份的 provider（Antigravity）保留一个 provider 级格子，含全部用量", () => {
    const { slots, coverage } = buildAccountSlots(
      [limit("antigravity-mac", "antigravity", { source_type: "language_server" })],
      [usage("mac-local", "antigravity", 9)],
      directory, now,
    );
    const slot = slotOf(slots, null, "antigravity");
    expect(slot.account).toBeNull();
    expect(slot.usage.total_tokens).toBe(9);
    expect(slot.quota.status).toBe("available");
    expect(coverage.antigravity).toBeUndefined();
  });

  it("超过 7 天无新读数且本期无用量的旧来源不出格；没有任何数据的 provider 给一个缺失占位", () => {
    const { slots } = buildAccountSlots(
      [limit("claude-main", "claude", { observed_at: "2026-08-02T04:00:00Z", reset_at: "2026-08-05T00:00:00Z" }),
        limit("tz-wangzp", "claude")],
      [], directory, now,
    );
    expect(slots.filter((slot) => slot.provider === "claude").map((slot) => slot.account?.label ?? null)).toEqual(["Zhipeng"]);
    const codex = slots.filter((slot) => slot.provider === "codex");
    expect(codex).toEqual([expect.objectContaining({ account: null, quota: expect.objectContaining({ status: "missing", reason: "no_data" }) })]);
  });

  it("排序：provider 固定顺序，同 provider 按账户名", () => {
    const { slots } = buildAccountSlots(
      [limit("codex-main", "codex"), limit("tz-wangzhipeng-limits", "claude"), limit("tz-wangzp", "claude"),
        limit("antigravity-mac", "antigravity")],
      [], directory, now,
    );
    expect(slots.map((slot) => [slot.provider, slot.account?.label ?? null])).toEqual([
      ["claude", "Tony"], ["claude", "Zhipeng"], ["codex", "Em"], ["antigravity", null],
    ]);
  });
});

describe("账户目录", () => {
  it("来源对应最近一次观测到的账户（来源切换账户后立刻生效）", () => {
    const dir = accountDirectoryFrom([
      { source_id: "s", provider: "claude", account_fingerprint: fpZ, first_seen_at: "2026-11-01T00:00:00Z", last_seen_at: "2026-11-06T00:00:00Z" },
      { source_id: "s", provider: "claude", account_fingerprint: fpT, first_seen_at: "2026-11-07T01:00:00Z", last_seen_at: "2026-11-07T01:00:00Z" },
    ], []);
    expect(dir.accountFor("claude", "s")).toBe(fpT);
    expect(dir.accountFor("claude", "unknown")).toBeNull();
  });
});
