/**
 * #74 P1：`value_golden.json` 与 `api_contract_golden.json` 的防陈旧守卫。
 *
 * 这类 golden 有一个静默失效模式：读模型新增字段后没人重新生成 golden，
 * 于是 golden 停止守护那个字段，而消费它的测试因为「两边都没有新字段」继续报绿——
 * 测试全绿，守护范围却在悄悄缩小。#63 实测发生过一次。
 *
 * 所以生成逻辑的 owner 是 `test/golden/` 下的收集器，`npm run cf:golden:gen` 反过来
 * 调它们；本文件每次都重新生成一遍并与已提交的 golden 逐条比对。变红时的正确动作是
 * **复核 diff 后重新生成**，不是放宽这里的断言。
 *
 * 每条比对断言都配了一条**结构下限**：只断言「一致」是穿得过去的——收集器返回空数组时
 * 「什么都没比」和「比了且全过」产生同一个绿。
 */

import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { collectApiContractRecords, type ContractRecord } from "./golden/api-contract-golden";
import { apiContractGoldenPath, token, valueGoldenPath } from "./golden/paths";
import { diffPaths, formatDiffs } from "./golden/shape";
import { collectValueGoldenRecords, valueRequests, type ValueRecord } from "./golden/value-golden";

type AnyRecord = Record<string, unknown>;

const regenerateHint = "复核下列差异后重新生成：npm run cf:golden:gen";

// 合同 golden 里绝不允许出现的运行时痕迹。token 泄进 fixture 等于把凭据提交进 Git。
const sensitiveSubstrings = [
  token,
  "/Users/",
  "/private/",
  "/tmp/",
  ".claude",
  ".codex",
  "BEGIN OPENSSH",
];

describe.sequential("golden 防陈旧守卫", () => {
  it("value_golden.json 等于此刻 Worker 重放出来的结果", async () => {
    const committed = JSON.parse(await readFile(valueGoldenPath, "utf8")) as ValueRecord[];
    const regenerated = await collectValueGoldenRecords();

    // 结构下限：先证明「确实比了东西」，再证明「比下来一致」。
    expect(regenerated.length, "重放条数").toBe(valueRequests.length);
    expect(regenerated.length, "value golden 至少要覆盖 14 条请求").toBeGreaterThanOrEqual(14);
    expect(committed.map((record) => record.name), "golden 覆盖的请求集合必须与 valueRequests 一致")
      .toEqual(valueRequests.map(([name]) => name));

    const diffs = diffPaths(committed, regenerated);
    if (diffs.length > 0) {
      throw new Error(
        `cloudflare/native-worker/test/value_golden.json 已经陈旧（${diffs.length} 处差异），`
        + "不再等于 Worker 读模型当前的输出——它正在停止守护下列字段。\n"
        + `${regenerateHint}\n${formatDiffs(diffs)}`,
      );
    }
  }, 120_000);

  it("value_golden 的重放是确定的（同一份 fixture 连跑两次完全相同）", async () => {
    // 守卫本身不许随机红：固定时间 + 固定时区 + 抹掉易变字段，三条只要有一条没做到，
    // 上面那条防陈旧断言就会变成噪音，很快会被人当成误报关掉。
    const first = await collectValueGoldenRecords();
    const second = await collectValueGoldenRecords();
    expect(first.length, "重放必须产出记录").toBeGreaterThan(0);
    const diffs = diffPaths(first, second);
    if (diffs.length > 0) {
      throw new Error(`重放结果不确定（${diffs.length} 处差异），说明还有易变字段没被固定或抹掉：\n${formatDiffs(diffs)}`);
    }
  }, 120_000);

  it("value_golden 覆盖到真实的降级形态，不是一份全空快照", async () => {
    const committed = JSON.parse(await readFile(valueGoldenPath, "utf8")) as ValueRecord[];
    const summaryWeek = bodyOf(committed, "summary-week");
    const mobileWeek = bodyOf(committed, "mobile-summary-week");

    const sourceStatus = summaryWeek.source_status as AnyRecord[];
    expect(sourceStatus.length, "source_status 必须非空").toBeGreaterThan(0);
    expect(sourceStatus.map((row) => row.status), "必须覆盖健康来源").toContain("ok");
    // 全新鲜的 fixture 下「过期折算」这条口径会退化成恒等变换，golden 什么都守不住。
    expect(sourceStatus.map((row) => row.status), "必须覆盖过期来源").toContain("stale");

    const mobileSources = mobileWeek.sources as AnyRecord[];
    expect(mobileSources.length, "mobile sources 必须非空").toBeGreaterThan(0);
    expect(mobileSources.map((row) => row.status), "mobile 必须覆盖过期来源").toContain("stale");

    const windows = (mobileWeek.limits as AnyRecord).windows as AnyRecord[];
    expect(windows.length, "mobile 额度窗口必须被覆盖").toBeGreaterThan(0);
    expect(
      windows.every((row) => row.official === true && row.confidence === "observed" && row.status === "ok"),
      "mobile 只展示可信官方额度",
    ).toBe(true);

    // 先证明这个循环真的会跑：数组为空时下面的循环体一次都不执行，
    // 「每台机器都带 source_ids」和「一台机器都没有」会产生同一个绿。
    const machines = (summaryWeek.groups as AnyRecord).by_machine as AnyRecord[];
    expect(machines.length, "groups.by_machine 必须非空，否则下面的逐台断言什么都没检查").toBeGreaterThan(0);
    for (const machine of machines) {
      const sourceIds = (machine.source_ids ?? []) as string[];
      expect(sourceIds.length, `groups.by_machine ${String(machine.name)} 必须带 source_ids`).toBeGreaterThan(0);
      const fromUsers = ((machine.users as AnyRecord[]) ?? []).flatMap((user) => (user.source_ids as string[]) ?? []);
      expect(sourceIds, `${String(machine.name)} 的 source_ids 必须涵盖其下所有用户`).toEqual(
        expect.arrayContaining(fromUsers),
      );
    }
  });

  it("value_golden 的周期语义从请求参数独立复算，不看读模型怎么算的", async () => {
    // 这是补 `npm run cf:golden:gen` 这条逃生口的第一道。防陈旧比对的生成端与校验端
    // 是同一份实现，所以「改读模型 + 顺手重新生成」必然全绿——实测过两个产品可见的
    // 口径事故都能这样零信号穿过去：week 窗口从 7 天缩成 6 天、mobile 缓存占比算少。
    //
    // 这里的判据完全来自**请求参数**（date + period），与读模型的实现无关：
    // 周期边界是产品定义，不是实现细节。read-model 把 -6 改成 -5，这条立刻红。
    const committed = JSON.parse(await readFile(valueGoldenPath, "utf8")) as ValueRecord[];
    const day = (base: string, delta: number) => {
      const stamp = new Date(`${base}T00:00:00Z`);
      stamp.setUTCDate(stamp.getUTCDate() + delta);
      return stamp.toISOString().slice(0, 10);
    };
    // period → [start_date 相对请求日期的偏移（null = 不设下界）, trend 点数]
    const periodRules: Record<string, { startOffset: number; trendPoints: number }> = {
      today: { startOffset: 0, trendPoints: 24 },   // 当日按小时
      week: { startOffset: -6, trendPoints: 7 },    // 含今天在内的 7 天
      month: { startOffset: -29, trendPoints: 30 }, // 含今天在内的 30 天
    };

    let checked = 0;
    for (const record of committed) {
      const url = new URL(`http://native.test${record.request.path}`);
      const date = url.searchParams.get("date")!;
      const period = url.searchParams.get("period")!;
      const body = record.response.body as AnyRecord;
      // web 的边界在 summary 里，mobile 的在 period 里——两个端点都要核。
      const window = (body.summary ?? body.period) as AnyRecord;
      const rule = periodRules[period];

      if (rule) {
        expect(window.start_date, `${record.name} 的 start_date 必须等于 ${period} 的产品定义边界`)
          .toBe(day(date, rule.startOffset));
        const points = ((body.trend as AnyRecord)?.points as unknown[]) ?? [];
        expect(points.length, `${record.name} 的 trend 点数必须是 ${period} 的定义长度`)
          .toBe(rule.trendPoints);
      } else {
        expect(period, "只认识 today/week/month/all 四个周期").toBe("all");
        expect(window.start_date, `${record.name}：all 不设下界`).toBeNull();
      }
      expect(window.end_date, `${record.name} 的 end_date 必须是请求日期`).toBe(date);
      checked += 1;
    }
    // 只留确切条数这一条：`checked === committed.length` 在循环里恒成立，断言它等于没断言。
    expect(checked, "必须逐条核到全部 14 条记录").toBe(14);
  });

  it("value_golden 里 web 与 mobile 对同一组请求必须给出同一份口径", async () => {
    // 两个端点的数值由两份实现算出（read-model.ts 与 mobile-summary.ts），
    // 而它们都在这份 golden 里。让它们互相核对，就得到一条**不依赖 golden 与读模型
    // 一致**的独立恒等式：只改其中一侧（实测过 mobile 的 cacheTokens 丢掉
    // cache_read），regenerate 之后两侧对不上，这里就红。
    const committed = JSON.parse(await readFile(valueGoldenPath, "utf8")) as ValueRecord[];
    const byName = new Map(committed.map((record) => [record.name, record]));
    // 只配对**请求参数完全相同**的：machine/account 过滤那两组两侧刻意用了不同的值。
    const pairs = [
      ["summary-today", "mobile-summary-today"],
      ["summary-week", "mobile-summary-week"],
      ["summary-month", "mobile-summary-month"],
      ["summary-all", "mobile-summary-all"],
      ["summary-week-observed-limits", "mobile-summary-week-observed-limits"],
    ];

    let checked = 0;
    for (const [webName, mobileName] of pairs) {
      const web = (byName.get(webName)!.response.body as AnyRecord).summary as AnyRecord;
      const mobile = (byName.get(mobileName)!.response.body as AnyRecord).period as AnyRecord;
      expect(new URL(`http://x${byName.get(webName)!.request.path}`).search,
        `${webName} 与 ${mobileName} 必须是同一组请求参数`)
        .toBe(new URL(`http://x${byName.get(mobileName)!.request.path}`).search);

      for (const key of ["total_tokens", "input_tokens", "output_tokens"]) {
        expect(Number(mobile[key]), `${mobileName}.${key} 必须与 ${webName} 一致`).toBe(Number(web[key]));
      }
      // mobile 把两类缓存合成一个 cache_tokens；少合一类就是这里对不上。
      expect(Number(mobile.cache_tokens), `${mobileName}.cache_tokens 必须等于 web 两类缓存之和`)
        .toBe(Number(web.cache_creation_tokens) + Number(web.cache_read_tokens));
      checked += 1;
    }
    expect(checked, "五对都必须核到").toBe(pairs.length);
  });

  it("value_golden 的聚合恒等式从产物独立算一遍", async () => {
    // 逐条明细之和必须等于总量。周期截断把整行删掉时，那一行的分量与 total 一起消失，
    // 上面那条「行内四分量分解」照样成立——所以还需要这条跨行的。
    const committed = JSON.parse(await readFile(valueGoldenPath, "utf8")) as ValueRecord[];
    let webChecked = 0;
    let mobileChecked = 0;
    for (const record of committed) {
      const body = record.response.body as AnyRecord;
      const items = body.items as AnyRecord[] | undefined;
      if (items) {
        const total = items.reduce((sum, row) => sum + Number(row.total_tokens ?? 0), 0);
        expect(total, `${record.name}：items 之和必须等于 summary.total_tokens`)
          .toBe(Number((body.summary as AnyRecord).total_tokens));
        webChecked += 1;
      }
      const byAgent = ((body.breakdown as AnyRecord)?.by_agent as AnyRecord[]) ?? null;
      if (byAgent) {
        const total = byAgent.reduce((sum, row) => sum + Number(row.tokens ?? 0), 0);
        expect(total, `${record.name}：by_agent 之和必须等于 period.total_tokens`)
          .toBe(Number((body.period as AnyRecord).total_tokens));
        mobileChecked += 1;
      }
    }
    // 结构下限用**确切条数**：`> 0` 会被 web 那 7 条满足，mobile 半边整体漏掉也不会红。
    expect(webChecked, "web 半边 7 条都要核到").toBe(7);
    expect(mobileChecked, "mobile 半边 7 条都要核到").toBe(7);
  });

  it("value_golden 不含任何运行时敏感数据", async () => {
    // value golden 记录的是全量响应（含 sources[].error_message），泄漏面比 shape golden 大。
    const raw = await readFile(valueGoldenPath, "utf8");
    expect(raw.length, "golden 不能是空文件").toBeGreaterThan(1000);
    for (const value of sensitiveSubstrings) {
      expect(raw.includes(value), `golden 不得包含 ${value}`).toBe(false);
    }
  });

  it("value_golden 的 token 守恒等式从产物独立算一遍", async () => {
    // 这条断言存在的理由，是 golden 变成 self-referential 之后留下的那个洞：
    // 「改读模型 + 顺手 npm run cf:golden:gen」会让上面那条防陈旧比对必然变绿
    // （生成端与校验端是同一份实现），于是一个纯数值口径回归可以零信号地穿过去。
    // 实测过：把 read-model 的 `cacheReadTokens += cacheRead` 改成 `+= 0`，
    // 重新生成 golden 之后 109 条测试全绿。
    //
    // 所以这里**不重放读模型**，只从已提交的产物里独立复算一个恒等式：
    // 四个分量之和必须等于 total。分量少算而 total 另有来路时，两边会立刻对不上。
    const committed = JSON.parse(await readFile(valueGoldenPath, "utf8")) as ValueRecord[];
    const parts = ["input_tokens", "output_tokens", "cache_creation_tokens", "cache_read_tokens"];
    const sumParts = (row: AnyRecord) => parts.reduce((sum, key) => sum + Number(row[key] ?? 0), 0);

    let checkedSummaries = 0;
    let checkedItems = 0;
    for (const record of committed) {
      const body = record.response.body as AnyRecord;
      const summary = body.summary as AnyRecord | undefined;
      if (summary && summary.total_tokens !== undefined) {
        expect(sumParts(summary), `${record.name} 的 summary 分量之和必须等于 total_tokens`)
          .toBe(Number(summary.total_tokens));
        checkedSummaries += 1;
      }
      for (const item of (body.items as AnyRecord[]) ?? []) {
        if (item.total_tokens === undefined) continue;
        expect(sumParts(item), `${record.name} 的 items 分量之和必须等于 total_tokens`)
          .toBe(Number(item.total_tokens));
        checkedItems += 1;
      }
    }

    // 结构下限：golden 一旦退化成空壳，上面两个循环一次都不跑，「守恒成立」与
    // 「什么都没核」会产生同一个绿。
    expect(checkedSummaries, "必须真的核到 summary").toBeGreaterThan(0);
    expect(checkedItems, "必须真的核到逐条 items").toBeGreaterThan(0);
  });

  it("api_contract_golden.json 等于此刻 Worker 实录出来的结果", async () => {
    const committed = JSON.parse(await readFile(apiContractGoldenPath, "utf8")) as ContractRecord[];
    const regenerated = await collectApiContractRecords();

    expect(regenerated.length, "合同记录条数（新增记录必须同时进入比对）").toBe(35);
    expect(committed.map((record) => record.name), "golden 的记录名与实录顺序必须一致")
      .toEqual(regenerated.map((record) => record.name));

    const diffs = diffPaths(committed, regenerated);
    if (diffs.length > 0) {
      throw new Error(
        `tests/fixtures/contract/api_contract_golden.json 已经陈旧（${diffs.length} 处差异）。\n`
        + `${regenerateHint}\n${formatDiffs(diffs)}`,
      );
    }
  }, 120_000);

  it("api_contract_golden 的实录是确定的", async () => {
    const first = await collectApiContractRecords();
    const second = await collectApiContractRecords();
    expect(first.length, "实录必须产出记录").toBe(35);
    const diffs = diffPaths(first, second);
    if (diffs.length > 0) {
      throw new Error(`实录结果不确定（${diffs.length} 处差异）：\n${formatDiffs(diffs)}`);
    }
  }, 120_000);

  it("api_contract_golden 覆盖认证面、写入面与读端点，且读端点不是空结构", async () => {
    const committed = JSON.parse(await readFile(apiContractGoldenPath, "utf8")) as ContractRecord[];
    const byName = new Map(committed.map((record) => [record.name, record]));

    // 未认证面：三个读端点 + 写端点 + 静态资源都必须有「不给看」的记录。
    for (const name of [
      "summary-requires-auth",
      "mobile-summary-requires-auth",
      "health-requires-auth",
      "static-css-requires-auth",
      "ingest-limits-requires-auth",
    ]) {
      expect(byName.get(name)?.response.status, `${name} 必须记录 401`).toBe(401);
    }
    expect(byName.get("ingest-auth-failed")?.response.status, "带错误 token 的写入必须 401").toBe(401);
    expect(byName.get("ingest-schema-invalid")?.response.status, "非法 payload 必须 400").toBe(400);
    expect(byName.get("ingest-limits-schema-invalid")?.response.status, "非法额度 payload 必须 400").toBe(400);
    expect(byName.get("login-valid-redirect")?.response.status, "登录成功必须是重定向").toBe(303);

    // 读端点不能是「什么都没有」——空结构下这份 shape golden 守不住任何字段。
    const summaryWeek = fieldsOf(byName.get("summary-week-missing-limits"));
    expect(Number(node(summaryWeek.items).length), "summary items 必须非空").toBeGreaterThan(0);
    expect(Number(node(summaryWeek.ai_accounts).length), "ai_accounts 必须非空").toBeGreaterThan(0);
    // 用 length 而不是 items：`by_machine` 整个字段消失时 items 会是 undefined，
    // 而 `expect(undefined).not.toEqual([])` 是通过的——那正是这条断言要拦的形态。
    // `Number(undefined)` 是 NaN，`NaN > 0` 为假，会红。
    expect(
      Number(node(subFields(summaryWeek.groups).by_machine).length),
      "groups.by_machine 必须非空且记录到元素结构",
    ).toBeGreaterThan(0);

    // `/api/health` 场景必须一直带一台过期设备：全新鲜时折算与不折算产出相同的 counts，
    // 这条口径会在 golden 里静音。
    for (const name of ["health-before-limits", "health-after-limits"]) {
      const sourceStatus = subFields(fieldsOf(byName.get(name)).source_status);
      expect(node(sourceStatus.counts).keys, `${name} 的 counts 必须含过期设备`).toContain("stale");
      const nonOkStatuses = ((node(sourceStatus.non_ok).items ?? []) as AnyRecord[]).map(
        (item) => node(subFields(item).status).value,
      );
      expect(nonOkStatuses, `${name} 的 non_ok 必须点名过期设备`).toContain("stale");
    }
  });

  it("api_contract_golden 不含任何运行时敏感数据", async () => {
    const raw = await readFile(apiContractGoldenPath, "utf8");
    expect(raw.length, "golden 不能是空文件").toBeGreaterThan(1000);
    for (const value of sensitiveSubstrings) {
      expect(raw.includes(value), `golden 不得包含 ${value}`).toBe(false);
    }
  });
});

function bodyOf(records: ValueRecord[], name: string): AnyRecord {
  const record = records.find((item) => item.name === name);
  expect(record, `${name} 必须在 golden 里`).toBeTruthy();
  return record!.response.body as AnyRecord;
}

/** shape 节点本身（`{type, keys, fields}` / `{type, length, items}`）。 */
function node(value: unknown): AnyRecord {
  return (value ?? {}) as AnyRecord;
}

/** 某个 shape 节点下的字段表。 */
function subFields(value: unknown): AnyRecord {
  return (node(value).fields ?? {}) as AnyRecord;
}

/** 一条合同记录的 JSON body 顶层字段表。 */
function fieldsOf(record: ContractRecord | undefined): AnyRecord {
  expect(record, "合同记录必须存在").toBeTruthy();
  return subFields((record!.response.body as AnyRecord).shape);
}
