/**
 * #183-b：每日 cron（`runQuotaCalibration`）D1 rows_read 上界估算。
 *
 * D1 免费计划预算是 500 万行/天（`.claude/rules/cloudflare.md`）。这个 cron 每天对
 * claude/codex/antigravity 三个 provider 各跑一次 `fetchLimitObservations` +
 * `fetchHourlyFamilyFacts`，SQL 侧 WHERE 过滤 + GROUP BY 聚合，但 D1 按扫描的基表行数计费
 * （`rows_read`），不是按返回的聚合行数——所以估算要用**基表行数**，不是聚合后的行数。
 *
 * 基表行数来自 2026-09-27 对生产 D1 的一次性只读导出（同一份数据是
 * `test/calibration_fixture.json` 的来源，见该文件与 `scripts/export_calibration_fixture.py`
 * 头注释）：账户从 2026-09-17 起步，导出时点覆盖约 10 天历史：
 * - `limit_window_history`（三个 provider 合计，`window='week'`）：3012 行
 * - `usage_hourly_facts`（三个 provider 合计）：493 行
 * - `usage_hourly_models`（三个 provider 合计）：602 行
 *
 * 这不是本次改动新生成的数字——是这次 #183 系列改动开始前就做过的一次性导出，本机没有
 * 权限重新对生产 D1 跑统计查询（见收口报告「意外事实」），所以这里只能按已知抽样线性
 * 外推到 28 天窗口（×2.8），代表「账户长到设计要求的 28 天训练窗口后，稳态每天大约要
 * 扫多少基表行」，不是精确值。
 */
import { describe, expect, it } from "vitest";

/** 2026-09-27 只读导出的基表行数（三个 provider 合计，约 10 天历史）。见文件头注释来源。 */
const SAMPLED_LIMIT_WINDOW_HISTORY_ROWS = 3012;
const SAMPLED_USAGE_HOURLY_FACTS_ROWS = 493;
const SAMPLED_USAGE_HOURLY_MODELS_ROWS = 602;
const SAMPLED_WINDOW_DAYS = 10;

const CALIBRATION_WINDOW_DAYS = 28;
const SCALE_FACTOR = CALIBRATION_WINDOW_DAYS / SAMPLED_WINDOW_DAYS;

/** D1 免费计划每日读预算，来自 .claude/rules/cloudflare.md。 */
const D1_FREE_DAILY_ROWS_READ_BUDGET = 5_000_000;

describe("quota calibration cron：D1 rows_read 上界估算（外推，非精确值）", () => {
  it("三个 provider 合计每天一次的 rows_read 上界远低于 D1 免费计划预算", () => {
    // usage_hourly_models 是 JOIN usage_hourly_facts 的驱动表，一次 JOIN 最多扫
    // (models 行数 + facts 行数)——D1 按基表行数计费，JOIN 本身不会让扫描行数翻倍
    // （对每条 model 行找它对应的 fact 行是索引查找，不是笛卡尔积）。
    const perProviderCronRowsReadUpperBound =
      SAMPLED_LIMIT_WINDOW_HISTORY_ROWS * SCALE_FACTOR
      + SAMPLED_USAGE_HOURLY_FACTS_ROWS * SCALE_FACTOR
      + SAMPLED_USAGE_HOURLY_MODELS_ROWS * SCALE_FACTOR;

    // cron 对三个 provider 各查一次，WHERE provider = ? 用得上 #183-b 新增的
    // idx_limit_window_history_provider 索引（领头列是 provider），理论上不需要
    // 三次都扫全表——但没有索引统计信息时按「保守估计＝三次独立全量扫描」估算上界。
    const dailyRowsReadUpperBound = perProviderCronRowsReadUpperBound * 3;

    // eslint-disable-next-line no-console
    console.log(
      `[rows_read 估算] 单 provider 上界≈${perProviderCronRowsReadUpperBound.toFixed(0)} 行，`
      + `三 provider 合计上界≈${dailyRowsReadUpperBound.toFixed(0)} 行/天，`
      + `占 D1 免费日预算 ${((dailyRowsReadUpperBound / D1_FREE_DAILY_ROWS_READ_BUDGET) * 100).toFixed(4)}%`,
    );

    expect(dailyRowsReadUpperBound).toBeLessThan(50_000);
    expect(dailyRowsReadUpperBound / D1_FREE_DAILY_ROWS_READ_BUDGET).toBeLessThan(0.01); // <1% 预算
  });

  it("account_observations 冲突检查（COUNT DISTINCT）与写回 quota_calibration 的行数都是常数级，不随窗口天数增长", () => {
    // account_observations 每个 provider 最多几个指纹（正常情况 1 个，冲突也就是几个）；
    // quota_calibration 每个 provider 覆盖写的行数 = 已知族数（Claude 4 / Codex 3 / Antigravity 3），
    // 三个 provider 合计写入 ≤十几行/天——跟设计文档 §3「quota_calibration ~十几行/天」一致。
    const knownFamilyCounts = { claude: 4, codex: 3, antigravity: 3 };
    const dailyWriteRowsUpperBound = Object.values(knownFamilyCounts).reduce((s, n) => s + n, 0);
    expect(dailyWriteRowsUpperBound).toBeLessThanOrEqual(15);
  });
});
