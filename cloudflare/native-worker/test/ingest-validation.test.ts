/**
 * #90 缺口块 1：`/ingest` 写路径的认证与入参校验。
 *
 * `write-model.ts:617` 起有十来个 `WriteValidationError` 校验点，而 `ingest.test.ts`
 * 里只有 3 处 `toBe(400)` 断言、`toBe(401)` 零命中——**写路径被拒绝的那一半几乎没人守**。
 *
 * 为什么这一半要紧：写路径是唯一的数据入口。校验放宽的后果不是「报错难看」，
 * 是**脏数据静默落库**——缺 `source_id` 的事实会挂到空来源上、`schema_version`
 * 是字符串时版本判定会走进未定义分支、`usage_hourly_facts` 里缺 `window_start`
 * 的事实会落成没有时间的行。这些都不会在写入时报错，只会在读出来的时候变成错的数字。
 *
 * 认证那两条（`/ingest` 带错 token、`/ingest-limits` 未认证）已由合同 golden 钉住
 * （`golden-freshness.test.ts` 的「覆盖认证面、写入面与读端点」），这里不重复，
 * 只补合同 golden 覆盖不到的**逐条校验规则**与 **token 轮换在写路径同样有效**。
 */

import { describe, expect, it } from "vitest";
import { withWorker } from "./golden/harness";
import { fixedNow, timezone } from "./golden/paths";

type AnyRecord = Record<string, unknown>;

/** 一份**合法**的最小 payload。每条用例都从它出发只破坏一个地方。 */
function validPayload(): AnyRecord {
  return {
    schema_version: 1,
    source_id: "mac-local",
    host: "macbook-pro",
    machine: "macbook-pro",
    os_user: "alice",
    platform: "darwin",
    timezone,
    observed_at: "2026-06-03T10:40:00+08:00",
    collection_window: "hourly",
    usage_hourly_facts: [{
      fact_id: "fact-1",
      agent: "claude",
      window_start: "2026-06-03T09:00:00+08:00",
      window_end: "2026-06-03T10:00:00+08:00",
      attribution_confidence: "observed",
      provenance: "test",
      usage: { input_tokens: 100, output_tokens: 50, total_tokens: 150 },
    }],
  };
}

async function post(body: unknown, options: { auth?: boolean | string; bindings?: Record<string, string> } = {}) {
  return withWorker({ now: fixedNow, bindings: options.bindings }, async ({ fetchRaw, db }) => {
    const response = await fetchRaw({
      method: "POST", path: "/ingest", auth: options.auth ?? true, body,
    });
    const facts = await db.prepare("SELECT count(*) AS n FROM usage_hourly_facts").first<{ n: number }>();
    return {
      status: response.status,
      body: JSON.parse(response.body.toString("utf8")) as AnyRecord,
      factsWritten: Number(facts?.n ?? 0),
    };
  });
}

describe.sequential("/ingest 写路径的入参校验", () => {
  it("合法 payload 收得下并真的落库——这是下面所有拒绝断言的对照组", async () => {
    // 没有这条，「被拒绝」的断言全部可能是「这条路径根本跑不通」的假象。
    const result = await post(validPayload());
    expect(result.status, "合法 payload 必须 200").toBe(200);
    expect(result.factsWritten, "合法 payload 必须真的写进 canonical 事实表").toBe(1);
  }, 60_000);

  it("缺任何一个必填顶层字段都拒收，且一个字节都不落库", async () => {
    // 逐个删——只测其中一个的话，其余几个的校验被删掉不会有人发现。
    const required = ["schema_version", "source_id", "host", "os_user", "timezone", "observed_at"];
    let checked = 0;
    for (const field of required) {
      const payload = validPayload();
      delete payload[field];
      const result = await post(payload);
      expect(result.status, `缺 ${field} 必须 400`).toBe(400);
      expect(result.body.error_type, `缺 ${field} 的错误类型`).toBe("http_schema_invalid");
      expect(String(result.body.message), `缺 ${field} 的消息要点名字段`).toContain(field);
      // 关键：拒收之后不许留下半份数据。
      expect(result.factsWritten, `缺 ${field} 时不许落库`).toBe(0);
      checked += 1;
    }
    expect(checked, "六个必填字段都要逐个试过").toBe(required.length);
  }, 120_000);

  it("schema_version 不是整数就拒收", async () => {
    // 字符串 "1" 看起来「能用」，但版本判定后面全是数值比较，放进去会走进未定义分支。
    let checked = 0;
    for (const value of ["1", 1.5, null, true]) {
      const payload = validPayload();
      payload.schema_version = value;
      const result = await post(payload);
      expect(result.status, `schema_version=${JSON.stringify(value)} 必须 400`).toBe(400);
      expect(result.factsWritten).toBe(0);
      checked += 1;
    }
    expect(checked, "四种非整数形态都要试").toBe(4);
  }, 120_000);

  it("payload 不是 JSON 对象就拒收", async () => {
    for (const body of [[], "string", 42]) {
      const result = await post(body);
      expect(result.status, `${JSON.stringify(body)} 必须 400`).toBe(400);
      expect(result.factsWritten).toBe(0);
    }
  }, 90_000);

  it("usage_hourly_facts 形状不对就拒收：不是数组、元素不是对象、缺子字段", async () => {
    const cases: Array<[string, unknown]> = [
      ["不是数组", { fact_id: "x" }],
      ["元素不是对象", ["not-an-object"]],
    ];
    for (const [label, facts] of cases) {
      const payload = validPayload();
      payload.usage_hourly_facts = facts;
      const result = await post(payload);
      expect(result.status, `usage_hourly_facts ${label} 必须 400`).toBe(400);
      expect(result.factsWritten).toBe(0);
    }

    // 逐个删事实级必填字段：缺 window_start 的事实会落成一条没有时间的行，
    // 写入时不报错，读出来才变成错的数字。
    const factRequired = ["fact_id", "agent", "window_start", "window_end", "usage", "attribution_confidence", "provenance"];
    let checked = 0;
    for (const key of factRequired) {
      const payload = validPayload();
      const fact = (payload.usage_hourly_facts as AnyRecord[])[0];
      delete fact[key];
      const result = await post(payload);
      expect(result.status, `事实缺 ${key} 必须 400`).toBe(400);
      expect(String(result.body.message), `事实缺 ${key} 的消息要点名它`).toContain(key);
      expect(result.factsWritten, `事实缺 ${key} 时不许落库`).toBe(0);
      checked += 1;
    }
    expect(checked, "七个事实级必填字段都要逐个试过").toBe(factRequired.length);
  }, 180_000);

  it("usage 与 ai_account 必须是对象，不是就拒收", async () => {
    for (const [key, value] of [["usage", "not-an-object"], ["ai_account", 42]] as Array<[string, unknown]>) {
      const payload = validPayload();
      (payload.usage_hourly_facts as AnyRecord[])[0][key] = value;
      const result = await post(payload);
      expect(result.status, `${key} 不是对象必须 400`).toBe(400);
      expect(result.factsWritten).toBe(0);
    }
  }, 90_000);

  it("token 轮换期的第二个 token 在**写路径**同样有效", async () => {
    // 轮换期两个 token 并存。此前只有读路径用第二个 token 试过
    // （`web_surface.test.ts`），写路径没有——轮换时如果写路径只认第一个，
    // 换发之后所有设备的上报会在没人察觉的情况下开始 401。
    const bindings = { AIUSAGE_TOKEN_SPECS: "contract-test-token,rotated-second-token" };

    const accepted = await post(validPayload(), { auth: "rotated-second-token", bindings });
    expect(accepted.status, "轮换期的第二个 token 必须能写").toBe(200);
    expect(accepted.factsWritten, "而且必须真的落库").toBe(1);

    // 对照：不在轮换清单里的 token 仍然被拒——否则「都能过」也满足上面那条。
    const rejected = await post(validPayload(), { auth: "not-in-rotation", bindings });
    expect(rejected.status, "不在清单里的 token 必须 401").toBe(401);
    expect(rejected.factsWritten, "被拒之后不许落库").toBe(0);
  }, 90_000);
});
