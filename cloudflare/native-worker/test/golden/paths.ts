/**
 * #74 P1：golden 生成与校验共用的路径与固定常量。
 *
 * 这些值以前分散在 Python 侧（`tests/test_value_golden_freshness.py`、
 * `tests/test_provider_slots_parity.py`、`tests/test_api_contract.py`）与 TS 测试文件里，
 * 各自抄了一份。抄多份的后果是「生成」与「校验」会各自漂移，最后产出一对自洽的错误，
 * 所以这里是唯一一份。
 */

import path from "node:path";
import { fileURLToPath } from "node:url";

export const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../..");

/** Worker 入口：所有 golden 都由它实际响应产出，不从读模型函数直接取值。 */
export const workerEntryPath = path.join(repoRoot, "cloudflare/native-worker/src/index.ts");
export const schemaPath = path.join(repoRoot, "cloudflare/migrations/0001_initial_schema.sql");
export const seedSqlPath = path.join(repoRoot, "cloudflare/native-worker/test/seed.sql");
export const providerSlotsScenarioDir = path.join(repoRoot, "cloudflare/native-worker/test/provider_slots");

export const valueGoldenPath = path.join(repoRoot, "cloudflare/native-worker/test/value_golden.json");
export const providerSlotsGoldenPath = path.join(repoRoot, "cloudflare/native-worker/test/provider_slots_golden.json");
export const apiContractGoldenPath = path.join(repoRoot, "tests/fixtures/contract/api_contract_golden.json");
export const macosOwnerFixturePath = path.join(
  repoRoot,
  "clients/macos/Tests/AIUsageMenuBarCoreTests/Fixtures/provider-slots-owner-fixture.json",
);

export const token = "contract-test-token";
export const timezone = "Asia/Shanghai";

/** 固定时刻：读模型的一切「相对现在」判定都参照它，否则 golden 每天都会变。 */
export const fixedNow = "2026-06-03T12:00:00+08:00";

/**
 * 合同场景里那台「超过 120 分钟没上报」的设备的采集时刻。
 *
 * 必须相对本场景用到的两个参照时刻都超过阈值：`/api/health` 参照 `AIUSAGE_NOW`
 * （12:00，差 240 分钟），`/ingest-limits` 的 payload `observed_at` 是 11:00（差 180 分钟）。
 * 全新鲜的 fixture 下「折算」与「不折算」产出完全相同的 counts，这条口径会静音。
 */
export const staleCollectedAt = "2026-06-03T08:00:00+08:00";
