# Usage Ledger Interface Design

Date: 2026-06-28
Status: draft for implementation planning
Related PRD: [`../product/usage-ledger-prd.md`](../product/usage-ledger-prd.md)
Related architecture: [`usage-ledger-architecture.md`](usage-ledger-architecture.md)
Related database: [`usage-ledger-database.md`](usage-ledger-database.md)

## 目标

定义 Usage Ledger 的本地 CLI、HTTP ingest、doctor 和 summary 接口。

本设计不要求普通用户通过 UI 或 Web 修复数据。确认、修复、忽略都由 AI agent / 运维通过无头 CLI 完成。

## 命令分层

推荐未来统一在现有 CLI 下新增子命令：

```text
ai-usage-widget usage-ledger ...
ai-usage-widget doctor usage-ledger ...
```

如果最终单独发布 `usage-ledger` 可执行文件，参数和 JSON 输出必须保持一致。

## 本地采集命令

### 总量重新统计

```bash
ai-usage-widget usage-ledger collect \
  --mode full_rescan \
  --since 2026-06-01 \
  --until 2026-06-27 \
  --provider codex \
  --provider claude \
  --timezone Asia/Shanghai \
  --output payload.json
```

用途：

- 首次历史回填。
- 异常日期重新核查。
- 晚到数据修正。

规则：

- 不作为日常定时任务。
- Codex 必须同时扫描 `~/.codex/sessions` 和 `~/.codex/archived_sessions`。
- Claude 扫描 `~/.claude/projects/**/*.jsonl`。
- 输出结构化 usage 明细，不输出原始路径或内容。

### 当前增量汇报

```bash
ai-usage-widget usage-ledger collect \
  --mode incremental_report \
  --lookback-hours 2 \
  --timezone Asia/Shanghai \
  --output payload.json
```

用途：

- 日常每 N 分钟上报。
- 更新当前小时。
- 满足条件后冻结上一个小时。

规则：

- 只能扫描最近窗口。
- Codex 最近窗口也必须同时扫 active + archived sessions。
- 候选集合必须包括最近发生变化的本地日志文件，不能只按 event entry_at 过滤。
- 不能重新计算历史总量。
- 不能覆盖今天之前已确认日期。

### 采集输出

本地采集命令输出 JSON：

```json
{
  "schema_version": 1,
  "collection_mode": "incremental_report",
  "source_id": "mac-local",
  "host": "host-mac-local",
  "machine": "machine-mac-local",
  "os_user": "os-user-main",
  "platform": "macOS",
  "timezone": "Asia/Shanghai",
  "observed_at": "2026-06-28T12:00:00+08:00",
  "scan_window": {
    "start_at": "2026-06-28T10:00:00+08:00",
    "end_at": "2026-06-28T12:00:00+08:00"
  },
  "events": [],
  "daily_fallbacks": [],
  "cutover_totals": [],
  "diagnostics": {
    "codex_scanned_active": true,
    "codex_scanned_archived": true,
    "claude_scanned": true,
    "scan_strategy": "changed_files_plus_time_window",
    "raw_paths_uploaded": false,
    "events_seen": 0,
    "events_selected": 0
  }
}
```

## 事件 payload

### Codex event

```json
{
  "event_id": "sha256:...",
  "provider": "codex",
  "agent": "codex",
  "entry_at": "2026-06-28T11:42:13+08:00",
  "timezone": "Asia/Shanghai",
  "usage": {
    "input_tokens": 123,
    "output_tokens": 456,
    "cache_creation_tokens": 0,
    "cache_read_tokens": 789,
    "reasoning_output_tokens": 0,
    "total_tokens": 1368
  },
  "source_event_key": "sanitized-codex-key",
  "source_session_id": "safe-session-id",
  "source_request_id": null,
  "source_message_id": null,
  "model": null,
  "account": {
    "provider": "openai",
    "account_id": null,
    "attribution_status": "unconfirmed_local_source"
  },
  "provenance": "codex_token_count",
  "metadata": {
    "duplicate_rule": "codex_session_token_count_ordinal",
    "record_time_semantics": "local_log_record_time"
  }
}
```

Codex `event_id` 必须由 provider、source、session、`token_count.timestamp` 和 session 内稳定 token_count 序号生成。不能包含原始路径、归档目录、glob 顺序或不稳定行 hash；active 与 archived 中的同一事件必须生成同一 ID。

### Claude event

```json
{
  "event_id": "sha256:...",
  "provider": "claude",
  "agent": "claude",
  "entry_at": "2026-06-28T11:45:00+08:00",
  "timezone": "Asia/Shanghai",
  "usage": {
    "input_tokens": 1000,
    "output_tokens": 2000,
    "cache_creation_tokens": 0,
    "cache_read_tokens": 3000,
    "reasoning_output_tokens": 0,
    "total_tokens": 6000
  },
  "source_event_key": "msg_xxx:req_yyy",
  "source_session_id": null,
  "source_request_id": "req_yyy",
  "source_message_id": "msg_xxx",
  "model": "claude-opus",
  "account": {
    "provider": "anthropic",
    "account_id": null,
    "attribution_status": "unconfirmed_local_source"
  },
  "provenance": "claude_assistant_usage",
  "metadata": {
    "duplicate_rule": "message_id_request_id_max_usage_then_latest",
    "record_time_semantics": "local_log_record_time"
  }
}
```

Claude `event_id` 必须只由 provider、source、`message.id` 和 `requestId` 等去重身份生成，不能包含 usage 数字。后续扫描如果发现同一 key 的最终 usage 变大，服务端必须更新同一事件并写 revision，而不是新增事件。

## HTTP ingest

建议新增专用 endpoint：

```http
POST /ingest-usage-ledger
Authorization: Bearer <token>
Content-Type: application/json
```

说明：

- 与现有 `/ingest` 隔离，避免 ledger full rescan 影响 legacy daily ingest。
- 认证方式沿用现有 Bearer token。
- 如果实现团队决定复用 `/ingest`，必须保持同样的 payload shape 和响应语义，并在 review 中说明原因。

### 请求

```json
{
  "schema_version": 1,
  "collection_mode": "incremental_report",
  "source_id": "mac-local",
  "host": "host-mac-local",
  "machine": "machine-mac-local",
  "os_user": "os-user-main",
  "platform": "macOS",
  "timezone": "Asia/Shanghai",
  "observed_at": "2026-06-28T12:00:00+08:00",
  "scan_window": {
    "start_at": "2026-06-28T10:00:00+08:00",
    "end_at": "2026-06-28T12:00:00+08:00"
  },
  "events": [],
  "daily_fallbacks": [],
  "cutover_totals": [],
  "diagnostics": {}
}
```

### Cutover total

上线切换日如果需要拼接“切换前今日总量 + 切换后 ledger 增量”，客户端可上报：

```json
{
  "date": "2026-06-28",
  "provider": "codex",
  "agent": "codex",
  "source_id": "mac-local",
  "timezone": "Asia/Shanghai",
  "cutover_at": "2026-06-28T10:30:00+08:00",
  "usage": {
    "input_tokens": 100,
    "output_tokens": 200,
    "cache_creation_tokens": 0,
    "cache_read_tokens": 300,
    "reasoning_output_tokens": 0,
    "total_tokens": 600
  },
  "source_type": "cutover_pre_total"
}
```

规则：

- 该 total 覆盖 `< cutover_at`。
- 切换后 ledger events 覆盖 `>= cutover_at`。
- 服务端不能把两段重叠相加。
- 后续 full rescan 如果补齐 `< cutover_at` 的明细事件，服务端必须把该 `cutover_pre_total` 标记为 `superseded`，并从汇总中移除。

批量限制：

- payload 必须支持分批上传。
- 单批建议上限由实现验证确定；超过上限应返回可重试错误。
- 客户端必须能用同一 batch 重试，服务端靠 `event_id` / `source_event_key` 保证幂等。
- 同一 `source_event_key` 如果选中 usage 发生变化，响应应计入 `events_updated`，并触发受影响小时重算。
- `source_event_key` 是去重权威；如果 `event_id` 与既有行不同但 `source_event_key` 命中，服务端必须按同一事件更新，不能新增计数。

### 成功响应

```json
{
  "success": true,
  "status": "accepted",
  "source_id": "mac-local",
  "accepted_at": "2026-06-28T12:00:03+08:00",
  "collection_mode": "incremental_report",
  "import_run_id": "run_...",
  "events_seen": 120,
  "events_inserted": 12,
  "events_updated": 0,
  "events_duplicate": 108,
  "daily_fallbacks_seen": 0,
  "cutover_totals_seen": 0,
  "hours_updated": 2,
  "hours_frozen": 1,
  "dates_marked_pending": 0
}
```

### 错误响应

```json
{
  "success": false,
  "status": "error",
  "error_type": "usage_ledger_schema_invalid",
  "message": "events[0].event_id is required"
}
```

常见错误：

| error_type | 含义 |
| --- | --- |
| `http_auth_failed` | Bearer token 缺失或错误。 |
| `usage_ledger_schema_invalid` | payload shape 不合法。 |
| `usage_ledger_sensitive_payload` | 出现 `.codex`、`.claude`、原始路径或敏感内容。 |
| `usage_ledger_batch_too_large` | 单批过大，需要分批。 |
| `usage_ledger_write_failed` | DB 写入失败。 |

## Doctor 命令

### 总览

```bash
ai-usage-widget doctor usage-ledger --json
```

输出：

```json
{
  "success": true,
  "doctor": "usage-ledger",
  "generated_at": "2026-06-28T12:10:00+08:00",
  "summary": {
    "latest_incremental_report_at": "2026-06-28T12:05:00+08:00",
    "today_status": "live",
    "pending_dates": 1,
    "fallback_dates": 0,
    "repair_pending_hours": 0,
    "contains_estimated_data": false,
    "contains_pending_data": true
  },
  "account_attribution": {
    "confirmed_accounts": 0,
    "unconfirmed_local_sources": 2,
    "unknown_sources": 0
  },
  "cutover": {
    "is_cutover_day": true,
    "cutover_at": "2026-06-28T10:30:00+08:00",
    "pre_total_status": "active"
  },
  "findings": [
    {
      "severity": "warning",
      "code": "pending_date",
      "date": "2026-06-27",
      "provider": "claude",
      "message": "Claude duplicate rule still needs daily reconciliation",
      "next_action": "ai-usage-widget usage-ledger confirm --date 2026-06-27 --provider claude"
    }
  ]
}
```

### 确认日期

```bash
ai-usage-widget usage-ledger confirm \
  --date 2026-06-27 \
  --provider claude \
  --reason "ccusage daily reconciliation within threshold"
```

### 修复日期

```bash
ai-usage-widget usage-ledger repair \
  --date 2026-06-27 \
  --provider codex \
  --from-run run_...
```

### 忽略差异

```bash
ai-usage-widget usage-ledger ignore \
  --date 2026-06-27 \
  --provider codex \
  --reason "known duplicate archived copy outside accepted window"
```

命令要求：

- 默认输出机器可读 JSON。
- 不打印 token、原始路径、prompt、response。
- 修改状态的命令必须写审计记录。
- 非 dry-run 修改必须返回 revision id。

## Summary 接口

普通客户端继续使用：

- `GET /api/summary`
- `GET /api/mobile/summary`

period 口径不变：

- `today`
- `week`：现有近 7 天窗口。
- `month`：现有近 30 天窗口。
- `all`

Usage Ledger 切换后，summary 的 usage 数据源应来自 ledger rollup，但响应 shape 应保持兼容。

汇总过滤规则：

- `today` 是 live 日期，始终纳入。
- `week` / `month` / `all` 中今天之前的日期默认只纳入 confirmed 数据。
- 如果汇总包含 pending 或 fallback estimated 数据，metadata 必须显式标记，供 doctor / AI agent 判断。

建议增加可选 metadata，供 doctor / AI agent 使用，普通客户端可忽略：

```json
{
  "metadata": {
    "usage_ledger": {
      "enabled": true,
      "source": "ledger_rollup",
      "contains_pending_data": false,
      "contains_estimated_data": false,
      "cutover_at": "2026-06-28T10:30:00+08:00"
    }
  }
}
```

## Health 接口

`GET /api/health` 可选增加 ledger 摘要：

```json
{
  "usage_ledger": {
    "enabled": true,
    "latest_incremental_report_at": "2026-06-28T12:05:00+08:00",
    "latest_full_rescan_at": "2026-06-28T09:00:00+08:00",
    "pending_dates": 0,
    "fallback_dates": 0,
    "repair_pending_hours": 0
  }
}
```

这不是用户 UI 操作入口，只是 AI agent / 运维核查证据。

## 安全校验

Ingest 必须拒绝：

- 字段值包含 `.codex` 或 `.claude` 原始路径。
- 字段名包含原始日志路径语义。
- payload 包含 prompt、response、tool output。
- payload 包含 SSH 参数。
- payload 包含 token、cookie、Authorization header。

账号归因不确定时：

```json
{
  "account": {
    "provider": "openai",
    "account_id": null,
    "attribution_status": "unconfirmed_local_source"
  }
}
```

## 验收

| 验收项 | 通过标准 |
| --- | --- |
| `full_rescan` | 可按日期范围生成批量 payload；Codex 扫 active + archived。 |
| `incremental_report` | 可按 lookback 窗口生成 payload；不会重算历史总量。 |
| HTTP 幂等 | 同一 batch 重试不会重复计数。 |
| Doctor | 输出 pending / fallback / repair 状态和下一步 CLI 动作。 |
| 晚到发现 | 刚写入但 entry_at 早于扫描窗口的事件，增量上报仍能通过变更文件扫描发现。 |
| 状态命令 | `confirm` / `repair` / `ignore` 修改状态并返回 revision id。 |
| Summary 兼容 | 现有 Web / Mobile 客户端无需改解析即可继续读 summary。 |
| 安全 | CLI、HTTP 响应、doctor 输出均不含原始路径和敏感内容。 |
