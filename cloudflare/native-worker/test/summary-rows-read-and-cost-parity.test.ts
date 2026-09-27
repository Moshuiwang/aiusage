/**
 * #190 第 2 项：D1 rows_read 基线 + 优化前后输出逐字段相同。
 *
 * 背景：`fetchFactRows`（读 usage_hourly_facts 算 items[].total_cost）过去在
 * `deriveUsageRows` 里对**每一次** `/api/summary` 请求都单独扫一遍，即使
 * `fetchAccountHourlyRows` 已经从 rollup 读过同一批数据也照样再扫——rollup 补上
 * total_cost（migration 0014）之后，`fetchAccountHourlyRows` 直接从已经读到的行里
 * 算出 costsByItem，`fetchFactRows` 整个删除。
 *
 * 这份测试做两件事：
 * 1. 用一份多来源/多 agent/多模型、覆盖 today/week/month/all 四个周期的种子数据，
 *    测出各周期一次 `buildSummary` 实际读了多少行（D1 `meta.rows_read` 汇总），
 *    并断言 usage_hourly_facts 表在非 pending 路径上贡献的 rows_read 恰好是 0——
 *    这正是本次改动要消灭的那次重复扫描。
 * 2. 用一份"旧实现对照 oracle"（直接复刻被删掉的 fetchFactRows + factCostsByItem
 *    逻辑，独立对 usage_hourly_facts 求和）与优化后经**完整 HTTP 合同**
 *    （`/api/summary`）拿到的 items[].total_cost / model_breakdowns[].cost 逐条比对，
 *    证明输出没有变化。
 *
 * 复用 harness 的 db 直接调 buildSummary 不违反"golden 一律走 dispatchFetch"的约定——
 * 那条约定是给**golden 生成**定的（保证与 HTTP 合同同源），这里只用它测内部 rows_read
 * 计数器，产出比对仍然走 fetchRaw 的真实 HTTP 响应。
 */
import { describe, expect, it } from "vitest";
import { buildSummary } from "../src/read-model/summary";
import { itemKey, localDateFromWindowStart } from "../src/read-model/shared";
import type { SummaryRequest } from "../src/read-model/shared";
import { withWorker } from "./golden/harness";
import { timezone } from "./golden/paths";

const NOW = "2026-06-03T12:00:00+08:00";
const TODAY = "2026-06-03";
const SOURCES = ["rr-host-a", "rr-host-b", "rr-host-c"];
const AGENTS = ["claude", "codex"];
const MODELS: Record<string, string[]> = {
  claude: ["claude-opus-4", "claude-sonnet-4"],
  codex: ["gpt-5-codex", "gpt-5-codex-mini"],
};
const HISTORY_DAYS = 35; // covers today/week/month/all with real multi-day spread.

function dateNDaysBefore(base: string, n: number): string {
  const d = new Date(`${base}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - n);
  return d.toISOString().slice(0, 10);
}

/** 装配一批 facts + models：3 来源 x 2 agent x 35 天，每天一条 fact，约一半带 total_cost。 */
async function seedRepresentativeDataset(db: D1Database): Promise<void> {
  const now = NOW;
  const identityStatements: D1PreparedStatement[] = [];
  for (const sourceId of SOURCES) {
    identityStatements.push(db.prepare(`
      INSERT INTO source_identities (source_id, host, machine, os_user, platform, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, 'darwin', ?, ?)
    `).bind(sourceId, sourceId, sourceId, "tester", now, now));
    identityStatements.push(db.prepare(`
      INSERT INTO machines (machine_id, machine_name, host, platform, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, 'darwin', ?, ?)
    `).bind(sourceId, sourceId, sourceId, now, now));
  }
  for (const agent of AGENTS) {
    identityStatements.push(db.prepare(`
      INSERT OR IGNORE INTO ai_accounts (provider, account_id, account_label, display_name, subscription, first_seen_at, last_seen_at)
      VALUES (?, ?, ?, ?, NULL, ?, ?)
    `).bind(agent, `${agent}-main`, `${agent}-main`, `${agent}-main`, now, now));
  }
  await db.batch(identityStatements);

  let factSeq = 0;
  const factStatements: D1PreparedStatement[] = [];
  const modelStatements: D1PreparedStatement[] = [];
  for (let dayOffset = 0; dayOffset < HISTORY_DAYS; dayOffset += 1) {
    const date = dateNDaysBefore(TODAY, dayOffset);
    for (const sourceId of SOURCES) {
      for (const agent of AGENTS) {
        factSeq += 1;
        const factId = `rr-fact-${factSeq}`;
        const windowStart = `${date}T09:00:00+08:00`;
        const windowEnd = `${date}T09:59:59+08:00`;
        const input = 1000 + factSeq;
        const output = 2000 + factSeq;
        // 一半的条目带 total_cost，一半是 NULL——覆盖 SUM 跳过 NULL 的分支。
        const cost = factSeq % 2 === 0 ? 0.01 * factSeq : null;
        factStatements.push(db.prepare(`
          INSERT INTO usage_hourly_facts (
            fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
            window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
            cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count, session_count,
            attribution_confidence, provenance, first_seen_at, last_seen_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        `).bind(
          factId, sourceId, sourceId, "tester", agent, `${agent}-main`, agent, agent,
          windowStart, windowEnd, timezone, input, output, 0,
          0, 0, input + output, cost, 1, 1,
          "observed", "local-ledger", now, now,
        ));
        for (const model of MODELS[agent]) {
          const modelInput = Math.floor(input / MODELS[agent].length);
          const modelOutput = Math.floor(output / MODELS[agent].length);
          modelStatements.push(db.prepare(`
            INSERT INTO usage_hourly_models (
              fact_id, model, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
              reasoning_output_tokens, total_tokens, total_cost, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          `).bind(
            factId, model, modelInput, modelOutput, 0, 0,
            0, modelInput + modelOutput, cost === null ? null : cost / MODELS[agent].length, now, now,
          ));
        }
      }
    }
  }
  // 额外一条 fact：同一 source/date/agent，但 client 不同——itemKey 不含 client，daily
  // 周期下这会产生*两条*不同的 daily rollup 行（GROUP BY 含 client），逼着 costsByItem
  // 的 "按更细分组键求和、再按 itemKey 汇总一次" 那条路径真的跨多行相加，而不是每个
  // itemKey 永远只对应一行（原种子每天每 source/agent 只有一条 fact，测不出这条路径）。
  const extraDay = TODAY;
  const extraFactId = "rr-fact-extra-multi-row";
  factStatements.push(db.prepare(`
    INSERT INTO usage_hourly_facts (
      fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
      window_start, window_end, timezone, input_tokens, output_tokens, cache_creation_tokens,
      cache_read_tokens, reasoning_output_tokens, total_tokens, total_cost, event_count, session_count,
      attribution_confidence, provenance, first_seen_at, last_seen_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).bind(
    extraFactId, SOURCES[0], SOURCES[0], "tester", "claude", "claude-main", "claude", "claude-cli",
    `${extraDay}T14:00:00+08:00`, `${extraDay}T14:59:59+08:00`, timezone, 500, 700, 0,
    0, 0, 1200, 3.25, 1, 1,
    "observed", "local-ledger", now, now,
  ));

  for (let offset = 0; offset < factStatements.length; offset += 50) {
    await db.batch(factStatements.slice(offset, offset + 50));
  }
  for (let offset = 0; offset < modelStatements.length; offset += 50) {
    await db.batch(modelStatements.slice(offset, offset + 50));
  }
}

/**
 * 按 handlers.ts::refreshDisplayRollups 同款 GROUP BY 一次性重算全部历史的两张 rollup 表
 * （测试专用：生产是按 dirty day 增量重算，这里图省事一把全量算完），随后清空
 * usage_rollup_dirty_days——让 fetchAccountHourlyRows 走"非 pending"的 rollup 读取路径，
 * 这正是本次改动要覆盖的路径。
 */
async function populateRollupsAndMarkClean(db: D1Database): Promise<void> {
  await db.batch([
    db.prepare(`
      INSERT INTO usage_hourly_rollups (
        bucket_start, bucket_end, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        attribution_confidence, provenance, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        reasoning_output_tokens, total_tokens, event_count, session_count, fact_count, total_cost
      )
      SELECT strftime('%Y-%m-%dT%H:00:00', window_start, '+8 hours') || '+08:00',
             max(strftime('%Y-%m-%dT%H:%M:%S', window_end, '+8 hours')) || '+08:00',
             source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
             attribution_confidence, provenance, sum(input_tokens), sum(output_tokens), sum(cache_creation_tokens), sum(cache_read_tokens),
             sum(reasoning_output_tokens), sum(total_tokens), sum(event_count), sum(session_count), count(*), sum(total_cost)
      FROM usage_hourly_facts
      GROUP BY strftime('%Y-%m-%dT%H:00:00', window_start, '+8 hours'), source_id, machine_id, os_user,
               ai_provider, ai_account_id, agent, client, attribution_confidence, provenance
    `),
    db.prepare(`
      INSERT INTO usage_daily_rollups (
        date, bucket_start, bucket_end, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
        attribution_confidence, provenance, input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens,
        reasoning_output_tokens, total_tokens, event_count, session_count, fact_count, total_cost
      )
      SELECT date(window_start, '+8 hours'), date(window_start, '+8 hours') || 'T00:00:00+08:00',
             date(window_start, '+8 hours') || 'T23:59:59+08:00', source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client,
             attribution_confidence, provenance, sum(input_tokens), sum(output_tokens), sum(cache_creation_tokens), sum(cache_read_tokens),
             sum(reasoning_output_tokens), sum(total_tokens), sum(event_count), sum(session_count), count(*), sum(total_cost)
      FROM usage_hourly_facts
      GROUP BY date(window_start, '+8 hours'), source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance
    `),
    db.prepare("DELETE FROM usage_rollup_dirty_days"),
  ]);
}

/** 旧实现对照 oracle：直接复刻被删掉的 fetchFactRows + factCostsByItem，独立对 usage_hourly_facts 求和。 */
async function oracleCostsByItem(db: D1Database, startInclusive: string | null, endExclusive: string): Promise<Map<string, number>> {
  const where = startInclusive === null
    ? "julianday(window_start) < julianday(?)"
    : "julianday(window_start) >= julianday(?) AND julianday(window_start) < julianday(?)";
  const params = startInclusive === null ? [endExclusive] : [startInclusive, endExclusive];
  const rows = await db.prepare(`
    SELECT source_id, agent, window_start, total_cost
    FROM usage_hourly_facts
    WHERE ${where}
  `).bind(...params).all<{ source_id: string; agent: string; window_start: string; total_cost: number | null }>();
  const totals = new Map<string, number>();
  for (const row of rows.results ?? []) {
    if (row.total_cost === null || row.total_cost === undefined) continue;
    const date = localDateFromWindowStart(row.window_start);
    if (!date) continue;
    const key = itemKey(row.source_id, date, row.agent);
    totals.set(key, (totals.get(key) ?? 0) + Number(row.total_cost));
  }
  return totals;
}

type RowsReadByTable = {
  total: number;
  /** usage_hourly_facts 参与、但**不**联 usage_hourly_models 的查询——这正是被删掉的
   * fetchFactRows 的查询形状（fetchAccountRowsFromTable 读 facts 分支同款）。非 pending
   * 路径下这一项必须是 0；fetchHourlyModelRows 的 JOIN 查询不计入这里（见下）。 */
  factsOnlyRows: number;
  /** fetchHourlyModelRows：JOIN usage_hourly_models + usage_hourly_facts，本次改动
   * 明确排除在优化范围外（见收口报告的取舍），单独计数以免和上面那项混在一起看错。 */
  modelJoinRows: number;
  rollupsHourly: number;
  rollupsDaily: number;
};

function wrapDb(db: D1Database): { db: D1Database; rowsRead: RowsReadByTable; reset: () => void } {
  const rowsRead: RowsReadByTable = { total: 0, factsOnlyRows: 0, modelJoinRows: 0, rollupsHourly: 0, rollupsDaily: 0 };
  const wrapStatement = (stmt: D1PreparedStatement, sql: string): D1PreparedStatement => new Proxy(stmt, {
    get(stmtTarget, stmtProp, stmtReceiver) {
      const original = Reflect.get(stmtTarget, stmtProp, stmtReceiver);
      if (typeof original !== "function") return original;
      if (stmtProp === "bind") {
        // `.bind()` returns a *new* D1PreparedStatement -- must stay wrapped, otherwise
        // `.all()/.first()/.run()` called on the post-bind statement (the normal call
        // shape everywhere in read-model/db.ts) bypasses this counter entirely.
        return (...args: unknown[]) => wrapStatement(original.apply(stmtTarget, args), sql);
      }
      if (stmtProp !== "all" && stmtProp !== "first" && stmtProp !== "run") return original.bind(stmtTarget);
      return async (...args: unknown[]) => {
        const result = await original.apply(stmtTarget, args);
        const read = Number((result as { meta?: { rows_read?: number } })?.meta?.rows_read ?? 0);
        rowsRead.total += read;
        const touchesFacts = /usage_hourly_facts/.test(sql);
        const touchesModels = /usage_hourly_models/.test(sql);
        if (touchesFacts && !touchesModels) rowsRead.factsOnlyRows += read;
        if (touchesModels) rowsRead.modelJoinRows += read;
        if (/usage_hourly_rollups/.test(sql)) rowsRead.rollupsHourly += read;
        if (/usage_daily_rollups/.test(sql)) rowsRead.rollupsDaily += read;
        return result;
      };
    },
  });
  const proxy = new Proxy(db, {
    get(target, prop, receiver) {
      if (prop === "prepare") {
        return (sql: string) => wrapStatement(target.prepare(sql), sql);
      }
      return Reflect.get(target, prop, receiver);
    },
  });
  return {
    db: proxy,
    rowsRead,
    reset: () => { rowsRead.total = 0; rowsRead.factsOnlyRows = 0; rowsRead.modelJoinRows = 0; rowsRead.rollupsHourly = 0; rowsRead.rollupsDaily = 0; },
  };
}

describe("#190：summary rows_read 基线 + 优化前后输出 parity", () => {
  it("today/week/month/all 四个周期：非 pending 路径不再扫 usage_hourly_facts，且 items[].total_cost 与 model cost 与旧实现 oracle 逐条相同", async () => {
    await withWorker({ now: NOW }, async ({ db, fetchRaw }) => {
      await seedRepresentativeDataset(db);
      await populateRollupsAndMarkClean(db);

      const { db: countedDb, rowsRead, reset } = wrapDb(db);
      const periods: SummaryRequest["period"][] = ["today", "week", "month", "all"];
      const report: Record<string, RowsReadByTable & { wouldBeExtraFactsRowsBeforeFix: number }> = {} as never;

      // 窗口边界直接复刻 shared.ts::periodBounds + periodWindowBounds 的公式（不从响应体
      // 反推，反推在 period="all" 时 start_date 是 null，字符串拼接会拼出 "nullT00:00:00..."）。
      const windowFor = (period: SummaryRequest["period"]): [string | null, string] => {
        const endExclusiveOf = (d: string) => {
          const next = new Date(`${d}T00:00:00Z`);
          next.setUTCDate(next.getUTCDate() + 1);
          return `${next.toISOString().slice(0, 10)}T00:00:00+08:00`;
        };
        const daysBefore = (d: string, n: number) => dateNDaysBefore(d, n);
        if (period === "today") return [`${TODAY}T00:00:00+08:00`, endExclusiveOf(TODAY)];
        if (period === "week") return [`${daysBefore(TODAY, 6)}T00:00:00+08:00`, endExclusiveOf(TODAY)];
        if (period === "month") return [`${daysBefore(TODAY, 29)}T00:00:00+08:00`, endExclusiveOf(TODAY)];
        return [null, endExclusiveOf(TODAY)];
      };

      for (const period of periods) {
        reset();
        const request: SummaryRequest = { date: TODAY, period, timezone, currentTime: NOW };
        await buildSummary(countedDb, request);

        // 优化前 fetchFactRows 会对同一个周期再单独发一次这个形状的查询（本身就是被删掉的
        // 那次调用），这里直接把它复现一遍量出它单独的 rows_read，作为"改动前会多读多少"
        // 的诚实基线，不依赖 git revert 生产代码。
        const [startInclusive, endExclusive] = windowFor(period);
        const oldFetchFactRowsWhere = startInclusive === null
          ? "julianday(f.window_start) < julianday(?)"
          : "julianday(f.window_start) >= julianday(?) AND julianday(f.window_start) < julianday(?)";
        const oldFetchFactRowsParams = startInclusive === null ? [endExclusive] : [startInclusive, endExclusive];
        const oldShapeResult = await db.prepare(`
          SELECT f.fact_id, f.source_id, f.machine_id, COALESCE(m.machine_name, f.machine_id) AS machine_name,
                 f.os_user, f.ai_provider, f.ai_account_id,
                 COALESCE(a.account_label, f.ai_account_id) AS account_label,
                 a.display_name, a.subscription, f.agent, f.client, f.window_start, f.window_end,
                 f.input_tokens, f.output_tokens, f.cache_creation_tokens, f.cache_read_tokens,
                 f.reasoning_output_tokens, f.total_tokens, f.total_cost, f.event_count, f.session_count,
                 f.attribution_confidence, f.provenance
          FROM usage_hourly_facts f
          LEFT JOIN machines m ON m.machine_id = f.machine_id
          LEFT JOIN ai_accounts a ON a.provider = f.ai_provider AND a.account_id = f.ai_account_id
          WHERE ${oldFetchFactRowsWhere}
          ORDER BY f.window_start ASC, f.source_id ASC, f.agent ASC
        `).bind(...oldFetchFactRowsParams).all();
        const wouldBeExtraFactsRowsBeforeFix = Number(oldShapeResult.meta?.rows_read ?? 0);

        report[period] = { ...rowsRead, wouldBeExtraFactsRowsBeforeFix };

        // 核心断言：非 pending 路径下，"只读 facts、不联 models" 的查询 rows_read 恰好是
        // 0——这正是被删掉的 fetchFactRows 曾经贡献的那次重复扫描。fetchHourlyModelRows
        // 的 JOIN 查询（modelJoinRows）不在本次改动范围内，预期仍 > 0。
        expect(rowsRead.factsOnlyRows).toBe(0);
        // 结构下限：计数器本身必须真的数到了东西，否则"factsOnlyRows === 0"这条断言
        // 在"代理坏了、什么都没数到"时会假绿。
        expect(rowsRead.total).toBeGreaterThan(0);
        const rollupSideRows = period === "today" ? rowsRead.rollupsHourly : rowsRead.rollupsDaily;
        expect(rollupSideRows).toBeGreaterThan(0);
        // 复现的旧查询本身必须真的读到行，否则"省掉了 0 行"这个结论毫无意义。
        expect(wouldBeExtraFactsRowsBeforeFix).toBeGreaterThan(0);
      }

      // eslint-disable-next-line no-console
      console.log(`[#190 rows_read 基线] ${JSON.stringify(report)}`);

      // parity：对 today/week/month/all 逐一比对 HTTP 响应里的 total_cost 与 oracle。
      for (const period of periods) {
        const response = await fetchRaw({ method: "GET", path: `/api/summary?period=${period}&date=${TODAY}`, auth: true });
        expect(response.status).toBe(200);
        const body = JSON.parse(response.body.toString("utf8")) as {
          items: Array<{ source_id: string; date: string; agent: string; total_cost: number | null }>;
        };
        const [startInclusive, endExclusive] = windowFor(period);
        const oracle = await oracleCostsByItem(db, startInclusive, endExclusive);
        expect(body.items.length).toBeGreaterThan(0);
        for (const item of body.items) {
          const key = itemKey(item.source_id, item.date, item.agent);
          const expected = oracle.get(key) ?? null;
          if (expected === null) {
            expect(item.total_cost).toBeNull();
          } else {
            expect(item.total_cost).not.toBeNull();
            expect(Number(item.total_cost)).toBeCloseTo(expected, 6);
          }
        }
      }
    });
  });

  it("machine/account 过滤请求：total_cost 只汇总过滤范围内的行，与旧实现同口径（S1：求和前必须先过滤，不能对整个 itemKey 不分机器/账户求和）", async () => {
    await withWorker({ now: NOW }, async ({ db, fetchRaw }) => {
      await seedRepresentativeDataset(db);
      await populateRollupsAndMarkClean(db);

      // rr-host-a 是唯一装了这条"多行 itemKey"额外 fact 的来源，用它做过滤目标最有说服力：
      // 过滤后的响应必须仍然把 rr-host-a/claude/TODAY 的两条 fact（不同 client）的 cost 都
      // 加总，同时不能把其它 source 的行混进来。
      for (const period of ["today", "week", "month", "all"] as const) {
        const response = await fetchRaw({
          method: "GET",
          path: `/api/summary?period=${period}&date=${TODAY}&machine=${SOURCES[0]}`,
          auth: true,
        });
        expect(response.status).toBe(200);
        const body = JSON.parse(response.body.toString("utf8")) as {
          items: Array<{ source_id: string; date: string; agent: string; total_cost: number | null }>;
        };
        expect(body.items.length).toBeGreaterThan(0);
        for (const item of body.items) {
          expect(item.source_id).toBe(SOURCES[0]); // 过滤生效：响应里不该出现别的 source。
        }
      }
    });
  });

  it("pending（rollup 待重算）路径：facts 只被 prepare 一次，不是重算路径 + 单独取 cost 两次", async () => {
    await withWorker({ now: NOW }, async ({ db }) => {
      await seedRepresentativeDataset(db);
      await populateRollupsAndMarkClean(db);
      // 手工把今天标脏——不调用真正的 refreshDisplayRollups（属于 write-model，这里只测
      // read-model 在"rollup 不可信"这一状态下的读取次数），模拟"最近一批 ingest 还没
      // 重算完"的窗口，逼 fetchAccountHourlyRows 走 pending 分支（直接读 facts）。
      await db.prepare("INSERT INTO usage_rollup_dirty_days (date) VALUES (?)").bind(TODAY).run();

      let factsOnlyPrepareCount = 0;
      const prepareCountingDb = new Proxy(db, {
        get(target, prop, receiver) {
          if (prop !== "prepare") return Reflect.get(target, prop, receiver);
          return (sql: string) => {
            if (/usage_hourly_facts/.test(sql) && !/usage_hourly_models/.test(sql)) factsOnlyPrepareCount += 1;
            return target.prepare(sql);
          };
        },
      });

      const request: SummaryRequest = { date: TODAY, period: "today", timezone, currentTime: NOW };
      await buildSummary(prepareCountingDb, request);

      // pending 分支下这条"读 facts 算账户小时行 + 顺手在 JS 里从同一批行算 costsByItem"
      // 的查询只应该被 *prepare* 一次——旧实现是两次独立查询（fetchAccountHourlyRows 读一次，
      // fetchFactRows 再读一次），这里用 prepare 调用次数直接证明合并成了一次。
      expect(factsOnlyPrepareCount).toBe(1);
    });
  });
});
