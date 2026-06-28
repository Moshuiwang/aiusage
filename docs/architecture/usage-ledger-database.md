# Usage Ledger Database Design

Date: 2026-06-28
Status: draft for implementation planning
Related PRD: [`../product/usage-ledger-prd.md`](../product/usage-ledger-prd.md)
Related architecture: [`usage-ledger-architecture.md`](usage-ledger-architecture.md)

## 目标

新增一个事件级 usage ledger，使历史用量不再被本地当前快照覆盖。

本设计是后续 schema 规划，不代表当前数据库已经存在这些表。当前真实 schema 仍以 [`database.md`](database.md) 和代码为准。

## 设计原则

- 事件明细只保存 token usage 和脱敏归因，不保存原始日志内容。
- Codex 事件必须能跨 active / archived 去重。
- Claude 事件必须能跨重复 assistant log 去重。
- 日常增量上报只能追加事件，不重算历史总量。
- 历史修正必须有审计记录。
- SQLite 和 Cloudflare D1 都应能承载同一逻辑；避免依赖 SQLite-only 特性。

## 新增表概览

| 表 | 用途 |
| --- | --- |
| `usage_ledger_events` | 事件级不可变 usage fact。 |
| `usage_ledger_daily_fallbacks` | 没有明细时的日级兜底估算。 |
| `usage_ledger_cutover_totals` | 上线切换日前今日总量，避免切换日双计。 |
| `usage_ledger_hours` | 小时 rollup、冻结状态和可信状态。 |
| `usage_ledger_dates` | 日期可信状态，用于 doctor 和汇总筛选。 |
| `usage_ledger_import_runs` | `full_rescan` / `incremental_report` 批次记录。 |
| `usage_ledger_revisions` | 修正、确认、忽略的审计记录。 |

## `usage_ledger_events`

事件级主事实表。

```sql
CREATE TABLE usage_ledger_events (
  event_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  agent TEXT NOT NULL,
  source_id TEXT NOT NULL,
  machine_id TEXT,
  os_user TEXT,
  ai_account_provider TEXT,
  ai_account_id TEXT,
  account_attribution_status TEXT NOT NULL,
  entry_at TEXT NOT NULL,
  hour_start TEXT NOT NULL,
  date TEXT NOT NULL,
  timezone TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  model TEXT,
  source_event_key TEXT NOT NULL,
  source_session_id TEXT,
  source_request_id TEXT,
  source_message_id TEXT,
  collection_mode TEXT NOT NULL,
  import_run_id TEXT NOT NULL,
  provenance TEXT NOT NULL,
  metadata_json TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
```

### 字段说明

| 字段 | 说明 |
| --- | --- |
| `event_id` | 服务端去重主键，必须稳定。 |
| `provider` | 日志和计费来源，例如 `codex` / `claude`。 |
| `agent` | 兼容现有 summary 的展示聚合维度。当前通常等于 provider，但保留用于未来同一 provider 下不同 agent/client 的归类。 |
| `entry_at` | 按记录时间入账的时间。Codex 为 `token_count.timestamp`，Claude 为 assistant `timestamp`。 |
| `hour_start` | 产品时区下的小时桶起点。 |
| `date` | 产品时区下的日期。 |
| `ai_account_provider` | 账号所属供应商，例如 `openai` / `anthropic`；无法确认时为空。 |
| `account_attribution_status` | `confirmed` / `unconfirmed_local_source` / `unknown`；`unknown` 只用于 legacy 或缺来源配置，doctor 按未确认账号处理。 |
| `source_event_key` | 本地 parser 生成的稳定去重身份，不含 usage 数值和原始路径；与 `event_id` 必须 1:1。 |
| `collection_mode` | `full_rescan` / `incremental_report`。 |
| `provenance` | `codex_token_count` / `claude_assistant_usage`。 |

### 去重规则

Codex `event_id` 建议组成：

```text
sha256(
  "codex" +
  source_id +
  session_id +
  token_count.timestamp +
  token_count_ordinal_within_session
)
```

要求：

- 不包含原始文件路径。
- 同一事件从 active 移到 archived 后仍能得到同一 ID。
- 归档后重复扫描不能让日总增加。
- `token_count_ordinal_within_session` 必须是 session 内 `token_count` 事件的确定性序号，不得使用受文件路径、归档目录或 glob 顺序影响的行号。
- 如果同一 session 同一 timestamp 有多条 `token_count`，ordinal 用 session 内 token_count 顺序消歧；必要时可在 `metadata_json` 保存安全 usage fingerprint 供 doctor 对账，但 fingerprint 不应成为归档位置相关的 ID。

Claude `event_id` 建议组成：

```text
sha256(
  "claude" +
  source_id +
  message.id +
  requestId fallback ""
)
```

要求：

- 同一 `message.id + requestId` 的重复记录只入账一次。
- 非 0 usage 不同的重复记录先按 PRD 规则选最终有效 usage，再更新同一个事件。
- usage 数字不能参与 `event_id`，否则后续 rescan 选到更大 usage 时会生成新事件并双计。
- 同一事件 usage 被更新时，必须写 `usage_ledger_revisions`，rollup 只能反映更新后的最终 usage。
- 未稳定验证前，对应日期保持 `pending`。

`source_event_key` 是去重权威身份，`event_id` 是它的 hash 化主键：

- Codex `source_event_key`: `codex|source_id|session_id|token_count.timestamp|token_count_ordinal_within_session`
- Claude `source_event_key`: `claude|source_id|message.id|requestId_or_empty`
- 服务端写入时优先按 `source_event_key` 判断同一事件；如果 `event_id` 因 parser 版本变化而不同，但 `source_event_key` 命中，必须视为同一事件并更新原事件。
- `event_id` 与 `source_event_key` 不一致的情况必须写 revision 或 import warning，不能直接插入第二条。

## `usage_ledger_daily_fallbacks`

当某段历史没有事件明细，只能使用 `ccusage` 日级兜底时保存。

```sql
CREATE TABLE usage_ledger_daily_fallbacks (
  fallback_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  agent TEXT NOT NULL,
  source_id TEXT NOT NULL,
  date TEXT NOT NULL,
  timezone TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  source_type TEXT NOT NULL,
  confidence TEXT NOT NULL,
  import_run_id TEXT NOT NULL,
  metadata_json TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
```

规则：

- `source_type` 可为 `historical_ccusage_fallback`。
- 只参与日、近 7 天、近 30 天、全部汇总。
- 不生成小时分布。
- doctor 必须标记“包含估算数据”。
- 同一个 `(date, provider, source_id, agent)` 上，事件明细和日级兜底必须互斥参与汇总：有事件明细时忽略兜底，没有事件明细时才使用兜底。

## `usage_ledger_cutover_totals`

保存上线切换日前的今日总量，用于切换日总量拼接。

```sql
CREATE TABLE usage_ledger_cutover_totals (
  date TEXT NOT NULL,
  provider TEXT NOT NULL,
  agent TEXT NOT NULL,
  source_id TEXT NOT NULL,
  timezone TEXT NOT NULL,
  cutover_at TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  source_type TEXT NOT NULL,
  status TEXT NOT NULL,
  import_run_id TEXT NOT NULL,
  metadata_json TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY (date, provider, agent, source_id)
);
```

规则：

- 只用于切换日。
- `status` 允许 `active`、`superseded`、`ignored`。
- 覆盖区间必须是 `< cutover_at`。
- 切换后 ledger 事件覆盖区间必须是 `>= cutover_at`。
- 不生成切换前小时分布。
- 与 `usage_ledger_events` 聚合时按半开区间合并，不能重叠。
- 如果后续 `full_rescan` 为同一切换日的 `< cutover_at` 区间生成了明细事件，`cutover_pre_total` 必须标记为 `superseded` 并退出汇总，且写 `usage_ledger_revisions`。不能同时把切换前 total 和切换前明细事件相加。

## `usage_ledger_hours`

小时 rollup 表，用于 summary 和冻结。

```sql
CREATE TABLE usage_ledger_hours (
  provider TEXT NOT NULL,
  agent TEXT NOT NULL,
  source_id TEXT NOT NULL,
  hour_start TEXT NOT NULL,
  hour_end TEXT NOT NULL,
  timezone TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  event_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  frozen_at TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY (provider, agent, source_id, hour_start)
);
```

允许状态：

| 状态 | 含义 |
| --- | --- |
| `open` | 当前小时或尚未冻结。 |
| `frozen` | 普通增量不再修改。 |
| `repair_pending` | 发现晚到或差异。 |
| `repaired` | 已修正。 |
| `ignored` | 差异已忽略。 |

写入规则：

- `incremental_report` 可以修改 `open` 小时。
- `incremental_report` 不能修改 `frozen` 小时。
- `full_rescan` / `repair` 可以产生修正，但必须写 `usage_ledger_revisions`。
- 小时进入 `repair_pending`、`repaired` 或 `ignored` 时，所属 `usage_ledger_dates` 必须同步标记 `includes_pending=1` 或状态降级为 `pending`。
- rollup 更新不能简单按 payload token 做 `+=`。服务端必须先插入 / 更新事件，再基于受影响小时从 `usage_ledger_events` 重算小时 totals，确保重复上报不会增加 rollup。D1 实现应把事件写入、受影响小时重算、日期状态更新放入同一批事务或等价的幂等批处理。

## `usage_ledger_dates`

日期可信状态表。

```sql
CREATE TABLE usage_ledger_dates (
  date TEXT NOT NULL,
  timezone TEXT NOT NULL,
  provider TEXT NOT NULL,
  agent TEXT NOT NULL,
  source_id TEXT NOT NULL,
  status TEXT NOT NULL,
  status_reason TEXT,
  includes_fallback INTEGER NOT NULL DEFAULT 0,
  includes_pending INTEGER NOT NULL DEFAULT 0,
  cutover_at TEXT,
  confirmed_at TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY (date, provider, agent, source_id)
);
```

允许状态：

| 状态 | 含义 |
| --- | --- |
| `confirmed` | 可进入默认确定汇总。 |
| `pending` | 需要 doctor / AI agent 确认。 |
| `fallback_estimated` | 只有日级兜底。 |

汇总规则：

- 今天是 live 日期，始终纳入当前汇总，并由 doctor 标记为 live / open。
- 今天之前，近 7 天、近 30 天、全部默认只使用 `confirmed`。
- 日期有效状态按参与来源里的最差状态计算；任一来源为 `pending` 或 `fallback_estimated`，覆盖该日期的汇总必须输出 contains pending / estimated。
- 日期状态粒度与事件、小时、兜底、切换日前总量一致，均包含 `agent`。如果未来要跨 agent 合并，必须在 summary 层显式取最差状态，不能让一个 agent 的 pending 静默覆盖另一个 agent。
- 切换日通过 `cutover_at` 说明今日总数和小时图口径差异。
- 服务端必须使用单一产品时区。payload timezone 与产品时区不一致时拒收或进入错误状态，不能把不同时区混入同一日期。

## `usage_ledger_import_runs`

记录每次采集或回填。

```sql
CREATE TABLE usage_ledger_import_runs (
  import_run_id TEXT PRIMARY KEY,
  collection_mode TEXT NOT NULL,
  source_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  timezone TEXT NOT NULL,
  scan_start_at TEXT,
  scan_end_at TEXT,
  scan_strategy TEXT,
  status TEXT NOT NULL,
  events_seen INTEGER NOT NULL DEFAULT 0,
  events_inserted INTEGER NOT NULL DEFAULT 0,
  events_duplicate INTEGER NOT NULL DEFAULT 0,
  fallback_days_seen INTEGER NOT NULL DEFAULT 0,
  safe_error TEXT,
  metadata_json TEXT
);
```

用途：

- 区分日常增量和总量重算。
- doctor 判断最近上报时间和上报健康。
- review 检查是否误把 `full_rescan` 配成定时任务。
- `scan_strategy` 记录 `changed_files_plus_time_window`、`full_history` 等策略，便于判断是否可能漏掉晚到事件。

## `usage_ledger_revisions`

修正、确认和忽略的审计表。

```sql
CREATE TABLE usage_ledger_revisions (
  revision_id TEXT PRIMARY KEY,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_key TEXT NOT NULL,
  previous_status TEXT,
  new_status TEXT,
  reason TEXT,
  actor TEXT NOT NULL,
  import_run_id TEXT,
  created_at TEXT NOT NULL,
  metadata_json TEXT
);
```

允许动作：

- `confirm`
- `repair`
- `ignore`
- `mark_pending`
- `freeze_hour`
- `unfreeze_for_repair`

`target_type` 允许值：

- `event`
- `hour`
- `date`
- `cutover_total`
- `fallback`

`target_key` 格式：

- event：`event_id`
- hour：`provider|agent|source_id|hour_start`
- date：`date|provider|agent|source_id`
- cutover_total：`date|provider|agent|source_id`
- fallback：`fallback_id`

actor 默认：

- `ai_agent`
- `operator`
- `system`

## 索引建议

```sql
CREATE INDEX idx_usage_ledger_events_date
ON usage_ledger_events(date, provider, agent);

CREATE INDEX idx_usage_ledger_events_hour
ON usage_ledger_events(hour_start, provider, agent);

CREATE INDEX idx_usage_ledger_events_source
ON usage_ledger_events(source_id, provider, entry_at);

CREATE UNIQUE INDEX idx_usage_ledger_events_source_key
ON usage_ledger_events(provider, source_id, source_event_key);

CREATE INDEX idx_usage_ledger_dates_status
ON usage_ledger_dates(status, date);

CREATE INDEX idx_usage_ledger_import_runs_source
ON usage_ledger_import_runs(source_id, started_at);
```

D1 实现时需要按实际查询计划校验索引，不能只照搬。

## 与现有表的关系

| 现有表 | 新关系 |
| --- | --- |
| `usage_daily` | legacy daily baseline；切换前继续保留。 |
| `usage_hourly` | legacy hourly aggregate；切换前继续服务趋势。 |
| `usage_blocks` | Claude legacy blocks；不再作为新 ledger 主事实源。 |
| `usage_hourly_facts` | 可复用账号归因思想，但 ledger 需要事件级去重和冻结状态。 |
| `collection_runs` / `source_reports` | 继续保存普通采集健康；ledger 另有 import run。 |

迁移期可以 shadow build：

1. 写入新 ledger 表。
2. 同时保留现有 summary。
3. doctor 对比 legacy summary 与 ledger summary。
4. 通过后把 summary builder 的 usage 来源切换到 ledger rollup。

## 隐私约束

数据库不得保存：

- 原始 JSONL 路径。
- prompt / response / tool output。
- token / cookie / auth header。
- SSH 参数。
- 完整 provider 原始响应。

`metadata_json` 只能保存安全诊断字段，例如：

- parser version
- source schema version
- selected duplicate rule
- scan window
- redacted account attribution reason

## 数据库验收

| 验收项 | 通过标准 |
| --- | --- |
| 事件去重 | 重复上报同一事件，`usage_ledger_events` 行数和 rollup token 不增加。 |
| Codex 归档 | active + archived 同扫，同一天总量不下降、不重复增加。 |
| Claude 去重 | 重复 `message.id + requestId` 不重复入账。 |
| 冻结 | `frozen` 小时不能被普通 `incremental_report` 修改。 |
| 修正审计 | `repair` / `confirm` / `ignore` 均写入 `usage_ledger_revisions`。 |
| 兜底 | `usage_ledger_daily_fallbacks` 不生成小时数据。 |
| 隐私 | 表中不存在 `.codex`、`.claude` 路径或原始日志内容。 |
