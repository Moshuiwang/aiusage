/**
 * `provider_slots_golden.json` 的防陈旧守卫（Issue #61 验收 6 → #74 P1 转由 Worker owner）。
 *
 * 13 个离线 SQL 场景 × 2 个端点，覆盖「用量有/无 × 官方额度有/无」四种组合，以及过期、
 * 失败、只有本地估算等降级形态。以前 golden 由 Python 读模型生成、Worker 只做消费方比对；
 * #67 把服务端权威转移到 Worker 之后，生成端与守卫都在这里，
 * `npm run cf:golden:gen` 调的是同一份收集器——同一个行为只允许有一份实现。
 *
 * 每个场景一个 it()：全部塞进一个 it 会顶到 vitest 的 testTimeout，
 * CI 一慢就红，而且红出来的现场看着像合同破了，其实只是超时。
 */

import { readFileSync } from "node:fs";
import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";
import { macosOwnerFixturePath, providerSlotsGoldenPath } from "./golden/paths";
import {
  collectProviderSlotsScenario,
  macosOwnerFixtureFrom,
  providerSlotsEndpoints,
  providerSlotsScenarios,
  type ProviderSlotsRecord,
} from "./golden/provider-slots-golden";
import { diffPaths, formatDiffs } from "./golden/shape";

// 收集阶段就要知道有哪些 scenario，才能一个 scenario 生成一个 it()。
const golden = JSON.parse(readFileSync(providerSlotsGoldenPath, "utf8")) as ProviderSlotsRecord[];
const goldenScenarios = [...new Set(golden.map((record) => record.scenario))].sort();

describe.sequential("provider slots golden 防陈旧守卫", () => {
  it("golden 覆盖的场景集合等于磁盘上的 SQL 场景集合", async () => {
    // 新增一个 .sql 而没重新生成 golden，或者删掉一个 .sql 而 golden 还留着记录，
    // 都会在这里变红——否则新场景会静默地不被任何断言覆盖。
    expect(goldenScenarios, "golden 场景清单与 provider_slots/ 目录必须一致").toEqual(await providerSlotsScenarios());
    // 再钉一份字面清单：只比「golden 与目录一致」时，把一个场景连同它的 golden 记录一起删掉
    // 是全绿的——覆盖面缩小不会有任何人发现。删场景必须改到这一行。
    expect(goldenScenarios, "场景清单变化必须显式改这里").toEqual([
      "01-usage-and-quota",
      "02-usage-without-quota",
      "03-quota-without-usage",
      "04-neither",
      "05-codex-quota-only",
      "06-expired-official-quota",
      "07-provider-failed-after-success",
      "08-stale-official-with-local-estimate",
      "09-local-estimate-only",
      "10-estimated-observation-newer-than-official",
      "11-aggregate-agent-with-canonical-provider",
      "12-naive-limit-timestamps",
      "13-third-party-provider-without-slot",
      "14-usage-without-canonical-provider",
      "15-two-accounts-one-provider",
    ]);
    expect(golden.length, "每个场景两个端点").toBe(goldenScenarios.length * providerSlotsEndpoints.length);
    for (const record of golden) {
      expect(Array.isArray(record.provider_slots), `${record.name} 必须有槽位数组`).toBe(true);
      expect(record.provider_usage_coverage, `${record.name} 必须有覆盖率`).toBeTruthy();
    }
  });

  for (const scenario of goldenScenarios) {
    it(`golden 的 ${scenario} 等于此刻 Worker 重放的结果`, async () => {
      const expected = golden.filter((record) => record.scenario === scenario);
      expect(expected.length, `${scenario} 在 golden 里必须有两个端点的记录`).toBe(providerSlotsEndpoints.length);

      const actual = await collectProviderSlotsScenario(scenario);
      const diffs = diffPaths(expected, actual, scenario);
      if (diffs.length > 0) {
        throw new Error(
          `provider_slots_golden.json 的 ${scenario} 已经陈旧（${diffs.length} 处差异）。\n`
          + `复核下列差异后重新生成：npm run cf:golden:gen\n${formatDiffs(diffs)}`,
        );
      }
    }, 60_000);
  }

  it("macOS owner fixture 就是 golden 的 mobile 半边，没有第二份手写事实", async () => {
    // 手写 fixture 会和现实脱节，且脱节方向正好是「实现者以为的样子」。
    // golden 的新鲜度由上面每个场景的重放保证，这里只需钉住「fixture 由 owner 派生」。
    const committed = JSON.parse(await readFile(macosOwnerFixturePath, "utf8")) as ProviderSlotsRecord[];
    const derived = macosOwnerFixtureFrom(golden);

    expect(derived.length, "mobile 半边必须与场景数一致").toBe(goldenScenarios.length);
    expect(derived.length, "场景数变化必须显式改这里").toBe(15);
    expect(derived.length, "派生结果不能为空").toBeGreaterThan(0);
    expect(committed.map((record) => record.name), "fixture 覆盖的场景必须与 golden 一致")
      .toEqual(derived.map((record) => record.name));

    const diffs = diffPaths(committed, derived, "macos-fixture");
    if (diffs.length > 0) {
      throw new Error(
        `macOS owner fixture 与 golden 的 mobile 半边不一致（${diffs.length} 处差异）。\n`
        + `复核后重新生成：npm run cf:golden:gen\n${formatDiffs(diffs)}`,
      );
    }
  });

  it("每个场景的槽位与覆盖率互相不矛盾（守恒等式从产物独立算一遍）", () => {
    // 要守的不变量是**用户能看到的**那份：槽位之和 + 明确点名的余量 == 该周期总量。
    // 固定槽位只有 claude / codex，任何进不了槽位的 token（第三方 provider、完全无法归属）
    // 都必须被单独点名，不能藏在 attributed_tokens 里冒充「已展示」。
    let checked = 0;
    for (const record of golden) {
      const coverage = record.provider_usage_coverage as Record<string, number | string>;
      const slots = record.provider_slots as Array<{ usage: { total_tokens: number } }>;
      const slotTokens = slots.reduce((sum, row) => sum + row.usage.total_tokens, 0);
      expect(coverage.attributed_tokens, `${record.name} 归属量`).toBe(slotTokens);
      expect(
        slotTokens + Number(coverage.other_provider_tokens) + Number(coverage.unattributed_tokens),
        `${record.name} 守恒等式`,
      ).toBe(coverage.total_tokens);
      expect(coverage.status, `${record.name} 覆盖状态`).toBe(
        Number(coverage.other_provider_tokens) === 0 && Number(coverage.unattributed_tokens) === 0
          ? "complete"
          : "partial",
      );
      checked += 1;
    }
    expect(checked, "守恒等式必须真的核了每一条记录").toBe(golden.length);
  });

  it("四种用量×额度组合、五种额度缺失原因都在 golden 里出现过", () => {
    const combinations = new Set<string>();
    const reasons = new Set<string>();
    for (const record of golden) {
      const slots = record.provider_slots as Array<{
        provider: string;
        usage: { status: string };
        quota: { status: string; reason: string | null };
      }>;
      const claude = slots.find((row) => row.provider === "claude");
      expect(claude, `${record.name} 必须有 claude 槽位`).toBeTruthy();
      combinations.add(`${claude!.usage.status}/${claude!.quota.status}`);
      for (const slot of slots) {
        if (slot.quota.status === "missing" && slot.quota.reason) reasons.add(slot.quota.reason);
      }
    }
    expect([...combinations].sort()).toEqual([
      "available/available",
      "available/missing",
      "missing/available",
      "missing/missing",
    ]);
    expect([...reasons].sort()).toEqual(["expired", "no_data", "stale", "unavailable", "unverified"]);
  });

  it("额度缺失时绝不携带百分比或重置时刻", () => {
    let checked = 0;
    for (const record of golden) {
      for (const slot of record.provider_slots as Array<{ provider: string; quota: Record<string, unknown> }>) {
        if (slot.quota.status !== "missing") continue;
        checked += 1;
        expect(slot.quota.windows, `${record.name} / ${slot.provider}`).toEqual([]);
        expect("last_verified_at" in slot.quota, `${record.name} / ${slot.provider} 必须显式声明未验证时刻`).toBe(true);
        const serialized = JSON.stringify(slot.quota);
        for (const leaked of ["used_percent", "remaining_percent", "reset_at"]) {
          expect(serialized.includes(leaked), `${record.name} / ${slot.provider} 泄漏了 ${leaked}`).toBe(false);
        }
      }
    }
    expect(checked, "必须真的检查到 missing 额度").toBeGreaterThan(0);
  });

  it("本地估算的新鲜度不得冒充官方验证时间", () => {
    const byName = new Map(golden.map((record) => [record.name, record]));
    for (const [endpoint] of providerSlotsEndpoints) {
      const stale = claudeQuota(byName.get(`08-stale-official-with-local-estimate:${endpoint}`)!);
      expect(stale.last_verified_at).toBe("2026-06-01T09:00:00+08:00");
      expect(stale.source_type).toBe("oauth_usage_api");

      const estimateOnly = claudeQuota(byName.get(`09-local-estimate-only:${endpoint}`)!);
      expect(estimateOnly.reason).toBe("unverified");
      expect(estimateOnly.last_verified_at).toBeNull();
    }
  });

  it("同一 provider 下两个账号时只展示最新观测的那个，不许把两份百分比混在一起", () => {
    // #90 块 12。`selectedLimitSources`（mobile 侧择优）与 `bestLimitWindows`（读侧去重）
    // 在测试里原本零命中——同 provider 多 source_id 只在 08 号出现过一次，
    // 而那是「官方 vs 本地估算」，不是两个真实账号。
    // 不择优的后果是两个账号的百分比混在一起：用户看到的数字既不是 A 的也不是 B 的。
    const byName = new Map(golden.map((record) => [record.name, record]));
    for (const [endpoint] of providerSlotsEndpoints) {
      const record = byName.get(`15-two-accounts-one-provider:${endpoint}`);
      expect(record, `15 号场景的 ${endpoint} 记录必须存在`).toBeTruthy();
      const claude = (record!.provider_slots as Array<{ provider: string; quota: Record<string, any> }>)
        .find((row) => row.provider === "claude")!;

      expect(claude.quota.status, "择优之后额度是可用的").toBe("available");
      // 结构下限：必须**恰好一条**。两条就是混在一起，零条就是这条路径根本没跑到。
      expect(claude.quota.windows, "同 provider 只能展示一个账号的窗口").toHaveLength(1);
      const shown = claude.quota.windows[0];
      expect(shown.source_id, "展示的必须是观测时刻更新的那个账号").toBe("claude-second");
      expect(shown.used_percent, "展示的百分比来自 claude-second").toBe(40);
      // 另一个账号的数字绝不能出现在任何地方——混进去比不显示更糟。
      expect(JSON.stringify(claude.quota).includes("78.25"), "claude-main 的百分比不许泄漏").toBe(false);
      expect(JSON.stringify(claude.quota).includes("claude-main"), "claude-main 不许出现").toBe(false);
    }
  });

  it("完全无法归属的用量被点名进 unattributed，而不是静默消失", () => {
    // #90 块 11。前 13 个场景里 `unattributed_tokens` 恒为 0——守恒等式的最后一项
    // 从未被激活，「归属不出 provider 的用量」这半边等于没有断言。而它正是最难发现的
    // 一类错：token 既进不了槽位、也没被点名，用户看到的是「槽位加起来对不上标题总量」。
    const byName = new Map(golden.map((record) => [record.name, record]));
    for (const [endpoint] of providerSlotsEndpoints) {
      const record = byName.get(`14-usage-without-canonical-provider:${endpoint}`);
      expect(record, `14 号场景的 ${endpoint} 记录必须存在`).toBeTruthy();
      const coverage = record!.provider_usage_coverage as Record<string, number | string>;
      const slotTokens = (record!.provider_slots as Array<{ usage: { total_tokens: number } }>)
        .reduce((sum, row) => sum + row.usage.total_tokens, 0);

      expect(slotTokens, "claude 的用量照常进槽位").toBe(3100);
      // 关键一条：那 800 token 必须被单独点名。断成 0 就是静默消失。
      expect(coverage.unattributed_tokens, "无法归属的用量必须被点名").toBe(800);
      expect(coverage.other_provider_tokens, "这批不是第三方 provider，而是完全无归属").toBe(0);
      expect(coverage.total_tokens, "总量必须含那 800").toBe(3900);
      expect(coverage.status, "有没被展示的量就是 partial").toBe("partial");
      expect(coverage.attributed_tokens, "已归属量只算进了槽位的那部分").toBe(3100);
    }
  });

  it("第三方 provider 的 token 被点名而不是藏起来，聚合 agent 落进 canonical 槽位", () => {
    const byName = new Map(golden.map((record) => [record.name, record]));
    for (const [endpoint] of providerSlotsEndpoints) {
      const thirdParty = byName.get(`13-third-party-provider-without-slot:${endpoint}`)!;
      const coverage = thirdParty.provider_usage_coverage as Record<string, number | string>;
      const slotTokens = (thirdParty.provider_slots as Array<{ usage: { total_tokens: number } }>)
        .reduce((sum, row) => sum + row.usage.total_tokens, 0);
      expect(slotTokens).toBe(3100);
      expect(coverage.other_provider_tokens).toBe(1100);
      expect(coverage.status).toBe("partial");
      expect(coverage.total_tokens).toBe(4200);

      const aggregate = byName.get(`11-aggregate-agent-with-canonical-provider:${endpoint}`)!;
      const claude = (aggregate.provider_slots as Array<{ provider: string; usage: Record<string, unknown> }>)
        .find((row) => row.provider === "claude")!;
      expect(claude.usage.status).toBe("available");
      expect(claude.usage.total_tokens).toBe(3100);
      expect((aggregate.provider_usage_coverage as Record<string, number>).unattributed_tokens).toBe(0);
    }
  });
});

function claudeQuota(record: ProviderSlotsRecord): Record<string, unknown> {
  const slot = (record.provider_slots as Array<{ provider: string; quota: Record<string, unknown> }>)
    .find((row) => row.provider === "claude");
  expect(slot, `${record.name} 必须有 claude 槽位`).toBeTruthy();
  return slot!.quota;
}
