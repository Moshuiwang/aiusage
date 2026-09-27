/**
 * #190 第 2 项：julianday(window_start)/julianday(bucket_start) 表达式索引守卫
 * （migration 0014）。
 *
 * read-model/db.ts 的 periodWhere 一律写成 `julianday(window_start) >= julianday(?)
 * AND julianday(window_start) < julianday(?)`——SQLite 的默认列索引对被函数包住的列
 * 谓词用不上，退化成全表扫描（SCAN）。这里直接用真实 D1（miniflare）跑
 * EXPLAIN QUERY PLAN，断言三张表的这个谓词都走 SEARCH，并且删掉索引后确实会变回
 * SCAN（变异证据：先看到红——SCAN——再确认索引存在时是绿——SEARCH）。
 */
import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { Miniflare } from "miniflare";
import { schemaPath } from "./golden/paths";
import { applySqlText } from "./golden/harness";

async function freshDb(): Promise<{ mf: Miniflare; db: D1Database }> {
  const mf = new Miniflare({
    modules: true,
    script: "export default { fetch() { return new Response('ok'); } }",
    d1Databases: ["DB"],
  });
  const db = await mf.getD1Database("DB");
  await applySqlText(db, await readFile(schemaPath, "utf8"));
  return { mf, db };
}

async function planDetail(db: D1Database, sql: string, params: unknown[]): Promise<string> {
  const result = await db.prepare(`EXPLAIN QUERY PLAN ${sql}`).bind(...params).all<{ detail: string }>();
  return (result.results ?? []).map((row) => row.detail).join(" | ");
}

const CASES: Array<{ table: string; column: string; index: string; sql: string }> = [
  {
    table: "usage_hourly_facts",
    column: "window_start",
    index: "idx_usage_hourly_facts_window_julianday",
    sql: "SELECT * FROM usage_hourly_facts f WHERE julianday(f.window_start) >= julianday(?) AND julianday(f.window_start) < julianday(?)",
  },
  {
    table: "usage_hourly_rollups",
    column: "bucket_start",
    index: "idx_usage_hourly_rollups_bucket_julianday",
    sql: "SELECT * FROM usage_hourly_rollups f WHERE julianday(f.bucket_start) >= julianday(?) AND julianday(f.bucket_start) < julianday(?)",
  },
  {
    table: "usage_daily_rollups",
    column: "bucket_start",
    index: "idx_usage_daily_rollups_bucket_julianday",
    sql: "SELECT * FROM usage_daily_rollups f WHERE julianday(f.bucket_start) >= julianday(?) AND julianday(f.bucket_start) < julianday(?)",
  },
];

describe("#190：julianday() 范围过滤的表达式索引（migration 0014）", () => {
  for (const testCase of CASES) {
    it(`${testCase.table}: julianday(${testCase.column}) 范围过滤走 SEARCH，删掉索引后变回 SCAN（变异证据）`, async () => {
      // 正面：schema 自带这个表达式索引时，走 SEARCH。
      const positive = await freshDb();
      try {
        const withIndex = await planDetail(positive.db, testCase.sql, ["2026-01-01", "2026-01-02"]);
        expect(withIndex).toContain("SEARCH");
        expect(withIndex).toContain(testCase.index);
        expect(withIndex).not.toContain("SCAN");
      } finally {
        await positive.mf.dispose();
      }

      // 变异：另开一个全新实例，在**第一次**对这句 SQL 跑 EXPLAIN 之前就删掉索引——
      // 必须用全新实例，不能在同一个 db 上"先查一次（缓存住计划）再删索引再查一次"：
      // miniflare 的 D1 对同一句 SQL 文本有查询计划缓存，DROP INDEX 之后原样重跑同一句
      // 文本会命中缓存拿到删除前的旧计划（sqlite_master 里索引确实已经不在了，但
      // EXPLAIN 结果不变）——那种写法测的是缓存复用，不是索引有没有生效。
      const negative = await freshDb();
      try {
        await negative.db.prepare(`DROP INDEX ${testCase.index}`).run();
        const rows = await negative.db.prepare(
          `SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?`,
        ).bind(testCase.index).all();
        expect(rows.results ?? []).toHaveLength(0); // 删除确实生效，不是误判。

        const withoutIndex = await planDetail(negative.db, testCase.sql, ["2026-01-01", "2026-01-02"]);
        expect(withoutIndex).toContain("SCAN f"); // SQLite 报告的是查询里用的别名 f，不是表名。
        expect(withoutIndex).not.toContain("SEARCH");
      } finally {
        await negative.mf.dispose();
      }
    });
  }

  it("fetchAccountRowsFromTable 的实际包装子查询（rollup 分支）同样走 SEARCH：表达式索引对查询规划器可见的形状是真实生产查询，不是简化过的示例", async () => {
    const { mf, db } = await freshDb();
    try {
      const wrappedQuery = `
        SELECT f.fact_id, f.source_id
        FROM (SELECT NULL AS fact_id, bucket_start AS window_start, bucket_end AS window_end,
                     source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
                     attribution_confidence, provenance, input_tokens, output_tokens,
                     cache_creation_tokens, cache_read_tokens, reasoning_output_tokens,
                     total_tokens, total_cost, event_count, session_count, fact_count
              FROM usage_daily_rollups) f
        LEFT JOIN machines m ON m.machine_id = f.machine_id
        LEFT JOIN ai_accounts a ON a.provider = f.ai_provider AND a.account_id = f.ai_account_id
        WHERE julianday(f.window_start) >= julianday(?) AND julianday(f.window_start) < julianday(?)
      `;
      const plan = await planDetail(db, wrappedQuery, ["2026-01-01", "2026-01-02"]);
      expect(plan).toContain("SEARCH usage_daily_rollups USING INDEX idx_usage_daily_rollups_bucket_julianday");
    } finally {
      await mf.dispose();
    }
  });
});
