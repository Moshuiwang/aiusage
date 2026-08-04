# Database Architecture

本文是当前数据库结构的索引，不是迁移设计稿。字段、主键和写入行为以
`cloudflare/migrations/`（D1 schema）与 `cloudflare/native-worker/src/write-model.ts`
（写入口径）为事实来源；本文只解释 AI Agent 应该先看哪里、
哪些表是现状、哪些只是历史目标。Python 本地存储层已随 #74 删除。

## 当前生产数据库

当前生产 canonical store 是 Cloudflare D1。D1 是 Cloudflare 托管的
SQLite-compatible serverless SQL 数据库，不是 PostgreSQL。AI Usage 的
Web、iPhone、Watch 和 macOS 菜单栏都通过 Cloudflare Worker API 读取派生摘要，
不直接读取数据库。

本地 SQLite 仍保留为 legacy/local compatibility、测试适配层和 D1 schema
迁移参考。它不是当前生产用户体验的唯一事实源，也不应该再被描述成服务端唯一数据库。

## Schema 权威来源

- schema owner：`cloudflare/migrations/`（0001 是累计快照；守卫是
  `tests/test_d1_schema_migration.py` 的显式列布局快照——#74 起不再镜像 Python 存储层）。
- 采集端 payload owner：`src/ai_usage_widget/pusher.py`（`models.py` 只保留命令执行结果）。
- 写入入口：Cloudflare Worker `/ingest`、`/ingest-limits`（`write-model.ts`）。
- 读模型 owner：`cloudflare/native-worker/src/read-model.ts` / `mobile-summary.ts`。
- 采集端唯一本地库：`collector_store.py` 的 outbox（缓冲，不是档案）。

不要从历史设计稿反推字段；新增字段必须先改代码和测试，再更新本文。

## 当前表

| 表 | 当前用途 | 主键 / 去重口径 |
| --- | --- | --- |
| `collection_runs` | 一次采集写入运行记录。 | `id` autoincrement |
| `source_reports` | 每个 source 的采集状态、错误类型和错误摘要。 | `id` autoincrement |
| `usage_daily` | 旧 daily 数据只读归档；Worker 不再常规读取或兼容写入。 | `(source_id, date, agent)` |
| `usage_daily_models` | 旧 daily model 数据只读归档；Worker 不再常规读取或兼容写入。 | `(source_id, date, agent, model_name)` |
| `usage_hourly` | 旧 hourly 数据只读归档；Worker 不再常规读取或兼容写入。 | `(source_id, hour, agent)` |
| `usage_blocks` | 旧 session/block 数据只读归档；Worker 不再常规读取或兼容写入。 | `(source_id, start_time, end_time, agent)` |
| `source_identities` | source 到 host/machine/os_user/platform 的当前身份映射。 | `source_id` |
| `machines` | 账号归因链路中的机器维度。 | `machine_id` |
| `os_identities` | 机器下 OS 用户维度。 | `(machine_id, os_user)` |
| `ai_accounts` | AI provider 账号维度。 | `(provider, account_id)` |
| `usage_hourly_facts` | 账号级 hourly fact，承载 machine/user/account/provider 归因。 | `fact_id`，另有小时去重唯一索引 |
| `usage_hourly_models` | `usage_hourly_facts` 的 model breakdown。 | `(fact_id, model)` |
| `usage_hourly_rollups` | today 与小时趋势的权威汇总读模型。 | 账号归因维度 + `window_start` |
| `usage_daily_rollups` | week/month/all 的权威日汇总读模型。 | 账号归因维度 + `window_start` |
| `limit_windows` | 官方或结构化 provider 的额度窗口事实。 | `(source_id, provider, source_type, window)` |

SQLite 写入必须启用 WAL 和 `busy_timeout=5000`，这一点已经在两个写入入口中执行。

生产 D1 中最影响用户体验的是 `usage_hourly_facts`：本机每次上报的是最近窗口内
有用量的小时桶，不是每个 session 的完整原始明细。服务端按同一来源、agent、
账号归因、时间窗口和 provenance 做 upsert；同一个小时桶重复上报时更新为最新事实，
不会累加成重复用量。

截至 2026-06-28 的一次生产核查，D1 数据库约 4.0 MB，属于很小的个人数据规模。
`usage_hourly_facts` 当时为 524 行，`source_reports` 和 `collection_runs`
约 8.6k 行。长期增长主要来自采集运行记录和 source report；如果未来体量明显增长，
应优先对运行日志类表做保留周期或归档策略，而不是削弱用户可见的用量账本。

## 当前核心字段

`usage_daily` / `usage_hourly` / `usage_blocks` 共享 usage token 字段：

- `source_id`
- 日期或窗口字段：`date` / `hour` / `start_time` + `end_time`
- `agent`
- `input_tokens`
- `output_tokens`
- `cache_creation_tokens`
- `cache_read_tokens`
- `total_tokens`
- `total_cost`
- `metadata_json`
- `raw_json`
- `first_seen_at`
- `last_seen_at`

`usage_hourly_facts` 是当前账号级归因事实表，关键字段为：

- identity：`fact_id`、`source_id`、`machine_id`、`os_user`
- account：`ai_provider`、`ai_account_id`
- window：`window_start`、`window_end`、`timezone`
- usage：`input_tokens`、`output_tokens`、`cache_creation_tokens`、`cache_read_tokens`、`reasoning_output_tokens`、`total_tokens`
- confidence：`attribution_confidence`、`provenance`
- evidence：`account_evidence_json`、`metadata_json`

`limit_windows` 当前只保存结构化窗口事实，不保存 token、cookie、完整 API 响应或原始日志：

- `source_id`
- `provider`
- `window`
- `used_percent`
- `remaining_percent`
- `reset_at`
- `window_duration_minutes`
- `source_type`
- `confidence`
- `status`
- `observed_at`
- `first_seen_at`
- `last_seen_at`

## 约束与边界

- 用户可见 token 总量只使用 `usage_hourly_facts`、`usage_hourly_models`、`usage_hourly_rollups`、`usage_daily_rollups`，不得被 limits/provider 失败阻塞。
- Usage Ledger 明细上报不得被 `ccusage daily` 缺失阻塞；旧 usage 表只保留为只读归档，不参与摘要或历史兜底。
- 生产发布前必须核验新 facts/rollups 对 today/week/month/all 历史范围的覆盖完整性；覆盖不足时停止发布，不得重新启用旧表 fallback。
- 官方额度只有 `official == true`、`confidence == "observed"`、`status == "ok"` 才能作为强结论展示。
- `.claude`、`.codex` 原始日志目录、token、cookie、完整 provider response 不进入 SQLite。
- 任何改表都必须单独任务包，先写迁移方案和测试；本轮不做 SQLite 迁移。

## Apple Watch companion

本轮 Apple Watch 刷新不新增数据库表，也不修改现有 schema。

原因：

- Watch 只展示 `/api/mobile/summary?period=today` 已经具备的 usage、trend、limits 和 source health。
- iPhone 后台刷新只是多一个移动端读取路径，不产生新的服务端事实。
- Watch App Group cache 是设备本地展示缓存，不是服务端数据库状态。
- 表盘的安装状态、组件选择和 timeline 状态由 watchOS 管理，不写入 SQLite。

如果未来要做用户可配置表盘偏好、设备列表、独立 watchOS token 或推送刷新，再单独开数据库迁移任务包；不能把这些作为本轮后台刷新实现的隐性前置条件。

## Data freshness / accuracy design

数据及时性、缓存落盘、D1/source parity 和 `limit_windows` 有效窗口选择的方案见
[`data-freshness-accuracy-database.md`](data-freshness-accuracy-database.md)。
该文档是后续实现规划，不改变本文列出的当前 schema 真相源。

## 历史目标 / 未实现

以下名称曾出现在旧设计文档中，但当前代码没有对应表或没有作为当前 schema 使用：

- `snapshot_builds`
- `source_status_hourly`
- `collector_cursors`
- `client_snapshot_cache`
- `display_preferences`

这些只能作为未来 roadmap 或历史设计参考，不能当作当前可用字段。
