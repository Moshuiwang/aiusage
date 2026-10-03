import { describe, expect, it } from "vitest";
import { buildLimitStatus } from "../src/read-model/limits-select";
import { providerQuotaSlot } from "../src/read-model/provider-slots";
import type { LimitRow } from "../src/read-model/shared";
import { collectProviderSlotsScenario } from "./golden/provider-slots-golden";

const now = new Date("2026-06-03T12:00:00+08:00");
function observation(source: string, at: string, changes: Partial<LimitRow> = {}): LimitRow {
  return { source_id: source, provider: "codex", window: "week", used_percent: 20,
    remaining_percent: 80, reset_at: "2026-06-10T05:13:05+08:00", window_duration_minutes: 10080,
    observed_at: at, source_type: "runtime_api", confidence: "observed", status: "ok",
    official: true, ...changes };
}
function failure(source: string, at: string): LimitRow {
  return observation(source, at, { window: "status", status: "provider_failed", official: false });
}

describe("官方额度只选择一个当前可信来源", () => {
  it.each([false, true])("另一来源较新失败不能遮住有效周窗口（逆序=%s）", (reverse) => {
    const rows = [observation("macmini", "2026-06-03T11:00:00+08:00"),
      failure("old-device", "2026-06-03T11:30:00+08:00")];
    const success = rows[0];
    if (reverse) rows.reverse();
    const status = buildLimitStatus(rows, now);
    expect(status).toHaveLength(1);
    expect(status[0]).toMatchObject({ source_id: "macmini", status: "ok" });
    const quota = providerQuotaSlot(rows, status[0], now);
    expect(quota).toMatchObject({ source_id: "macmini", status: "available",
      last_verified_at: "2026-06-03T11:00:00+08:00" });
    expect(quota.windows).toEqual([success]);
  });

  it("同来源失败晚于成功时不把旧窗口当作可用", () => {
    const rows = [observation("macmini", "2026-06-03T11:00:00+08:00"),
      failure("macmini", "2026-06-03T11:30:00+08:00")];
    const status = buildLimitStatus(rows, now);
    expect(status).toHaveLength(1);
    expect(status[0]).toMatchObject({ source_id: "macmini", status: "unavailable" });
    expect(providerQuotaSlot(rows, status[0], now)).toMatchObject({ status: "missing", windows: [] });
  });

  it("失败来源即便带着旧成功，也不压过另一可用账号或混合其百分比", () => {
    const rows = [observation("account-a", "2026-06-03T11:00:00+08:00"),
      observation("account-b", "2026-06-03T11:15:00+08:00", { used_percent: 80, remaining_percent: 20 }),
      failure("account-b", "2026-06-03T11:30:00+08:00")];
    const status = buildLimitStatus(rows, now);
    expect(status).toHaveLength(1);
    expect(status[0]).toMatchObject({ source_id: "account-a", status: "ok" });
    const quota = providerQuotaSlot(rows, status[0], now);
    expect(quota.windows).toEqual([rows[0]]);
    expect(quota.last_verified_at).toBe("2026-06-03T11:00:00+08:00");
  });

  it("两个可用账号继续择最新成功，只展示该来源窗口", () => {
    const rows = [observation("account-a", "2026-06-03T11:00:00+08:00"),
      observation("account-b", "2026-06-03T11:15:00+08:00", { used_percent: 80, remaining_percent: 20 })];
    const status = buildLimitStatus(rows, now);
    expect(status).toHaveLength(1);
    expect(status[0]).toMatchObject({ source_id: "account-b", status: "ok" });
    expect(providerQuotaSlot(rows, status[0], now).windows).toEqual([rows[1]]);
  });

  it("估算的新时间戳不能提升该来源的官方成功优先级", () => {
    const rows = [observation("account-a", "2026-06-03T11:00:00+08:00"),
      observation("account-b", "2026-06-03T11:15:00+08:00"),
      observation("account-a", "2026-06-03T11:30:00+08:00", { official: false, confidence: "estimated" })];
    expect(buildLimitStatus(rows, now)).toMatchObject([{ source_id: "account-b", status: "ok" }]);
  });

  it.each([
    { status: "ok", observed_at: "2026-06-01T11:00:00+08:00" },
    { reset_at: "2026-06-03T10:00:00+08:00" },
    { official: false, confidence: "estimated" },
    { confidence: "estimated" },
  ])("过期、已重置和估算窗口不能成为可用备选：%j", (changes) => {
    const rows = [observation("macmini", "2026-06-03T11:00:00+08:00", changes),
      failure("old-device", "2026-06-03T11:30:00+08:00")];
    const status = buildLimitStatus(rows, now);
    expect(status).toHaveLength(1);
    expect(status[0]).toMatchObject({ source_id: "old-device", status: "unavailable" });
    expect(providerQuotaSlot(rows, status[0], now)).toMatchObject({ status: "missing", windows: [] });
  });

  it("summary 和 mobile-summary 均输出一致的官方周来源、读数和重置时刻", async () => {
    const records = await collectProviderSlotsScenario("16-healthy-source-with-other-failure");
    expect(records).toHaveLength(2);
    expect(records.map((record) => record.name)).toEqual([
      "16-healthy-source-with-other-failure:summary",
      "16-healthy-source-with-other-failure:mobile-summary",
    ]);
    for (const record of records) {
      const slots = record.provider_slots as Array<{ provider: string; quota: Record<string, any> }>;
      expect(slots).toHaveLength(3);
      const quota = slots.find((slot) => slot.provider === "codex")!.quota;
      expect(quota).toMatchObject({ status: "available", source_id: "codex-macmini",
        source_type: "runtime_api", last_verified_at: "2026-06-03T11:00:00+08:00" });
      expect(quota.windows).toHaveLength(1);
      expect(quota.windows[0]).toMatchObject({ source_id: "codex-macmini", official: true,
        confidence: "observed", status: "ok", used_percent: 20, remaining_percent: 80,
        window: "week", window_duration_minutes: 10080, reset_at: "2026-06-10T05:13:05+08:00" });
    }
  }, 60_000);
});
