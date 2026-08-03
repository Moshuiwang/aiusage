// #74 块 8：`verify-cloud` fixture 的 owner 绑定守卫（接替
// tests/test_cli_verify_cloud.py::TestVerifyCloudFixturesStayBoundToReadModel 的 3 条耦合用例）。
//
// fixture 不是手写的想象：mobile DTO 与版本健康块都必须由真正的 owner 现算出来对齐。
// #74 删除 Python 读模型后，owner 是本目录旁边的 `mobile-summary.ts` 与 `version-contract.ts`；
// 读模型改了形状而 fixture 没跟上，这里会红——否则 `verify-cloud` 会一直核对一份过时的幻想。
//
// fixture 目录仍在 `tests/fixtures/verify_cloud/`（消费方 `verify_cloud.py` 留 Python），
// 所以 `scripts/verify.sh` 的 Worker 触发判据必须包含该前缀（回归用例在 test_verify_scope.py）。
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { buildMobileSummary } from "../src/mobile-summary";
import { buildVersionHealth } from "../src/version-contract";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const fixturesRoot = path.join(repoRoot, "tests/fixtures/verify_cloud");

const SCENARIOS = ["healthy", "degraded", "parity_mismatch"] as const;
// parity_mismatch 的 mobile fixture 是「故意与 owner 不一致」的负面样本，单独断言。
const OWNER_ALIGNED_SCENARIOS = ["healthy", "degraded"] as const;

type AnyRecord = Record<string, unknown>;

function loadFixture(scenario: string, name: string): AnyRecord {
  const raw = readFileSync(path.join(fixturesRoot, scenario, name), "utf-8");
  return JSON.parse(raw) as AnyRecord;
}

// 经由 JSON 往返归一化（丢 undefined、-0 之类 JSON 表达不了的东西），
// 让比较发生在「两份 JSON 文档」之间，而不是 JS 运行时对象之间。
function asJson(value: unknown): unknown {
  return JSON.parse(JSON.stringify(value));
}

describe("verify-cloud fixtures stay bound to the Worker owners", () => {
  it("healthy 与 degraded 的 mobile fixture 必须逐字段等于 buildMobileSummary(summary)", () => {
    let checked = 0;
    for (const scenario of OWNER_ALIGNED_SCENARIOS) {
      const summary = loadFixture(scenario, "summary.json");
      const built = asJson(buildMobileSummary(summary)) as AnyRecord;
      // 结构下限：owner 真的产出了完整 DTO，而不是空对象对空对象的假绿。
      for (const key of ["period", "trend", "provider_slots", "sources", "limits"]) {
        expect(built, `${scenario}: buildMobileSummary 输出必须带 ${key}`).toHaveProperty(key);
      }
      expect(built, `${scenario}: mobile fixture 已偏离 owner 输出`).toEqual(
        loadFixture(scenario, "mobile_summary.json"),
      );
      checked += 1;
    }
    // 字面量而不是 OWNER_ALIGNED_SCENARIOS.length：清单被清空时 0===0 不许照样绿。
    expect(checked, "必须核完两个 owner 对齐场景").toBe(2);
  });

  it("parity_mismatch 的 mobile fixture 必须真的与 owner 输出不一致", () => {
    // 负面 fixture 的有效性守卫：如果它悄悄变「正确」了，verify-cloud 的
    // parity 失败路径就再也测不到失败。
    const summary = loadFixture("parity_mismatch", "summary.json");
    expect(asJson(buildMobileSummary(summary))).not.toEqual(
      loadFixture("parity_mismatch", "mobile_summary.json"),
    );
  });

  it("三个场景的版本块必须等于 buildVersionHealth(source_status)", () => {
    let checked = 0;
    for (const scenario of SCENARIOS) {
      const summary = loadFixture(scenario, "summary.json");
      const sourceStatus = summary.source_status as AnyRecord[];
      expect(Array.isArray(sourceStatus), `${scenario}: summary 必须带 source_status`).toBe(true);
      expect(sourceStatus.length, `${scenario}: source_status 不能为空`).toBeGreaterThan(0);
      const expected = asJson(buildVersionHealth(sourceStatus));
      expect(summary.version_health, `${scenario}: summary.version_health 偏离 owner`).toEqual(expected);
      expect(
        loadFixture(scenario, "health.json").versions,
        `${scenario}: health.versions 偏离 owner`,
      ).toEqual(expected);
      checked += 1;
    }
    expect(checked, "必须核完全部三个场景").toBe(3);
  });
});
