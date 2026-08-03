/**
 * #90 缺口块 5：today 小时趋势的派生规则。
 *
 * **这一块的原始描述已经过期，实测记录在这里，别照着映射表再写一遍。**
 *
 * 映射表（`server-path-test-migration-map.md` 第 7 节第 5 项）说这里缺 5 条守卫，点名了
 * `addBlockToHourBuckets` / `dedupeCumulativeBlockRows` / `capTodayHourlyToPeriodTotals`
 * 三个函数，理由是「假尖峰、重复计数、超额趋势——用户直接看得见的错失去守卫」。
 *
 * 实测（2026-08-03）：`read-model.ts:164` 是 `const blockRows: TimedRow[] = []`——
 * **它被初始化成空数组之后再也没有被填充过**，`usage_blocks` 表在整个 `read-model.ts` 里
 * 一次都没有被查询。于是：
 *
 * - `addBlockToHourBuckets` / `dedupeCumulativeBlockRows` / `blockDedupeKey` /
 *   `blockRowSortKey` 全部是**死代码**；
 * - `capTodayHourlyToPeriodTotals` 虽然被调用，但**唯一的溢出来源就是 block**，
 *   所以它实际上是空转的。判定实验：把它整个改成 `return;`，本文件与全量 Worker 测试
 *   **结果一字不变**。
 *
 * 给死代码写守卫，产出的是「已经守住了」的假象，比没有守卫更糟。所以本文件只断言
 * **当前真的会跑到**的那条路径：账本小时事实 → 趋势点。死代码本身另记，见 #90 的评论。
 */

import { describe, expect, it } from "vitest";
import { withWorker } from "./golden/harness";
import { fixedNow, timezone } from "./golden/paths";

type AnyRecord = Record<string, unknown>;

const date = "2026-06-03";
const sourceId = "mac-local";
const machineId = "macbook-pro";
const osUser = "alice";

/** 账本事实：周期总量与小时趋势的唯一来源。 */
async function seedLedgerFacts(
  db: D1Database,
  facts: Array<{ hour: string; input: number; output: number; cache: number; agent?: string }>,
): Promise<void> {
  const statements = [
    db.prepare(`
      INSERT INTO source_identities (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
    `).bind(sourceId, machineId, machineId, osUser, "darwin", fixedNow, fixedNow),
    db.prepare(`
      INSERT INTO machines (machine_id, machine_name, host, platform, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, ?, ?)
    `).bind(machineId, machineId, machineId, "darwin", fixedNow, fixedNow),
  ];
  facts.forEach((fact, index) => {
    const agent = fact.agent ?? "claude";
    const total = fact.input + fact.output + fact.cache;
    statements.push(
      db.prepare(`
        INSERT OR IGNORE INTO ai_accounts (provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
      `).bind(agent, `${agent}-main`, osUser, osUser, null, fixedNow, fixedNow),
      db.prepare(`
        INSERT INTO usage_hourly_facts (
          fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
          window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
          cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count,
          session_count, attribution_confidence, provenance, first_seen_at, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).bind(
        `fact-${index}`, sourceId, machineId, osUser, agent, `${agent}-main`, agent, "test",
        `${date}T${fact.hour}:00:00+08:00`, `${date}T${fact.hour}:59:59+08:00`, timezone,
        fact.input, fact.output, fact.cache, 0, 0, total, null, 1, 1,
        "observed", "test", fixedNow, fixedNow,
      ),
    );
  });
  await db.batch(statements);
}

async function todaySummary(db: D1Database): Promise<AnyRecord> {
  const { buildSummary } = await import("../src/read-model");
  return await buildSummary(db, { date, period: "today", timezone, currentTime: fixedNow }) as AnyRecord;
}

const pointsOf = (summary: AnyRecord) => ((summary.trend as AnyRecord).points as AnyRecord[]) ?? [];
const sumField = (rows: AnyRecord[], field: string) => rows.reduce((sum, row) => sum + Number(row[field] ?? 0), 0);

describe.sequential("today 小时趋势（活路径）", () => {
  it("账本小时事实原样落到对应的那个小时点上，四个数一个都不许变形", async () => {
    await withWorker({ now: fixedNow }, async ({ db }) => {
      await seedLedgerFacts(db, [
        { hour: "09", input: 600, output: 300, cache: 100 },
        { hour: "14", input: 200, output: 100, cache: 50 },
      ]);

      const points = pointsOf(await todaySummary(db));
      expect(points.length, "today 趋势必须按小时铺满 24 格").toBe(24);

      const byHour = new Map(points.map((point) => [String(point.hour), point]));
      const nine = byHour.get(`${date}T09:00:00+08:00`);
      const fourteen = byHour.get(`${date}T14:00:00+08:00`);
      expect(nine, "09:00 点必须存在").toBeTruthy();
      expect(fourteen, "14:00 点必须存在").toBeTruthy();

      // 落错小时（时区算错、按 UTC 分桶）会让「上午的用量消失、半夜冒出来一坨」，
      // 这是用户一眼能看出来但很难自己解释的错。
      expect(nine).toMatchObject({ input_tokens: 600, output_tokens: 300, cache_tokens: 100, total_tokens: 1000 });
      expect(fourteen).toMatchObject({ input_tokens: 200, output_tokens: 100, cache_tokens: 50, total_tokens: 350 });

      // 没有事实的小时必须是 0，而不是被残差填充平摊掉。
      expect(byHour.get(`${date}T03:00:00+08:00`)!.total_tokens, "没用量的小时就是 0").toBe(0);
    });
  }, 60_000);

  // 这里曾经有一条「趋势之和 == 周期总量」的守恒断言，已删除：它是**恒真**的。
  // 判定实验：在 `hourlyTrend` 里静默丢掉 14 点那条小时事实，该断言仍然绿——
  // 因为 `fillTodayHourlyResidual` 会把缺掉的那块当作残差补回趋势，
  // 两侧于是必然相等。守恒等式选错了对象，测试和实现会一起错。
  // 真正能抓到「事实丢了」的是上面那条逐点比对（同一变异下变红）。

  it("by_agent 分项与逐点总量互相不矛盾", async () => {
    await withWorker({ now: fixedNow }, async ({ db }) => {
      await seedLedgerFacts(db, [
        { hour: "09", input: 600, output: 300, cache: 100 },
        { hour: "20", input: 50, output: 25, cache: 25, agent: "codex" },
      ]);

      const trend = (await todaySummary(db)).trend as AnyRecord;
      const byAgent = (trend.by_agent as AnyRecord[]) ?? [];
      const points = (trend.points as AnyRecord[]) ?? [];

      // 两个 agent 都必须出现——只有一个时，「分项之和等于总量」会退化成恒真。
      expect(byAgent.map((row) => String(row.agent)).sort(), "两个 agent 都要在分项里")
        .toEqual(["claude", "codex"]);
      const agentSum = byAgent.reduce(
        (sum, row) => sum + ((row.values as number[]) ?? []).reduce((acc, value) => acc + Number(value), 0), 0);
      expect(agentSum, "by_agent 之和必须等于逐点总量之和").toBe(sumField(points, "total_tokens"));
    });
  }, 60_000);
});
