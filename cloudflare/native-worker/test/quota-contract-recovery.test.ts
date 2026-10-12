import { describe, expect, it } from "vitest";
import { withWorker } from "./golden/harness";
import { fixedNow } from "./golden/paths";
import { parseLimitWindow } from "../src/write-model/validate";
import { buildLimitStatus } from "../src/read-model/limits-select";
import { providerQuotaSlot } from "../src/read-model/provider-slots";
import type { LimitRow } from "../src/read-model/shared";

function measured(changes: Record<string, unknown> = {}) {
  return {provider: "claude", source_id: "synthetic-claude", window: "week", used_percent: 33,
    remaining_percent: 67, reset_at: "2026-06-10T12:00:00+08:00", window_duration_minutes: 10080,
    observed_at: "2026-06-03T11:00:00+08:00", source_type: "official_cli", confidence: "observed", status: "ok", ...changes};
}
const failed = () => measured({window: "unknown", used_percent: 0, remaining_percent: 0, window_duration_minutes: 0,
  observed_at: "2026-06-03T11:30:00+08:00", reset_at: "2026-06-03T11:30:00+08:00",
  source_type: "provider_runtime", confidence: "missing", status: "provider_failed"});

describe.sequential("额度测量存在性与网络失败恢复", () => {
  it("不完整成功观测整包拒绝且无写入，真实0和失败占位仍可上报", async () => {
    await withWorker({now: fixedNow}, async ({fetchRaw, db}) => {
      for (const fields of [["used_percent"], ["remaining_percent"], ["used_percent", "remaining_percent"]]) {
        for (const shape of ["missing", "null"]) {
          const bad: Record<string, unknown> = measured();
          for (const field of fields) { if (shape === "missing") delete bad[field]; else bad[field] = null; }
          const response = await fetchRaw({method: "POST", path: "/ingest-limits", auth: true,
            body: {schema_version: 1, observed_at: bad.observed_at, windows: [measured(), bad]}});
          expect(response.status, `${fields} ${shape}`).toBe(400);
          expect(JSON.parse(response.body.toString("utf8")).error_type).toBe("limit_schema_invalid");
          for (const table of ["limit_windows", "limit_window_history"]) {
            expect(await db.prepare(`SELECT count(*) AS n FROM ${table}`).first()).toEqual({n: 0});
          }
        }
      }
      for (const window of [measured({used_percent: 0, remaining_percent: 100}),
        measured({used_percent: 100, remaining_percent: 0}), measured({used_percent: 0, remaining_percent: 0}), failed()]) {
        const response = await fetchRaw({method: "POST", path: "/ingest-limits", auth: true,
          body: {schema_version: 1, observed_at: window.observed_at, windows: [window]}});
        expect(response.status).toBe(200);
      }
    });
  }, 60_000);

  it("非有限值不是测量数字", () => {
    for (const field of ["used_percent", "remaining_percent"]) {
      for (const value of [NaN, Infinity, -Infinity]) expect(() => parseLimitWindow(measured({[field]: value}))).toThrow();
    }
  });

  it("近期失败只在独立历史字段保留本来源成功值，过期/重置/估算不进入历史字段", () => {
    const now = new Date("2026-06-03T12:00:00+08:00");
    const success = {...measured(), official: true} as LimitRow;
    const failure = {...failed(), official: false} as LimitRow;
    const rows = [success, failure];
    const quota = providerQuotaSlot(rows, buildLimitStatus(rows, now)[0], now);
    expect(quota).toMatchObject({status: "missing", reason: "unavailable", windows: [],
      last_verified_at: success.observed_at, source_id: success.source_id, last_successful_windows: [success]});
    const future = [{...success, observed_at: "2026-06-03T12:30:00+08:00"},
      {...failure, observed_at: "2026-06-03T12:45:00+08:00", reset_at: "2026-06-03T12:45:00+08:00"}];
    const futureQuota = providerQuotaSlot(future, buildLimitStatus(future, now)[0], now);
    expect(futureQuota.last_successful_windows ?? []).toEqual([]);
    for (const changes of [{observed_at: "2026-06-03T09:00:00+08:00"},
      {reset_at: "2026-06-03T11:59:00+08:00"}, {official: false, confidence: "estimated"}, {source_id: "another-account"}]) {
      const altered = [{...success, ...changes}, failure];
      const unavailable = providerQuotaSlot(altered, {source_id: failure.source_id, status: "unavailable"}, now);
      expect(unavailable.windows).toEqual([]);
      expect(unavailable.last_successful_windows ?? []).toEqual([]);
    }
  });

  it("真实路由成功→失败→恢复→旧失败补报，历史值不成为当前可用额度", async () => {
    await withWorker({now: fixedNow}, async ({fetchRaw}) => {
      const push = async (window: Record<string, unknown>) => {
        const result = await fetchRaw({method: "POST", path: "/ingest-limits", auth: true,
          body: {schema_version: 1, observed_at: window.observed_at, windows: [window]}});
        expect(result.status).toBe(200);
      };
      const read = async () => {
        const result = await fetchRaw({path: "/api/mobile/summary?period=today&offset=0", auth: true});
        expect(result.status).toBe(200);
        const summary = JSON.parse(result.body.toString("utf8"));
        return summary.provider_slots.find((s: {provider: string}) => s.provider === "claude").quota;
      };
      await push(measured());
      expect(await read()).toMatchObject({status: "available", windows: [{used_percent: 33}]});
      await push(failed());
      expect(await read()).toMatchObject({status: "missing", windows: [], last_successful_windows: [{used_percent: 33}]});
      await push(measured({observed_at: "2026-06-03T11:45:00+08:00", used_percent: 35, remaining_percent: 65}));
      expect(await read()).toMatchObject({status: "available", windows: [{used_percent: 35}], last_verified_at: "2026-06-03T11:45:00+08:00"});
      await push(failed());
      expect(await read()).toMatchObject({status: "available", windows: [{used_percent: 35}]});
    });
  }, 60_000);
});
