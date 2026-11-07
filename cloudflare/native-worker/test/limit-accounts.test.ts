/**
 * #287：`/ingest-limits` 的 window.account（采集端自动识别的账户资料）落库。
 *
 * - 额度来源 -> 账户：写 account_observations（与用量侧同一张表、同一套 6 小时节流）。
 * - 账户资料：account_profiles 每个 (账户, 套餐) 一行；套餐变化 = 新增一行。
 * - account 字段不合规只丢弃账户部分，额度窗口本身照常写入（附加字段不能拖垮主数据）。
 */
import { describe, expect, it } from "vitest";
import { acquireWorker } from "./golden/harness";
import { fixedNow, timezone, token } from "./golden/paths";

const fpA = "fp:claude:35f06f61d06d4aa38b8a3b94";

function window(observedAt: string, account?: unknown): Record<string, unknown> {
  return {
    source_id: "tz-wangzp",
    provider: "claude",
    window: "week",
    used_percent: 77,
    remaining_percent: 23,
    reset_at: "2026-06-12T00:00:00+08:00",
    window_duration_minutes: 10080,
    observed_at: observedAt,
    source_type: "official_cli",
    confidence: "observed",
    status: "ok",
    ...(account === undefined ? {} : { account }),
  };
}

async function post(mf: Awaited<ReturnType<typeof acquireWorker>>["mf"], observedAt: string, windows: unknown[]): Promise<Response> {
  return mf.dispatchFetch("http://native.test/ingest-limits", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify({ schema_version: 1, observed_at: observedAt, timezone, windows }),
  });
}

async function rows(db: D1Database) {
  const observations = (await db.prepare(
    "SELECT source_id, provider, account_fingerprint, first_seen_at, last_seen_at FROM account_observations ORDER BY first_seen_at",
  ).all()).results;
  const profiles = (await db.prepare(
    "SELECT provider, account_fingerprint, plan, label, first_seen_at, last_seen_at FROM account_profiles ORDER BY first_seen_at",
  ).all()).results;
  const limitCount = (await db.prepare("SELECT COUNT(*) AS c FROM limit_windows").first<{ c: number }>())?.c;
  return { observations, profiles, limitCount };
}

describe("额度上报的账户资料", () => {
  it("写入来源→账户对应和账户资料，且额度窗口照常写入", async () => {
    const { mf, db } = await acquireWorker({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: timezone });
    const t0 = "2026-06-05T00:00:00+08:00";
    const response = await post(mf, t0, [window(t0, { fingerprint: fpA, label: "Zhipeng", plan: "max_5x" })]);
    expect(response.status).toBe(200);
    const { observations, profiles, limitCount } = await rows(db);
    expect(limitCount).toBe(1);
    expect(observations).toEqual([
      { source_id: "tz-wangzp", provider: "claude", account_fingerprint: fpA, first_seen_at: t0, last_seen_at: t0 },
    ]);
    expect(profiles).toEqual([
      { provider: "claude", account_fingerprint: fpA, plan: "max_5x", label: "Zhipeng", first_seen_at: t0, last_seen_at: t0 },
    ]);
  });

  it("同一批多个窗口属于同一账户时只写一次（不按窗口数放大写入）", async () => {
    const { mf, db } = await acquireWorker({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: timezone });
    const t0 = "2026-06-05T00:00:00+08:00";
    const account = { fingerprint: fpA, label: "Zhipeng", plan: "max_5x" };
    const session = { ...window(t0, account), window: "session", window_duration_minutes: 300, reset_at: "2026-06-05T04:00:00+08:00" };
    expect((await post(mf, t0, [window(t0, account), session])).status).toBe(200);
    const { observations, profiles, limitCount } = await rows(db);
    expect(limitCount).toBe(2);
    expect(observations).toHaveLength(1);
    expect(profiles).toHaveLength(1);
  });

  it("套餐变化新增一行，旧套餐的时间段保留", async () => {
    const { mf, db } = await acquireWorker({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: timezone });
    const t0 = "2026-06-01T00:00:00+08:00";
    const t1 = "2026-06-05T00:00:00+08:00";
    await post(mf, t0, [window(t0, { fingerprint: fpA, label: "Zhipeng", plan: "max_20x" })]);
    await post(mf, t1, [window(t1, { fingerprint: fpA, label: "Zhipeng", plan: "max_5x" })]);
    const { profiles } = await rows(db);
    expect(profiles.map((row) => [row.plan, row.first_seen_at])).toEqual([["max_20x", t0], ["max_5x", t1]]);
  });

  it("6 小时内重复观察同一套餐不重写，超过 6 小时才更新 last_seen_at", async () => {
    const { mf, db } = await acquireWorker({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: timezone });
    const account = { fingerprint: fpA, label: "Zhipeng", plan: "max_5x" };
    const t0 = "2026-06-05T00:00:00+08:00";
    const t1 = "2026-06-05T05:00:00+08:00";
    const t2 = "2026-06-05T06:30:00+08:00";
    await post(mf, t0, [window(t0, account)]);
    await post(mf, t1, [window(t1, account)]);
    expect((await rows(db)).profiles[0].last_seen_at).toBe(t0);
    await post(mf, t2, [window(t2, account)]);
    expect((await rows(db)).profiles[0].last_seen_at).toBe(t2);
  });

  it.each([
    ["指纹格式不对", { fingerprint: "fp:claude:nothex", plan: "max_5x" }],
    ["指纹 provider 与窗口不符", { fingerprint: "fp:codex:35f06f61d06d4aa38b8a3b94", plan: "pro" }],
    ["account 不是对象", "fp:claude:35f06f61d06d4aa38b8a3b94"],
  ])("%s：丢弃账户部分，额度照常写入", async (_name, account) => {
    const { mf, db } = await acquireWorker({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: timezone });
    const t0 = "2026-06-05T00:00:00+08:00";
    expect((await post(mf, t0, [window(t0, account)])).status).toBe(200);
    const { observations, profiles, limitCount } = await rows(db);
    expect(limitCount).toBe(1);
    expect(observations).toEqual([]);
    expect(profiles).toEqual([]);
  });

  it("展示名像邮箱只丢展示名、套餐不合规只记 unknown，账户归属照常保留", async () => {
    const { mf, db } = await acquireWorker({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: timezone });
    const t0 = "2026-06-05T00:00:00+08:00";
    await post(mf, t0, [window(t0, { fingerprint: fpA, label: "someone@example.com", plan: "Max 5x; DROP" })]);
    const { observations, profiles } = await rows(db);
    expect(observations).toHaveLength(1);
    expect(profiles).toEqual([
      { provider: "claude", account_fingerprint: fpA, plan: "unknown", label: null, first_seen_at: t0, last_seen_at: t0 },
    ]);
    expect(JSON.stringify(profiles)).not.toContain("@");
  });

  it("没有 plan 时记为 unknown，不猜", async () => {
    const { mf, db } = await acquireWorker({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: timezone });
    const t0 = "2026-06-05T00:00:00+08:00";
    await post(mf, t0, [window(t0, { fingerprint: fpA })]);
    const { profiles } = await rows(db);
    expect(profiles).toEqual([
      { provider: "claude", account_fingerprint: fpA, plan: "unknown", label: null, first_seen_at: t0, last_seen_at: t0 },
    ]);
  });
});
