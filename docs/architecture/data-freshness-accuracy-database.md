# Data Freshness and Accuracy Database Solution

Date: 2026-06-23
Status: draft

## 结论

本轮不应先改大 schema。当前核心问题主要是事实源选择、旧行过滤、Cloudflare D1 parity、客户端本地缓存落盘证据。数据库方案按三层处理：

1. 中心事实表继续保存采集事实。
2. read model 负责选出用户可见事实。
3. 客户端 App Group cache 保存 last good summary，并通过 diagnostic/receipt 证明落盘。

只有当这些还不能满足核查要求时，再新增服务端审计表。

## 中心数据库

### 当前源站 SQLite

当前生产源站表仍以 `docs/architecture/database.md` 的现状为准。与本轮最相关的是：

- `usage_daily`
- `usage_hourly`
- `usage_blocks`
- `source_reports`
- `source_identities`
- `usage_hourly_facts`
- `limit_windows`

### Cloudflare D1

D1 目标是接管同一套中心事实表。D1 未切流前，必须被视为 parity target，不是用户可见唯一事实源。

本次核查暴露的 D1 条件：

- D1 可以有 `collection_runs`，但 `limit_windows` 为空时，不能支撑 quota 展示。
- D1 parity 不能只看 usage totals；必须包括 source health 和 limits windows。
- `/ingest-limits` 的 dual-write / shadow-write 必须和 `/ingest` 一样被核查。

## `limit_windows` 解决方案

### 问题

裸查 `limit_windows` 会看到不同来源和历史行混合：

- 最新 official/runtime rows。
- 较早的 `active_limits_cache` rows。
- 已过期 reset 窗口。
- provider 失败或 stale 行。

如果核查者直接从裸表取“每个 provider/window 最新行”，可能得到和 UI 不一致的旧百分比。

### 目标规则

用户可见 quota 只从“有效窗口候选”选取：

```text
provider/window/source_id
  -> status == ok
  -> confidence == observed
  -> official/runtime source preferred
  -> reset_at not expired when applicable
  -> newest observed_at wins
```

`active_limits_cache` 只能作为低可信 fallback，且不能覆盖更新的 official/runtime 行。

### 数据库动作

P0 不新增字段，先在 read model 查询/筛选层收口。

P1 如 D1 性能或 parity 需要，再补索引：

```sql
CREATE INDEX IF NOT EXISTS idx_limit_windows_lookup
ON limit_windows (provider, window, source_id, status, confidence, observed_at DESC);
```

是否添加索引必须以 D1/SQLite 双端测试为准，不能只凭直觉加。

## 客户端本地缓存

客户端缓存不是中心数据库，但它是用户可见数据的本地持久层。

| 缓存 | 文件 | 解决方案 |
| --- | --- | --- |
| iPhone App Group summary | `last-mobile-summary.json` | 请求 today 成功后必须写入；失败要记录 diagnostic |
| iPhone runtime diagnostic | `last-mobile-runtime-diagnostic.json` | 增加 `cache_write_status`、`cache_written_at`、`watch_push_status` |
| Watch App Group summary | `last-watch-summary.json` | 收到 WatchConnectivity summary 后必须写入 |
| Watch receipt | 建议新增 `last-watch-cache-receipt.json` | 记录 decode/write/reload 结果，便于真机核查 |
| Mac popover cache | `last-summary.json` | 保留，核查时与 current collection 分开报告 |

### iPhone cache receipt 建议 shape

```json
{
  "schema_version": 1,
  "period": "today",
  "summary_generated_at": "2026-06-23T22:22:36.480719+08:00",
  "request_url": "https://aiusage.chunbai.com/api/mobile/summary?period=today",
  "cache_written_at": "2026-06-23T22:23:01+08:00",
  "cache_file": "last-mobile-summary.json",
  "cache_write_status": "ok",
  "watch_push_status": "queued",
  "safe_error": null
}
```

不得写入 token、Authorization header、完整本地路径或 provider 原始响应。

### Watch cache receipt 建议 shape

```json
{
  "schema_version": 1,
  "period": "today",
  "summary_generated_at": "2026-06-23T22:22:36.480719+08:00",
  "received_at": "2026-06-23T22:23:04+08:00",
  "cache_written_at": "2026-06-23T22:23:04+08:00",
  "cache_file": "last-watch-summary.json",
  "cache_write_status": "ok",
  "delivery": "watchconnectivity_application_context",
  "safe_error": null
}
```

## 是否需要服务端新增表

P0 不需要。

未来如果要长期追踪“哪些设备真的收到了 summary”，可以新增服务端 client receipt 表，但这会引入新上报接口和隐私边界，不作为当前必需项。

候选表仅供未来评审：

```sql
CREATE TABLE client_summary_receipts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  period TEXT NOT NULL,
  summary_generated_at TEXT,
  cache_written_at TEXT,
  receipt_type TEXT NOT NULL,
  status TEXT NOT NULL,
  safe_error TEXT,
  observed_at TEXT NOT NULL
);
```

当前不建议实现，原因：

- 单用户产品下，本地 devicectl/diagnostic 足够核查。
- 新接口会扩大攻击面。
- Watch/iPhone 本地 cache 问题应先在本地闭环解决。

## 数据库验收

| 验收项 | 通过标准 |
| --- | --- |
| SQLite read model | 旧 `active_limits_cache` 不再污染用户可见 quota |
| D1 parity | D1 usage、source health、limit windows 都与 origin API 对齐 |
| D1 `limit_windows` | 生产切流前非空，且最新 observed rows 与 origin 同口径 |
| Client cache | iPhone/Watch cache 文件可读、可 decode、period=today、generated_at 与 API/Watch context 对齐 |
| Diagnostics | cache write 失败时有安全错误摘要，不再静默消失 |
