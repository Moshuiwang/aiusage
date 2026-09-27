/**
 * #183-b：`/ingest` 的 `account_observations` 落库到 `account_observations` 表。
 *
 * 关键行为：新指纹插入；同指纹重复观察时，`last_seen_at` 距上次落库不到 6 小时不重写
 * （控制写入频率——ingest 上报频率可能远高于每 6 小时一次，逐条重写这张小表没有增量信息，
 * 白白占用 D1 写入配额）；超过 6 小时才重写。
 */
import { describe, expect, it } from "vitest";
import { acquireWorker } from "./golden/harness";
import { fixedNow, timezone, token } from "./golden/paths";
import { accountObservationStatements } from "../src/write-model/statements";

const sourceId = "aobs-source";

function ingestPayload(observations: Array<Record<string, unknown>>, observedAt: string): Record<string, unknown> {
  return {
    schema_version: 1,
    source_id: sourceId,
    host: "aobs-host",
    os_user: "aobs-user",
    timezone,
    observed_at: observedAt,
    usage_daily: [],
    account_observations: observations,
  };
}

async function postIngest(mf: Awaited<ReturnType<typeof acquireWorker>>["mf"], payload: Record<string, unknown>): Promise<Response> {
  return mf.dispatchFetch("http://native.test/ingest", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function readRow(db: D1Database): Promise<{ first_seen_at: string; last_seen_at: string } | null> {
  return db.prepare(
    "SELECT first_seen_at, last_seen_at FROM account_observations WHERE source_id = ? AND provider = ? AND account_fingerprint = ?",
  ).bind(sourceId, "claude", "fp:claude:35f06f61d06d4aa38b8a3b94").first<{ first_seen_at: string; last_seen_at: string }>();
}

describe("account_observations upsert", () => {
  it("首次观察插入一行，first_seen_at 与 last_seen_at 等于观察时刻", async () => {
    const { mf, db } = await acquireWorker({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: timezone });
    const t0 = "2026-06-05T00:00:00+08:00";
    const response = await postIngest(mf, ingestPayload(
      [{ agent: "claude", provider: "claude", account_fingerprint: "fp:claude:35f06f61d06d4aa38b8a3b94", observed_at: t0 }],
      t0,
    ));
    expect(response.status).toBe(200);
    const row = await readRow(db);
    expect(row).not.toBeNull();
    expect(row?.first_seen_at).toBe(t0);
    expect(row?.last_seen_at).toBe(t0);
  });

  it("6 小时内的重复观察不重写 last_seen_at（黑盒：走真实 /ingest，核实 last_seen_at 未变）", async () => {
    const { mf, db } = await acquireWorker({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: timezone });
    const t0 = "2026-06-05T00:00:00+08:00";
    const t1 = "2026-06-05T05:00:00+08:00"; // 5 小时后，< 6 小时门槛
    await postIngest(mf, ingestPayload(
      [{ agent: "claude", provider: "claude", account_fingerprint: "fp:claude:35f06f61d06d4aa38b8a3b94", observed_at: t0 }],
      t0,
    ));
    expect((await readRow(db))?.last_seen_at).toBe(t0);

    const secondResponse = await postIngest(mf, ingestPayload(
      [{ agent: "claude", provider: "claude", account_fingerprint: "fp:claude:35f06f61d06d4aa38b8a3b94", observed_at: t1 }],
      t1,
    ));
    expect(secondResponse.status).toBe(200);
    const row = await readRow(db);
    expect(row?.last_seen_at).toBe(t0); // 没被 t1 覆盖
    expect(row?.first_seen_at).toBe(t0);
  });

  it("超过 6 小时的观察会重写 last_seen_at（不是永远不更新，只是节流；黑盒 /ingest）", async () => {
    const { mf, db } = await acquireWorker({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: timezone });
    const t0 = "2026-06-05T00:00:00+08:00";
    const t1 = "2026-06-05T06:01:00+08:00"; // 6 小时零 1 分钟后，超过门槛
    await postIngest(mf, ingestPayload(
      [{ agent: "claude", provider: "claude", account_fingerprint: "fp:claude:35f06f61d06d4aa38b8a3b94", observed_at: t0 }],
      t0,
    ));
    await postIngest(mf, ingestPayload(
      [{ agent: "claude", provider: "claude", account_fingerprint: "fp:claude:35f06f61d06d4aa38b8a3b94", observed_at: t1 }],
      t1,
    ));
    const row = await readRow(db);
    expect(row?.last_seen_at).toBe(t1);
    expect(row?.first_seen_at).toBe(t0); // first_seen_at 不随更新变化
  });

  it("单元级：用 D1 meta.changes 直接核实 6 小时内的第二条 upsert 语句真的 0 行变化", async () => {
    // 上面两条黑盒测试从"这张表的值有没有变"验证行为；这条从 D1 batch 的 meta.changes
    // 独立核实"没写"这个结论本身——不依赖 handlers.ts 的其它写语句，隔离得更干净。
    const { db } = await acquireWorker({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: timezone });
    const t0 = "2026-06-05T00:00:00+08:00";
    const t1 = "2026-06-05T05:00:00+08:00";
    const obs = { agent: "claude", provider: "claude", account_fingerprint: "fp:claude:35f06f61d06d4aa38b8a3b94" };
    const [firstResult] = await db.batch(accountObservationStatements(db, sourceId, [{ ...obs, observed_at: t0 }]));
    expect(Number(firstResult.meta?.changes ?? 0)).toBe(1);
    const [secondResult] = await db.batch(accountObservationStatements(db, sourceId, [{ ...obs, observed_at: t1 }]));
    expect(Number(secondResult.meta?.changes ?? 0)).toBe(0);
  });

  it("同一来源同一时刻观察到两个不同 provider，各自独立插入一行", async () => {
    const { mf, db } = await acquireWorker({ AIUSAGE_NOW: fixedNow, AIUSAGE_TIMEZONE: timezone });
    const t0 = "2026-06-05T00:00:00+08:00";
    await postIngest(mf, ingestPayload(
      [
        { agent: "claude", provider: "claude", account_fingerprint: "fp:claude:35f06f61d06d4aa38b8a3b94", observed_at: t0 },
        { agent: "codex", provider: "codex", account_fingerprint: "fp:codex:ad5d4ce6324ab7e5a0909ba8", observed_at: t0 },
      ],
      t0,
    ));
    const rows = await db.prepare("SELECT provider FROM account_observations WHERE source_id = ? ORDER BY provider")
      .bind(sourceId).all<{ provider: string }>();
    expect(rows.results.map((r) => r.provider)).toEqual(["claude", "codex"]);
  });
});
