/**
 * #74 P1：`value_golden.json` 的 owner。
 *
 * 这份 golden 记录的是**全部数值**（只抹易变字段），守的是读模型的口径回归：
 * 周期截断、归属守恒、来源健康折算、额度窗口采用，任何一处算错都会在这里变红。
 *
 * 以前它由 Python 读模型生成（`scripts/gen_value_golden.py`），#67 把服务端权威
 * 转移到 Worker 之后，生成端跟着转移到这里；Python 侧不再持有生成与校验逻辑。
 */

import { applySqlFile, withWorker } from "./harness";
import { fixedNow, seedSqlPath } from "./paths";
import { maskVolatile } from "./shape";

export type ValueRecord = {
  name: string;
  request: { method: string; path: string; auth: boolean };
  response: {
    status: number;
    content_type: string;
    location: string | null;
    body: unknown;
  };
};

/**
 * 请求清单是 golden 覆盖面的**唯一声明**：这里加一条而 golden 没重新生成，
 * 防陈旧守卫会因为条数与名字对不上直接变红。
 */
export const valueRequests: Array<[name: string, path: string]> = [
  ["summary-today", "/api/summary?date=2026-06-03&period=today"],
  ["mobile-summary-today", "/api/mobile/summary?date=2026-06-03&period=today"],
  ["summary-week", "/api/summary?date=2026-06-03&period=week"],
  ["mobile-summary-week", "/api/mobile/summary?date=2026-06-03&period=week"],
  ["summary-month", "/api/summary?date=2026-06-03&period=month"],
  ["mobile-summary-month", "/api/mobile/summary?date=2026-06-03&period=month"],
  ["summary-all", "/api/summary?date=2026-06-03&period=all"],
  ["mobile-summary-all", "/api/mobile/summary?date=2026-06-03&period=all"],
  ["summary-week-machine-filter", "/api/summary?date=2026-06-03&period=week&machine=macbook-pro"],
  ["mobile-summary-week-machine-filter", "/api/mobile/summary?date=2026-06-03&period=week&machine=linux-dev"],
  ["summary-week-account-filter", "/api/summary?date=2026-06-03&period=week&account=alice"],
  ["mobile-summary-week-account-filter", "/api/mobile/summary?date=2026-06-03&period=week&account=bob"],
  // seed.sql 里已含官方额度观测，这两条与上面的 week 请求同参数，
  // 记录的是「额度已入库」这条路径下 summary / mobile 的完整取值。
  ["summary-week-observed-limits", "/api/summary?date=2026-06-03&period=week"],
  ["mobile-summary-week-observed-limits", "/api/mobile/summary?date=2026-06-03&period=week"],
];

export async function collectValueGoldenRecords(): Promise<ValueRecord[]> {
  return withWorker({ now: fixedNow }, async ({ db, fetchRaw }) => {
    await applySqlFile(db, seedSqlPath);

    const records: ValueRecord[] = [];
    for (const [name, requestPath] of valueRequests) {
      const response = await fetchRaw({ method: "GET", path: requestPath, auth: true });
      if (response.status !== 200) {
        throw new Error(`value golden 请求 ${name} 期望 200，实际 ${response.status}`);
      }
      records.push({
        name,
        request: { method: "GET", path: requestPath, auth: true },
        response: {
          status: response.status,
          content_type: response.contentType.split(";")[0],
          location: response.location,
          body: maskVolatile(JSON.parse(response.body.toString("utf8"))),
        },
      });
    }
    return records;
  });
}
