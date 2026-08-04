/**
 * #101：共享 Miniflare fixture 的隔离性守卫。
 *
 * `resetDatabase` 的清理范围必须覆盖 schema 里的每一张用户表——
 * 每测新建实例时漏表无影响，一旦实例共享，漏掉的表就是跨用例污染通道。
 * 守卫用「实际污染全部表 → reset → 逐表断言清空」证明，不比对硬编码清单：
 * 未来新增的表会被 sqlite_master 枚举自动纳入，不给「忘了更新守卫」留缝。
 */

import { describe, expect, it } from "vitest";
import { acquireWorker, resetDatabase, withWorker } from "./golden/harness";
import { fixedNow } from "./golden/paths";
import type { Miniflare } from "miniflare";

/** 枚举全部用户表：排除 SQLite 自身（sqlite_*）与 D1/Miniflare 内部表（_cf_* 等下划线开头）。 */
async function listUserTables(db: D1Database): Promise<string[]> {
  const rows = await db.prepare(
    "SELECT name FROM sqlite_master WHERE type = 'table'"
    + " AND name NOT LIKE 'sqlite%' AND name NOT LIKE '\\_%' ESCAPE '\\'",
  ).all<{ name: string }>();
  return rows.results.map((row) => row.name);
}

type ColumnInfo = { name: string; type: string; notnull: number; dflt_value: string | null; pk: number };

/**
 * 给一张表造一行最小合法数据：NOT NULL 且无默认值的列按类型亲和性补值。
 * 表按 sqlite_master 创建顺序处理，schema 里唯一的 FK（source_reports.run_id →
 * collection_runs.id）靠「父表先插、AUTOINCREMENT 首行必为 1」满足。
 */
async function polluteTable(db: D1Database, table: string): Promise<void> {
  const info = await db.prepare(`PRAGMA table_info(${table})`).all<ColumnInfo>();
  const isNumeric = (type: string) => /INT|REAL|NUM|DOUBLE|FLOAT/i.test(type);
  let required = info.results.filter((col) => col.notnull === 1 && col.dflt_value === null);
  if (!required.length) {
    // 全列可空的表也要占一行，否则守卫对它是瞎的。
    required = info.results.slice(0, 1);
  }
  const columns = required.map((col) => col.name).join(", ");
  const placeholders = required.map(() => "?").join(", ");
  const values = required.map((col) => (isNumeric(col.type) ? 1 : "x"));
  await db.prepare(`INSERT INTO ${table} (${columns}) VALUES (${placeholders})`).bind(...values).run();
}

describe.sequential("shared worker fixture isolation", () => {
  it("resetDatabase clears every user table the schema creates", async () => {
    await withWorker({ now: fixedNow }, async ({ db }) => {
      const tables = await listUserTables(db);
      // 结构下限：枚举必须真的拿到了 schema 的表，并且包含这次事故的三位主角。
      expect(tables.length).toBeGreaterThanOrEqual(14);
      expect(tables).toContain("usage_daily_rollups");
      expect(tables).toContain("usage_hourly_rollups");
      expect(tables).toContain("source_accuracy");

      for (const table of tables) await polluteTable(db, table);
      for (const table of tables) {
        const row = await db.prepare(`SELECT count(*) AS n FROM ${table}`).first<{ n: number }>();
        expect(row?.n, `${table} 的污染行必须真的写进去了`).toBeGreaterThanOrEqual(1);
      }

      await resetDatabase(db);

      const dirty: string[] = [];
      for (const table of tables) {
        const row = await db.prepare(`SELECT count(*) AS n FROM ${table}`).first<{ n: number }>();
        if ((row?.n ?? 0) > 0) dirty.push(table);
      }
      expect(dirty, "resetDatabase 漏掉的表").toEqual([]);
    });
  });

  // 两个刻意互相污染的用例：A 往池化实例的每一张表写脏数据并直接结束，
  // B 用同一个绑定键重新 acquire，断言拿到的是**同一个实例**且库是干净的。
  // 断言必须分布在两个真实用例里——「用例之间」才是共享实例的清理边界，
  // 单个用例内部自证不了这件事。顺序由 describe.sequential 保证。
  let pollutedInstance: Miniflare | null = null;

  it("deliberately pollutes every table of a pooled instance (pair A)", async () => {
    const { mf, db } = await acquireWorker({ AIUSAGE_NOW: fixedNow });
    pollutedInstance = mf;
    const tables = await listUserTables(db);
    expect(tables.length).toBeGreaterThanOrEqual(14);
    for (const table of tables) await polluteTable(db, table);
    for (const table of tables) {
      const row = await db.prepare(`SELECT count(*) AS n FROM ${table}`).first<{ n: number }>();
      expect(row?.n, `${table} 的污染行必须真的写进去了`).toBeGreaterThanOrEqual(1);
    }
  });

  it("re-acquiring the same key must return the same instance with a clean database (pair B)", async () => {
    const { mf, db } = await acquireWorker({ AIUSAGE_NOW: fixedNow });
    // 结构下限：必须真的是同一个实例。拿到新实例的话，「干净」是靠重建白得的，
    // 这条守卫就在测一个不存在的场景。
    expect(pollutedInstance, "pair A 必须先跑过").not.toBeNull();
    expect(mf, "池必须复用同键实例而不是重建").toBe(pollutedInstance);

    const dirty: string[] = [];
    for (const table of await listUserTables(db)) {
      const row = await db.prepare(`SELECT count(*) AS n FROM ${table}`).first<{ n: number }>();
      if ((row?.n ?? 0) > 0) dirty.push(table);
    }
    expect(dirty, "上一个用例留下的脏表").toEqual([]);

    // 复用实例的发号器也必须像新库：pair A 灌过 AUTOINCREMENT 表之后这里仍要发 1。
    const run = await db.prepare(
      "INSERT INTO collection_runs (collected_at, timezone, collector_version, status)"
      + " VALUES ('2026-06-03T11:00:00+08:00', 'Asia/Shanghai', '0.1.0', 'ok') RETURNING id",
    ).first<{ id: number }>();
    expect(run?.id, "复用实例必须像新库一样从 id=1 发号").toBe(1);
  });

  it("acquireWorker rejects attempts to re-enable the summary cache on a pooled instance", async () => {
    // 池化实例强制关缓存；调用方传开关进来只有两种结局——被静默吞掉（危险：
    // 「不该有缓存头」的断言会变恒真）或显式报错。必须是后者。
    await expect(acquireWorker({ AIUSAGE_DISABLE_SUMMARY_CACHE: "false" }))
      .rejects.toThrow(/AIUSAGE_DISABLE_SUMMARY_CACHE/);
  });

  it("resetDatabase restores autoincrement ids to a fresh-database state", async () => {
    // 共享实例下 DELETE FROM 不清 sqlite_sequence：复用库发出的 id 会从上个
    // 用例的尾巴继续长，任何依赖「新库第一行 id=1」的种子或 golden 都会漂。
    await withWorker({ now: fixedNow }, async ({ db }) => {
      const insertRun = () => db.prepare(
        "INSERT INTO collection_runs (collected_at, timezone, collector_version, status)"
        + " VALUES ('2026-06-03T11:00:00+08:00', 'Asia/Shanghai', '0.1.0', 'ok') RETURNING id",
      ).first<{ id: number }>();
      await insertRun();
      await insertRun();
      await resetDatabase(db);
      const afterReset = await insertRun();
      expect(afterReset?.id, "重置后的库必须像新库一样从 id=1 发号").toBe(1);
    });
  });
});
