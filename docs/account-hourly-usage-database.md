# Database Design: Account Hourly Usage

## 目标

SQLite 继续作为个人 usage 的 canonical store。新设计新增小时事实表，把机器、OS 登录用户、AI 登录账号都作为正式维度。

旧 `usage_daily` 可以保留兼容，但账号归因视图应以新的 hourly facts 为准。

## 表结构

### `machines`

保存机器维度。

```sql
CREATE TABLE machines (
  machine_id TEXT PRIMARY KEY,
  machine_name TEXT NOT NULL,
  host TEXT,
  platform TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);
```

### `os_identities`

保存机器登录用户维度。

```sql
CREATE TABLE os_identities (
  machine_id TEXT NOT NULL,
  os_user TEXT NOT NULL,
  display_name TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY (machine_id, os_user),
  FOREIGN KEY (machine_id) REFERENCES machines(machine_id)
);
```

### `ai_accounts`

保存 AI 登录账号维度。

```sql
CREATE TABLE ai_accounts (
  provider TEXT NOT NULL,
  account_id TEXT NOT NULL,
  account_label TEXT NOT NULL,
  display_name TEXT,
  subscription TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY (provider, account_id)
);
```

说明：

- `provider`: `openai` / `anthropic`。
- `account_id`: 优先使用 provider id；没有时使用稳定 hash；未知时为 `unknown`。
- `account_label`: UI 可读标签，例如邮箱。
- 不保存 token、refresh token、cookie。

### `usage_hourly_facts`

保存小时 usage 事实。

```sql
CREATE TABLE usage_hourly_facts (
  fact_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  machine_id TEXT NOT NULL,
  os_user TEXT NOT NULL,
  ai_provider TEXT NOT NULL,
  ai_account_id TEXT NOT NULL,
  agent TEXT NOT NULL,
  client TEXT,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  timezone TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  total_cost REAL,
  event_count INTEGER NOT NULL DEFAULT 0,
  session_count INTEGER NOT NULL DEFAULT 0,
  attribution_confidence TEXT NOT NULL,
  provenance TEXT NOT NULL,
  account_evidence_json TEXT,
  metadata_json TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  FOREIGN KEY (machine_id, os_user) REFERENCES os_identities(machine_id, os_user),
  FOREIGN KEY (ai_provider, ai_account_id) REFERENCES ai_accounts(provider, account_id)
);
```

推荐索引：

```sql
CREATE INDEX idx_usage_hourly_facts_window
  ON usage_hourly_facts(window_start, window_end);

CREATE INDEX idx_usage_hourly_facts_account
  ON usage_hourly_facts(ai_provider, ai_account_id, window_start);

CREATE INDEX idx_usage_hourly_facts_machine_user
  ON usage_hourly_facts(machine_id, os_user, window_start);

CREATE INDEX idx_usage_hourly_facts_agent
  ON usage_hourly_facts(agent, window_start);

CREATE INDEX idx_usage_hourly_facts_source
  ON usage_hourly_facts(source_id, window_start);

CREATE UNIQUE INDEX idx_usage_hourly_facts_unique_hour
  ON usage_hourly_facts(
    source_id,
    agent,
    COALESCE(client, ''),
    window_start,
    window_end,
    ai_provider,
    ai_account_id,
    attribution_confidence,
    provenance
  );
```

### `usage_hourly_models`

保存模型拆分。

```sql
CREATE TABLE usage_hourly_models (
  fact_id TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  total_cost REAL,
  metadata_json TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY (fact_id, model),
  FOREIGN KEY (fact_id) REFERENCES usage_hourly_facts(fact_id)
);
```

### `source_status_hourly`（后续阶段）

当前实现仍沿用既有 `source_reports` / `collection_runs` 提供 source health。下面这张表是账号小时采集器状态细化后的后续扩展，不属于第一版已上线表。

保存每次采集状态。

```sql
CREATE TABLE source_status_hourly (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL,
  machine_id TEXT NOT NULL,
  os_user TEXT NOT NULL,
  status_scope TEXT NOT NULL,
  collector_key TEXT,
  agent TEXT,
  provider TEXT,
  observed_at TEXT NOT NULL,
  timezone TEXT NOT NULL,
  status TEXT NOT NULL,
  error_type TEXT,
  message TEXT,
  facts_accepted INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
```

推荐索引：

```sql
CREATE INDEX idx_source_status_hourly_latest
  ON source_status_hourly(source_id, status_scope, COALESCE(collector_key, ''), observed_at);
```

### `collector_cursors`（后续阶段）

当前第一版不在服务端管理本地日志 cursor；终端采集器仍应在本机保存 cursor。下面这张表是后续需要跨采集器审计或恢复时的扩展。

保存本地或服务端去重 cursor。服务端可以保存接收到的 cursor，真正读取本地日志的 cursor 仍建议保存在本机。

```sql
CREATE TABLE collector_cursors (
  source_id TEXT NOT NULL,
  cursor_name TEXT NOT NULL,
  cursor_value TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (source_id, cursor_name)
);
```

## 幂等规则

`fact_id` 是单条 usage fact 的主键，但不是唯一的幂等保护。

小时聚合事实必须同时依赖稳定唯一约束：

```text
(source_id, agent, client, window_start, window_end, ai_provider, ai_account_id, attribution_confidence, provenance)
```

事件级去重不能混进小时聚合 key。若后续需要事件级审计，单独增加 `usage_events_seen` 表保存事件 hash。

小时聚合 `fact_id` 可以稳定为：

```text
<agent>:<client>:<source_id>:<window_start>:<window_end>:<attribution_confidence>:<ai_provider>:<account_id>:<provenance>
```

同一 `fact_id` 重复上传时：

- 更新 token 数值。
- 更新 `last_seen_at`。
- 保留 `first_seen_at`。
- 覆盖 metadata。

## 查询示例

### 今日按 AI 账号

```sql
SELECT
  f.ai_provider,
  f.ai_account_id,
  a.account_label,
  SUM(f.total_tokens) AS total_tokens
FROM usage_hourly_facts f
JOIN ai_accounts a
  ON a.provider = f.ai_provider
 AND a.account_id = f.ai_account_id
WHERE f.window_start >= ?
  AND f.window_start < ?
  AND f.attribution_confidence = 'observed'
GROUP BY f.ai_provider, f.ai_account_id, a.account_label
ORDER BY total_tokens DESC;
```

账号页可以另外返回 confidence breakdown，把 inferred 单独展示：

```sql
SELECT
  f.ai_provider,
  f.ai_account_id,
  a.account_label,
  f.attribution_confidence,
  SUM(f.total_tokens) AS total_tokens
FROM usage_hourly_facts f
JOIN ai_accounts a
  ON a.provider = f.ai_provider
 AND a.account_id = f.ai_account_id
WHERE f.window_start >= ?
  AND f.window_start < ?
GROUP BY f.ai_provider, f.ai_account_id, a.account_label, f.attribution_confidence
ORDER BY total_tokens DESC;
```

### 今日按机器

```sql
SELECT
  f.machine_id,
  m.machine_name,
  SUM(f.total_tokens) AS total_tokens
FROM usage_hourly_facts f
JOIN machines m ON m.machine_id = f.machine_id
WHERE f.window_start >= ?
  AND f.window_start < ?
GROUP BY f.machine_id, m.machine_name
ORDER BY total_tokens DESC;
```

### 今日按机器登录用户

```sql
SELECT
  f.machine_id,
  m.machine_name,
  f.os_user,
  SUM(f.total_tokens) AS total_tokens
FROM usage_hourly_facts f
JOIN machines m ON m.machine_id = f.machine_id
WHERE f.window_start >= ?
  AND f.window_start < ?
GROUP BY f.machine_id, m.machine_name, f.os_user
ORDER BY total_tokens DESC;
```

### 某账号按机器拆分

```sql
SELECT
  f.machine_id,
  m.machine_name,
  f.os_user,
  f.agent,
  SUM(f.total_tokens) AS total_tokens
FROM usage_hourly_facts f
JOIN machines m ON m.machine_id = f.machine_id
WHERE f.ai_provider = ?
  AND f.ai_account_id = ?
  AND f.window_start >= ?
  AND f.window_start < ?
GROUP BY f.machine_id, m.machine_name, f.os_user, f.agent
ORDER BY total_tokens DESC;
```

## 与旧表关系

保留旧表：

- `usage_daily`
- `usage_hourly`
- `usage_blocks`
- `source_identities`
- `limit_windows`

新增表不要求立即删除旧表。

迁移期：

- Web / Mobile summary 先通过 snapshot/API 聚合层读取新 hourly facts。
- Headline daily total 在迁移期继续保护旧 daily baseline；没有新 hourly facts 的历史日期，继续显示旧 daily totals。
- 账号归因、最近一小时和小时趋势读取新 hourly facts。
- 账号归因只对新 hourly facts 展示强结论。
- 同一时间范围同时存在新 hourly facts 和旧 `usage_hourly` 时，账号视图只读新表，避免双算。
- 非账号视图需要明确 cutover：新表覆盖的时间范围优先读新表；旧表只作为没有新表覆盖时的 fallback。

## 数据保留

建议保留：

- 小时 facts：长期保留。
- model breakdown：长期保留。
- source status：至少 90 天。
- 本地 cursor：长期保留。

不保存：

- 原始 JSONL 行。
- prompt / response。
- tool output。
- auth token。
- refresh token。
- cookie。
