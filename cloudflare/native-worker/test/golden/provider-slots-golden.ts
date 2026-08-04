/**
 * #74 P1：`provider_slots_golden.json` 与 macOS owner fixture 的 owner。
 *
 * 13 个离线 SQL 场景 × 2 个端点，覆盖「用量有/无 × 官方额度有/无」四种组合，
 * 以及过期、失败、只有本地估算等降级形态。macOS 客户端的 fixture 是这份 golden 的
 * mobile 半边——它必须由 owner 模块产出而不是手写，否则会和现实脱节，
 * 且脱节方向正好是「实现者以为的样子」。
 */

import { readdir } from "node:fs/promises";
import path from "node:path";
import { applySqlFile, withWorker } from "./harness";
import { fixedNow, providerSlotsScenarioDir } from "./paths";

export type ProviderSlotsRecord = {
  name: string;
  scenario: string;
  request: { method: string; path: string; auth: boolean };
  provider_slots: unknown;
  provider_usage_coverage: unknown;
};

export const providerSlotsEndpoints: Array<[endpoint: string, path: string]> = [
  ["summary", "/api/summary?date=2026-06-03&period=today"],
  ["mobile-summary", "/api/mobile/summary?date=2026-06-03&period=today"],
];

/** 场景清单从目录读，新增一个 .sql 而没重新生成 golden 会让防陈旧守卫变红。 */
export async function providerSlotsScenarios(): Promise<string[]> {
  const entries = await readdir(providerSlotsScenarioDir);
  return entries.filter((name) => name.endsWith(".sql")).map((name) => name.replace(/\.sql$/, "")).sort();
}

/**
 * 单个场景的重放。场景之间共用池化实例（#101），「干净」靠 acquireWorker 取用时的
 * resetDatabase 保证——上一条的额度窗口漏进下一条这件事，由 golden 防陈旧守卫兜底
 * （实测把重置去掉会红 15 条，正是窗口跨场景泄漏的形态）。
 */
export async function collectProviderSlotsScenario(scenario: string): Promise<ProviderSlotsRecord[]> {
  return withWorker({ now: fixedNow }, async ({ db, fetchRaw }) => {
    await applySqlFile(db, path.join(providerSlotsScenarioDir, `${scenario}.sql`));
    const collected: ProviderSlotsRecord[] = [];
    for (const [endpoint, requestPath] of providerSlotsEndpoints) {
      const response = await fetchRaw({ method: "GET", path: requestPath, auth: true });
      if (response.status !== 200) {
        throw new Error(`provider slots 场景 ${scenario}:${endpoint} 期望 200，实际 ${response.status}`);
      }
      const body = JSON.parse(response.body.toString("utf8")) as Record<string, unknown>;
      collected.push({
        name: `${scenario}:${endpoint}`,
        scenario,
        request: { method: "GET", path: requestPath, auth: true },
        provider_slots: body.provider_slots,
        provider_usage_coverage: body.provider_usage_coverage,
      });
    }
    return collected;
  });
}

export async function collectProviderSlotsRecords(): Promise<ProviderSlotsRecord[]> {
  const records: ProviderSlotsRecord[] = [];
  for (const scenario of await providerSlotsScenarios()) {
    records.push(...await collectProviderSlotsScenario(scenario));
  }
  return records;
}

/** macOS 客户端 fixture = golden 的 mobile 半边，逐字节等价，不做任何裁剪。 */
export function macosOwnerFixtureFrom(records: ProviderSlotsRecord[]): ProviderSlotsRecord[] {
  return records.filter((record) => record.name.endsWith(":mobile-summary"));
}
