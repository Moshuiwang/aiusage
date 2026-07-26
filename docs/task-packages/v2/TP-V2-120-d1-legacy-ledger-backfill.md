# TP-V2-120 D1 Legacy Ledger Backfill

Version: V2
ID: TP-V2-120
Status: done
Type: implementation
Depends on: TP-V2-103, TP-V2-119
Parallel with: none

## Goal

提供一次性、可审计、可恢复的 D1 历史补齐工具，让 2026-05-18 之后的新账本摘要与发布前基线一致，不重新启用旧表读取。

## Context

PR #49 将用户摘要完全切到 `usage_hourly_facts`、`usage_hourly_models`、
`usage_hourly_rollups`、`usage_daily_rollups`。生产预发核查发现新表的历史覆盖不足。
日常增量采集默认只回看 48 小时，因此它不能自动补齐全部旧日级历史。

业务口径：

- 旧 `usage_hourly` 有真实小时归属时才允许补小时事实。
- 只有旧 `usage_daily` 时，只补日级兜底，不能把日总量伪装成某个小时。
- 旧表没有 AI 账号字段；只接受现有事实中的唯一映射或 Ops 明确审核的映射。
- `usage_hourly_models` 可以为空，用户会看不到补齐日期的模型拆分。

## Scope

- 新增默认 dry-run 的本地 D1 export 分析工具。
- 限定 `2026-05-18` 之后的显式日期范围。
- 每批最多 1000 个 SQL 语句，生成幂等批次和定向 rollback。
- 只写四张新账本表；旧表只 SELECT。
- 补齐前后报告覆盖周期、逐日、机器、系统账号、AI 账号、表行数和 D1 用量估算。
- Worker 对已审核的日/小时兜底采用稳定优先级，避免以后出现双算。

## Out of Scope

- 不访问生产 Cloudflare、Ops 凭据或原始 Claude/Codex 日志。
- 不部署、不合并、不执行生产 D1 写入。
- 不补 2026-05-02 至 2026-05-17。
- 不从旧日汇总制造模型或小时明细。

## Red Test

- 缺少实现时导入失败。
- 重复执行不新增写入。
- 第一批成功、后续中断后可从任意批次恢复。
- 旧表快照前后完全一致。
- 机器、系统账号、AI 账号映射一致。
- 日级兜底存在时，后续详细事实不能改变已审核历史总量。
- 模型明细保持为空。

## Implementation

1. 从 Ops 导出的只读 D1 SQL 构造本地 SQLite 快照。
2. 识别发布前读模型真正依赖、但新 rollup 完全缺失的日期键。
3. 从 `source_identities`、`machines` 和现有事实中取得唯一身份映射；歧义时停止。
4. 对权威旧小时行生成稳定 ID 的小时 fact/rollup；对仅日级记录生成带专用 provenance 的 daily rollup。
5. 生成可重复执行的 SQL 小批次和只删除本计划精确主键的 rollback。
6. Worker 在同一日期/小时键中优先使用已审核兜底，防止后续明细与兜底叠加。

## Acceptance Criteria

- dry-run 不修改输入快照。
- 生产 SQL 只能由显式 `--emit-write-sql` 生成。
- 所有批次幂等，任一批次可安全重跑。
- 旧表不出现 INSERT / UPDATE / DELETE。
- 身份不唯一时不生成任何写入 SQL。
- 补齐后 today/week/month/all、逐日和筛选差异为 0 才允许恢复新 Worker。
- 模型为空的影响在报告和 Ops 交接中明确。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_d1_legacy_backfill -v
npx vitest run --config cloudflare/native-worker/vitest.config.ts
npx tsc --noEmit -p cloudflare/native-worker/tsconfig.json
```

## Handoff

- Ops 只在 `/Users/wangzhipeng/Documents/ops` 中执行生产命令。
- 运行顺序和停止条件见 `cloudflare/D1_LEGACY_BACKFILL_HANDOFF.md`。
- 生产实际读写量以 Wrangler JSON 的 `meta.rows_read` / `meta.rows_written` 为准。
