# D1 历史账本一次性补齐交接

## 用户可见结果

本次目标是让 2026-05-18 之后的 today / week / month / all 总量恢复到发布前基线，
并保持机器、系统账号和 AI 账号归属。旧表仍是只读归档，Worker 恢复新读模型后不再读取旧表。

补齐有两类：

- 旧 `usage_hourly` 有真实小时记录：补入带稳定 ID 的小时事实和小时汇总。
- 只有旧 `usage_daily`：补入日级兜底，只影响日/周/月/全部汇总，不制造小时分布。

`usage_hourly_models` 不补。用户仍能看到总量和筛选，但补齐日期的模型明细为空。

## 研发边界

- 项目：`/Users/wangzhipeng/Documents/ai-usage-widget`
- 工具：`src/ai_usage_widget/d1_legacy_backfill.py`
- 目标 D1：`aiusage-prod-db`
- 用户入口：`https://aiusage.chunbai.com`
- 只允许写：
  - `usage_hourly_facts`
  - `usage_hourly_models`（本次实际为 0 行）
  - `usage_hourly_rollups`
  - `usage_daily_rollups`
- 旧 `usage_daily`、`usage_daily_models`、`usage_hourly`、`usage_blocks` 只能 SELECT。
- 不改变密钥、变量、绑定、Worker 名称、域名、登录态、截图或浏览器关闭体验。

## 根因与迁移口径

根因是历史覆盖缺口，不是摘要加法错误：

- 日常 Usage Ledger 增量默认只回看 48 小时。
- PR #49 移除旧表 fallback 后，新 facts/rollups 没有覆盖的旧日期不再进入摘要。
- 发布前 Worker 在某个 `source_id + date + agent` 没有新账本行时会继续使用
  `usage_daily`；有新账本行时则使用新账本，因此不能用“旧总量减新总量后随意累加”的办法补。

可可靠迁移：

- `usage_hourly` 的小时、source、agent、token 分项、总量和成本。
- `usage_daily` 的日期、source、agent、token 分项、总量和成本。
- `source_identities` 的机器与系统账号。
- 现有 `usage_hourly_facts` 中同一 source + agent 的唯一 AI 账号映射。

不能可靠迁移：

- 旧日表没有小时归属，不能生成小时趋势。
- 旧表没有稳定的 AI 账号字段；多个账号或没有映射时必须停止并人工提供去敏映射。
- 旧 `agent=all` 与新表多账号/多 agent 明细重叠时无法同时保住总量和筛选归属，工具直接停止，不自动拆分。
- 日表不能可靠恢复模型明细，不能从 `usage_daily_models` 强行分摊到小时事实。

## 执行前检查

以下命令必须由 Ops 在 `/Users/wangzhipeng/Documents/ops` 中执行。不要输出凭据。

1. 确认 D1 支持 Time Travel，并记录执行前 bookmark：

```bash
npx wrangler d1 info aiusage-prod-db --json
npx wrangler d1 time-travel info aiusage-prod-db --json
```

如果数据库不是 production storage、bookmark 获取失败或账号不明确，立即停止。

2. 导出只读快照并转换为本地 SQLite：

```bash
mkdir -p /tmp/aiusage-d1-backfill
npx wrangler d1 export aiusage-prod-db --remote \
  --output /tmp/aiusage-d1-backfill/before.sql
sqlite3 /tmp/aiusage-d1-backfill/before.sqlite \
  < /tmp/aiusage-d1-backfill/before.sql
```

3. 默认 dry-run（不会写 D1，也不会修改本地快照）：

```bash
cd /Users/wangzhipeng/Documents/ai-usage-widget
PYTHONPATH=src python3 -m ai_usage_widget.d1_legacy_backfill \
  --db /tmp/aiusage-d1-backfill/before.sqlite \
  --start-date 2026-05-18 \
  --end-date 2026-07-01 \
  --as-of-date "$(date +%F)" \
  --batch-size 500 \
  > /tmp/aiusage-d1-backfill/dry-run.json
```

停止条件：

- 状态不是 `ready`。
- `unresolved_identities` 非空。
- 任一日期计划补写量为负或超出旧基线。
- 计划触及四张旧表。
- 预计单批超过 1000 个语句。
- today 或当前 week 在执行前并非已知基线一致。

身份有歧义时，Ops 只能提供审核后的去敏 JSON 映射，不得猜测：

```json
{
  "source-id|agent": {
    "machine_id": "reviewed-machine-id",
    "os_user": "reviewed-os-user",
    "ai_provider": "reviewed-provider",
    "ai_account_id": "reviewed-account-id"
  }
}
```

然后用 `--identity-map /path/to/reviewed-map.json` 重新 dry-run。映射文件不得含 token、密码或原始日志。
映射中的 `machine_id` 和 `ai_provider + ai_account_id` 必须已存在于 D1 身份表；工具不会新造身份。

## 生成与审核 SQL

只有 dry-run 通过后才显式生成写入文件：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.d1_legacy_backfill \
  --db /tmp/aiusage-d1-backfill/before.sqlite \
  --start-date 2026-05-18 \
  --end-date 2026-07-01 \
  --as-of-date "$(date +%F)" \
  --batch-size 500 \
  --emit-write-sql /tmp/aiusage-d1-backfill/sql \
  > /tmp/aiusage-d1-backfill/plan.json
```

审核要点：

- `apply-*.sql` 只能 INSERT/UPSERT 新表。
- 每个文件最多 500 个语句，硬上限 1000。
- provenance 只能是：
  - `historical_ccusage_fallback_v1`
  - `legacy_hourly_archive_backfill_v1`
- `rollback.sql` 只能按本计划生成的精确主键删除本次补写，并再次校验上述 provenance。
- `model_rows` 必须为 0。

先在 before.sqlite 的副本完整演练并再次运行报告；差异不为 0 时停止。

## 生产分批执行

逐个文件执行，每批保留 JSON 结果。不要并行写 D1：

```bash
mkdir -p /tmp/aiusage-d1-backfill/meta
npx wrangler d1 execute aiusage-prod-db --remote \
  --file /tmp/aiusage-d1-backfill/sql/apply-0001.sql \
  --json > /tmp/aiusage-d1-backfill/meta/apply-0001.json
```

每一批都检查返回成功，并记录 `meta.rows_read`、`meta.rows_written`。失败时：

- 不重建计划，不重复导入旧表。
- 先停止，读取当前新表行数和已执行批次。
- 同一批文件可以幂等重跑；确认成功后再继续下一批。
- 不执行 Worker 部署或切换。

预计用量以 `plan.json` 为准：

- `rows_read` 是基于导出快照的预估扫描行数。
- `rows_written` 是逻辑写入数。
- `rows_written_conservative_with_indexes` 是含索引的保守估算。
- 实际值以每批 Wrangler JSON 和 D1 Metrics 为准。

## 执行后只读验收

重新导出为 `after.sql` / `after.sqlite`，对同一范围运行 dry-run 报告：

```bash
npx wrangler d1 export aiusage-prod-db --remote \
  --output /tmp/aiusage-d1-backfill/after.sql
sqlite3 /tmp/aiusage-d1-backfill/after.sqlite \
  < /tmp/aiusage-d1-backfill/after.sql
PYTHONPATH=src python3 -m ai_usage_widget.d1_legacy_backfill \
  --db /tmp/aiusage-d1-backfill/after.sqlite \
  --start-date 2026-05-18 \
  --end-date 2026-07-01 \
  --as-of-date "$(date +%F)" \
  --actual-meta /tmp/aiusage-d1-backfill/meta/apply-*.json \
  > /tmp/aiusage-d1-backfill/after-report.json
```

必须全部满足：

- today / week / month / all `difference_tokens == 0`。
- `daily_differences` 为空。
- 机器、系统账号、AI 账号筛选差异全部为 0。
- 旧表行数与 before 完全相同。
- 新表新增行数与计划一致。
- 模型补写为 0，用户可见影响已接受。
- 实际 rows_read / rows_written 未超出 Ops 预算。

然后才部署包含本 PR 的 Worker，并实际打开 Web、iPhone、Watch、macOS 菜单栏入口，
验证 today/week/month/all、机器和账号筛选。任何一个入口不一致都停止恢复。

## 回退

优先使用定向回退，不影响补齐之后的其他正常上报：

```bash
npx wrangler d1 execute aiusage-prod-db --remote \
  --file /tmp/aiusage-d1-backfill/sql/rollback.sql \
  --json
```

执行后重新导出并确认只有本计划列出的精确行键被移除，四张旧表仍在且未变化。

只有定向回退失败且确认需要覆盖整库时，才由 Ops 使用执行前记录的 Time Travel bookmark。
Time Travel 会原地覆盖数据库并取消在途查询，属于高风险兜底，必须单独获得用户确认：

```bash
npx wrangler d1 time-travel restore aiusage-prod-db \
  --bookmark "<EXECUTION_PRE_BOOKMARK>"
```

## 最终停止条件

- 任何身份映射不唯一。
- 新旧逐日总量不能解释。
- 写入文件出现旧表 DML。
- 单批失败后当前状态无法确认。
- Time Travel bookmark 不可用。
- 任一用户入口或筛选与基线不一致。
- 需要扩大到 2026-05-02 至 2026-05-17。
