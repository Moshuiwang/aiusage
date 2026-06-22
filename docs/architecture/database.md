# Database Architecture

本文是当前数据库结构的索引，不是迁移设计稿。字段、主键和写入行为以
`src/ai_usage_widget/storage_sqlite.py` 和 `src/ai_usage_widget/models.py`
为唯一权威来源；本文只解释 AI Agent 应该先看哪里、哪些表是现状、哪些只是历史目标。

## 单一权威来源

- Schema owner：`src/ai_usage_widget/storage_sqlite.py` 的 `_ensure_schema()`。
- 数据模型 owner：`src/ai_usage_widget/models.py`。
- 写入入口：`write_sqlite()`、`write_limit_windows()`。
- 读模型 owner：`src/ai_usage_widget/snapshot_builder.py`。

不要从历史设计稿反推字段；新增字段必须先改代码和测试，再更新本文。

## 当前表

| 表 | 当前用途 | 主键 / 去重口径 |
| --- | --- | --- |
| `collection_runs` | 一次采集写入运行记录。 | `id` autoincrement |
| `source_reports` | 每个 source 的采集状态、错误类型和错误摘要。 | `id` autoincrement |
| `usage_daily` | `source_id/date/agent` 级 daily usage baseline。 | `(source_id, date, agent)` |
| `usage_daily_models` | `source_id/date/agent/model_name` 级 daily model breakdown。 | `(source_id, date, agent, model_name)` |
| `usage_hourly` | `source_id/hour/agent` 级 hourly 聚合，主要服务趋势。 | `(source_id, hour, agent)` |
| `usage_blocks` | session/block 时间窗级 usage。 | `(source_id, start_time, end_time, agent)` |
| `source_identities` | source 到 host/machine/os_user/platform 的当前身份映射。 | `source_id` |
| `machines` | 账号归因链路中的机器维度。 | `machine_id` |
| `os_identities` | 机器下 OS 用户维度。 | `(machine_id, os_user)` |
| `ai_accounts` | AI provider 账号维度。 | `(provider, account_id)` |
| `usage_hourly_facts` | 账号级 hourly fact，承载 machine/user/account/provider 归因。 | `fact_id`，另有小时去重唯一索引 |
| `usage_hourly_models` | `usage_hourly_facts` 的 model breakdown。 | `(fact_id, model)` |
| `limit_windows` | 官方或结构化 provider 的额度窗口事实。 | `(source_id, provider, source_type, window)` |

SQLite 写入必须启用 WAL 和 `busy_timeout=5000`，这一点已经在两个写入入口中执行。

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

- daily baseline 是用户可见 token 总量的基础，不得被 limits/provider 失败阻塞。
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

## 历史目标 / 未实现

以下名称曾出现在旧设计文档中，但当前代码没有对应表或没有作为当前 schema 使用：

- `snapshot_builds`
- `source_status_hourly`
- `collector_cursors`
- `client_snapshot_cache`
- `display_preferences`

这些只能作为未来 roadmap 或历史设计参考，不能当作当前可用字段。
