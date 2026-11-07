/**
 * D1 写入预算守卫（Cloudflare Free：每天 10 万行写入，索引重写也计数）。
 *
 * 2026-11-07 线上 7 天明细：usage_hourly_facts 的 upsert 平均每次写 7.5 行——DO UPDATE SET
 * 把冲突键列（全部带索引）也重新赋值，SQLite 会重写每个涉及的索引，哪怕值没变。
 * 这里用本地 D1 的 meta.rows_written（与线上同口径，含索引）直接度量单条语句的成本。
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { acquireWorker } from "./golden/harness";
import { repoRoot } from "./golden/paths";
import { normalizeFacts } from "../src/write-model/normalize";
import { factRevisionStatement, hourlyFactStatements } from "../src/write-model/statements";
import { localDayRollupStatements } from "../src/write-model/handlers";
import { validateIngestPayload } from "../src/write-model/validate";
import type { UsageHourlyFact } from "../src/write-model/shared";

//: token 变化的一次更新：修订记录 1 行 + fact 表行与 PK、machine_user 两个索引 3 行。
//: 优化前实测 10 行（fact 单条 9 行）。
const UPDATE_BUDGET = 4;

function fixtureFact(): UsageHourlyFact {
  const records = JSON.parse(readFileSync(path.join(repoRoot, "cloudflare/native-worker/test/collector_payload_fixture.json"), "utf8"));
  // fixture 为确定性把顶层 observed_at 抹成 "<masked>"（同 ingest.test.ts），这里填回合法时刻。
  const facts = normalizeFacts(validateIngestPayload({ ...records[0].payload, observed_at: "2026-06-04T10:05:00+08:00" }));
  expect(facts.length).toBeGreaterThan(0); // 结构下限：确实拿到了真实采集端产出的 fact
  return facts[0];
}

async function write(db: D1Database, fact: UsageHourlyFact, seen: string) {
  // 与 handleIngestWrite 同序：先修订记录，再明细写入组。
  const results = await db.batch([factRevisionStatement(db, fact, seen), ...hourlyFactStatements(db, fact, seen)]);
  return results.reduce((sum, r) => sum + Number(r.meta.rows_written ?? 0), 0);
}

describe("一条用量明细（真实写入组）的写入成本", () => {
  it("只有 token 变化的更新不重写冲突键索引", async () => {
    const { db } = await acquireWorker({});
    const fact = fixtureFact();
    const seen = "2026-06-03T12:00:00+08:00";
    const inserted = await write(db, fact, seen);
    expect(inserted).toBeGreaterThan(8); // 新行写全部索引：证明度量含索引
    const updated = await write(db, { ...fact, total_tokens: fact.total_tokens + 10, input_tokens: fact.input_tokens + 10 }, "2026-06-03T12:05:00+08:00");
    expect(updated).toBeLessThanOrEqual(UPDATE_BUDGET);
    const row = await db.prepare("SELECT total_tokens FROM usage_hourly_facts WHERE fact_id = ?").bind(fact.fact_id).first<{ total_tokens: number }>();
    expect(row?.total_tokens).toBe(fact.total_tokens + 10);
  });

  it("值完全相同的重复上报零写入", async () => {
    const { db } = await acquireWorker({});
    const fact = fixtureFact();
    const seen = "2026-06-03T12:00:00+08:00";
    await write(db, fact, seen);
    expect(await write(db, fact, seen)).toBe(0);
  });
});

describe("额度历史只在数值变化或满 1 小时时记录", () => {
  const { acquire, post } = (() => {
    const acquire = () => acquireWorker({ AIUSAGE_NOW: "2026-06-03T12:00:00+08:00", AIUSAGE_TIMEZONE: "Asia/Shanghai" });
    const post = async (mf: Awaited<ReturnType<typeof acquireWorker>>["mf"], observedAt: string, used: number) => {
      const response = await mf.dispatchFetch("http://native.test/ingest-limits", {
        method: "POST", headers: { Authorization: "Bearer contract-test-token", "Content-Type": "application/json" },
        body: JSON.stringify({ schema_version: 1, observed_at: observedAt, windows: [{
          source_id: "tz-wangzp", provider: "claude", window: "week", used_percent: used, remaining_percent: 100 - used,
          reset_at: "2026-06-08T02:00:00+08:00", window_duration_minutes: 10080, observed_at: observedAt,
          source_type: "official_cli", confidence: "observed", status: "ok",
        }] }),
      });
      expect(response.status).toBe(200);
    };
    return { acquire, post };
  })();

  it("不变不记；变化即记；不变但满 1 小时补记一条；当前窗口始终更新", async () => {
    const { mf, db } = await acquire();
    await post(mf, "2026-06-03T10:00:00+08:00", 40);
    await post(mf, "2026-06-03T10:05:00+08:00", 40); // 不变：不记
    await post(mf, "2026-06-03T10:30:00+08:00", 40); // 不变：不记
    await post(mf, "2026-06-03T10:35:00+08:00", 41); // 变化：记
    await post(mf, "2026-06-03T11:40:00+08:00", 41); // 不变但距上一条 >1h：记
    const history = (await db.prepare("SELECT observed_at, used_percent FROM limit_window_history ORDER BY observed_at").all()).results;
    expect(history).toEqual([
      { observed_at: "2026-06-03T10:00:00+08:00", used_percent: 40 },
      { observed_at: "2026-06-03T10:35:00+08:00", used_percent: 41 },
      { observed_at: "2026-06-03T11:40:00+08:00", used_percent: 41 },
    ]);
    const current = await db.prepare("SELECT observed_at FROM limit_windows").first<{ observed_at: string }>();
    expect(current?.observed_at).toBe("2026-06-03T11:40:00+08:00");
  });
});

describe("读取失败的占位记录同样去重", () => {
  // 线上实测（2026-11-07 部署后）：provider_failed 占位的 reset_at = observed_at，每次都不同，
  // 去重把它当成「变化」，Antigravity 每次上报都记一条历史。
  it("失败占位 1 小时内只记一条，满 1 小时补记", async () => {
    const { mf, db } = await acquireWorker({ AIUSAGE_NOW: "2026-06-03T12:00:00+08:00", AIUSAGE_TIMEZONE: "Asia/Shanghai" });
    const fail = async (at: string) => {
      const response = await mf.dispatchFetch("http://native.test/ingest-limits", {
        method: "POST", headers: { Authorization: "Bearer contract-test-token", "Content-Type": "application/json" },
        body: JSON.stringify({ schema_version: 1, observed_at: at, windows: [{
          source_id: "antigravity-main", provider: "antigravity", window: "unknown", used_percent: 0, remaining_percent: 0,
          reset_at: at, window_duration_minutes: 0, observed_at: at,
          source_type: "provider_runtime", confidence: "missing", status: "provider_failed",
        }] }),
      });
      expect(response.status).toBe(200);
    };
    for (const at of ["2026-06-03T10:00:00+08:00", "2026-06-03T10:05:00+08:00", "2026-06-03T10:30:00+08:00", "2026-06-03T11:05:00+08:00"]) {
      await fail(at);
    }
    const history = (await db.prepare("SELECT observed_at FROM limit_window_history ORDER BY observed_at").all()).results;
    expect(history).toEqual([{ observed_at: "2026-06-03T10:00:00+08:00" }, { observed_at: "2026-06-03T11:05:00+08:00" }]);
  });
});

describe("单日汇总重算：只写真正变化的格子", () => {
  const day = "2026-06-03";
  async function seed(db: D1Database, hours: number[], tokensAt: (hour: number) => number) {
    await db.prepare("DELETE FROM usage_hourly_facts").run();
    for (const hour of hours) {
      const start = `${day}T${String(hour).padStart(2, "0")}:00:00+08:00`;
      const end = `${day}T${String(hour).padStart(2, "0")}:59:59+08:00`;
      await db.prepare(`INSERT INTO usage_hourly_facts (fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id,
        agent, client, window_start, window_end, timezone, total_tokens, input_tokens, attribution_confidence, provenance,
        first_seen_at, last_seen_at) VALUES (?, 'src', 'm', 'u', 'claude', 'acct', 'claude', 'cli', ?, ?, 'Asia/Shanghai', ?, ?,
        'observed', 'seed', ?, ?)`).bind(`f-${hour}`, start, end, tokensAt(hour), tokensAt(hour), start, start).run();
    }
    // 种子数据由测试直接写入，触发器会登记脏日；这里只度量重算本身。
    await db.prepare("DELETE FROM usage_rollup_dirty_days").run();
  }
  async function rebuild(db: D1Database) {
    const results = await db.batch(localDayRollupStatements(db, day));
    return results.reduce((sum, r) => sum + Number(r.meta.rows_written ?? 0), 0);
  }
  async function snapshot(db: D1Database) {
    const hourly = (await db.prepare("SELECT bucket_start, total_tokens FROM usage_hourly_rollups ORDER BY bucket_start").all()).results;
    const daily = (await db.prepare("SELECT date, total_tokens, fact_count FROM usage_daily_rollups").all()).results;
    return { hourly, daily };
  }

  it("10 个小时里只改 1 个小时：重算写入 ≤ 2 行，结果与全量一致", async () => {
    const { db } = await acquireWorker({ AIUSAGE_TIMEZONE: "Asia/Shanghai" });
    const hours = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17];
    await seed(db, hours, (hour) => hour * 100);
    expect(await rebuild(db)).toBeGreaterThan(20); // 首次全量写入（含索引），证明度量有效
    await db.prepare("UPDATE usage_hourly_facts SET total_tokens = total_tokens + 5, input_tokens = input_tokens + 5 WHERE fact_id = 'f-17'").run();
    await db.prepare("DELETE FROM usage_rollup_dirty_days").run();
    const written = await rebuild(db);
    expect(written).toBeLessThanOrEqual(2); // 变化的那个小时格 + 当天日汇总
    const state = await snapshot(db);
    expect(state.hourly).toHaveLength(10);
    expect(state.hourly.at(-1)).toEqual({ bucket_start: `${day}T17:00:00+08:00`, total_tokens: 1705 });
    expect(state.daily).toEqual([{ date: day, total_tokens: hours.reduce((sum, h) => sum + h * 100, 0) + 5, fact_count: 10 }]);
  });

  it("同一小时里明细改了归属（身份变化），旧身份的格子要删掉", async () => {
    const { db } = await acquireWorker({ AIUSAGE_TIMEZONE: "Asia/Shanghai" });
    await seed(db, [9], () => 50);
    await rebuild(db);
    await db.prepare("UPDATE usage_hourly_facts SET ai_account_id = 'acct-b' WHERE fact_id = 'f-9'").run();
    await rebuild(db);
    const hourly = (await db.prepare("SELECT ai_account_id, total_tokens FROM usage_hourly_rollups").all()).results;
    const daily = (await db.prepare("SELECT ai_account_id, total_tokens FROM usage_daily_rollups").all()).results;
    expect(hourly).toEqual([{ ai_account_id: "acct-b", total_tokens: 50 }]);
    expect(daily).toEqual([{ ai_account_id: "acct-b", total_tokens: 50 }]);
  });

  it("没有任何变化时零写入", async () => {
    const { db } = await acquireWorker({ AIUSAGE_TIMEZONE: "Asia/Shanghai" });
    await seed(db, [9, 10], (hour) => hour);
    await rebuild(db);
    expect(await rebuild(db)).toBe(0);
  });

  it("明细被删掉的小时与身份，汇总里也删掉（不留陈旧格子）", async () => {
    const { db } = await acquireWorker({ AIUSAGE_TIMEZONE: "Asia/Shanghai" });
    await seed(db, [9, 10, 11], (hour) => hour);
    await rebuild(db);
    await db.prepare("DELETE FROM usage_hourly_facts WHERE fact_id = 'f-10'").run();
    await rebuild(db);
    const state = await snapshot(db);
    expect(state.hourly.map((row) => row.bucket_start)).toEqual([`${day}T09:00:00+08:00`, `${day}T11:00:00+08:00`]);
    expect(state.daily).toEqual([{ date: day, total_tokens: 20, fact_count: 2 }]);
    await db.prepare("DELETE FROM usage_hourly_facts").run();
    await rebuild(db);
    expect(await snapshot(db)).toEqual({ hourly: [], daily: [] });
  });
});

it("单日重算语句数与分批常量一致（分批按它计算 25 条上限）", async () => {
  const { db } = await acquireWorker({});
  const source = readFileSync(path.join(repoRoot, "cloudflare/native-worker/src/write-model/handlers.ts"), "utf8");
  const declared = Number(/const LOCAL_DAY_ROLLUP_STATEMENTS = (\d+);/.exec(source)?.[1]);
  expect(localDayRollupStatements(db, "2026-06-03")).toHaveLength(declared);
});
