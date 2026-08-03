# Interface Architecture

本文是当前服务接口的索引。HTTP path、请求校验和响应 shape 以
`src/ai_usage_widget/server.py`、`server_services.py`、`ingest.py`、
`mobile_summary.py` 和 `snapshot_builder.py` 为唯一权威来源。

## 单一权威来源

- HTTP adapter：`src/ai_usage_widget/server.py`
- 服务编排：`src/ai_usage_widget/server_services.py`
- Usage ingest contract：`src/ai_usage_widget/ingest.py`
- Limits contract：`src/ai_usage_widget/limits.py` + `server_services.validate_limits_ingest_payload()`
- Web summary read model：`src/ai_usage_widget/snapshot_builder.py`
- Mobile DTO：`src/ai_usage_widget/mobile_summary.py`

旧的 `*-interface.md` 设计稿只作为历史参考，不再定义当前接口。

## 当前 HTTP 接口

| Method | Path | Auth | 当前用途 |
| --- | --- | --- | --- |
| `POST` | `/ingest` | Bearer token | 终端主动 push usage payload。 |
| `POST` | `/ingest-limits` | Bearer token | provider / runtime push limits windows。 |
| `POST` | `/login` | token 表单或 JSON | Web 登录，成功后写 cookie。 |
| `GET` | `/api/summary` | Bearer token 或 cookie | Web dashboard summary read model。 |
| `GET` | `/api/mobile/summary` | Bearer token 或 cookie | iOS / Android / 轻量客户端 DTO。 |
| `GET` | `/api/health` | Bearer token 或 cookie | 服务、SQLite、snapshot 和 source 状态摘要。 |
| `GET` | `/`、`/dashboard` | cookie 或登录页 | Web dashboard 页面。 |
| `GET` | `/login` | no | 登录页面。 |
| `GET` | `/static/*` | Bearer token 或 cookie | dashboard 静态资源。 |

`/api/summary` 和 `/api/mobile/summary` 当前查询参数一致：

- `date`：目标日期，缺省为服务进程当前日期。
- `period`：`today`、`week`、`month`、`all`。
- `machine`：可选机器过滤。
- `account`：可选 OS user / account 过滤。

## Usage Ingest

`POST /ingest` 的必填字段来自 `validate_ingest_payload()`：

- `schema_version`
- `source_id`
- `host`
- `os_user`
- `timezone`
- `observed_at`

可选字段：

- `machine`
- `platform`
- `collection_window`
- `usage_daily`
- `ccusage_daily_report`
- `ccusage_session_report`
- `mswusage_codex_hourly_report`
- `codex_hourly_status`
- `usage_hourly_facts`
- `collection_status`
- `error_type`
- `error_message`

安全边界：

- payload 中不得出现 `.claude`、`.codex` 原始日志路径或敏感 key。
- payload 中不得出现 SSH 参数。
- 认证失败返回 `http_auth_failed`。
- schema 错误返回 `http_schema_invalid`。

成功响应：

```json
{
  "status": "accepted",
  "source_id": "source-id",
  "accepted_at": "2026-06-21T12:00:00+08:00",
  "facts_accepted": 0,
  "message": "Data accepted successfully"
}
```

## Limits Ingest

`POST /ingest-limits` 当前要求：

- `schema_version` 必须为 `1`
- `observed_at` 必须是 ISO 8601 datetime
- `windows` 必须是列表

每个 window 必填：

- `provider`
- `window`
- `reset_at`
- `observed_at`

每个 window 可选：

- `source_id`
- `used_percent`
- `remaining_percent`
- `window_duration_minutes`
- `source_type`
- `confidence`
- `status`

成功响应：

```json
{
  "success": true,
  "status": "accepted",
  "windows_written": 1,
  "accepted_at": "2026-06-21T12:00:00+08:00"
}
```

## Web Summary

`GET /api/summary` 由 `snapshot_builder.py` 输出当前 v1 read model，顶层字段为：

- `schema_version`
- `generated_at`
- `timezone`
- `summary`
- `groups`
- `items`
- `trend`
- `source_status`
- `limits`
- `account_hourly`
- `ai_accounts`
- `metadata`

旧根架构文档中的 `limits.used`、`limits.limit`、`used_percentage`、`resets_at`
不是当前代码输出字段。当前字段是 `used_percent`、`remaining_percent`、
`reset_at`、`window_duration_minutes`、`official` 等。

## Mobile Summary

`GET /api/mobile/summary` 由 `/api/summary` 派生，只做 DTO 转换和字段裁剪，不重新聚合业务口径。

当前顶层字段：

- `schema_version`
- `client`
- `generated_at`
- `timezone`
- `period`
- `trend`
- `sources`
- `breakdown`
- `limits`

当前目标客户端：

- iPhone App / iOS Widget 使用 mobile summary。
- iPhone App 后台刷新使用 `period=today` 的 mobile summary，并把结果同步给 Apple Watch。
- Apple Watch App 和表盘组件不直接调用本接口；它们只读取 iPhone 同步过来的本地摘要。
- Android、macOS 菜单栏、Windows 托盘后续也复用 mobile summary 或由它裁剪的轻量摘要。
- 客户端不得直接读取 SQLite，不得执行 `ccusage`、SSH 或 provider。

### Apple Watch 刷新合同

本轮不新增 Watch 专用 HTTP endpoint。Watch 看到的数据来自这条本地链路：

```text
/api/mobile/summary?period=today
  -> iPhone App cache
  -> WatchConnectivity
  -> Watch App Group cache
  -> Watch App / Watch WidgetKit accessory
```

Watch 所需字段必须来自 mobile summary 已有字段：

- `generated_at` 和 `timezone`：用于更新时间和 stale 判断。
- `period.total_tokens`、`period.input_tokens`、`period.output_tokens`、`period.cache_tokens`：用于 today usage 展示。
- `trend`：用于 today chart complication。
- `limits.windows`：用于 Codex / Claude quota ring。
- `sources`：用于判断 source health 和可解释的 stale/error。

用户在 iPhone 前台选择 week/month/all 不改变 Watch 表盘刷新口径；后台和表盘只同步 today summary。这样表盘语义稳定，不会因为 iPhone 页面停留在某个筛选项而显示错口径。

失败语义：

- HTTP 失败不清空 iPhone 或 Watch 已有缓存。
- WatchConnectivity 延迟不算接口失败，只表示 Watch 暂时展示旧缓存。
- 超过 freshness window 时客户端显示 stale，不把旧数据当成实时。

## 错误模型

HTTP 错误响应统一 shape：

```json
{
  "status": "error",
  "error_type": "http_schema_invalid",
  "message": "..."
}
```

常见 `error_type`：

- `http_auth_failed`
- `http_schema_invalid`
- `limit_schema_invalid`
- `not_found`
- `read_failed`
- `write_failed`
- `internal_error`

历史文档中出现过但当前并非所有路径都会直接返回的错误类型，只能作为设计参考或 source status 分类，不应被客户端当成完整枚举。

## Data freshness / accuracy design

数据来源、缓存落盘、`backend_mode` / `canonical_store` metadata、iPhone/Watch
本地 diagnostic 的接口规划见
[`data-freshness-accuracy-interfaces.md`](data-freshness-accuracy-interfaces.md)。
该文档是后续实现规划，新增 HTTP 字段必须保持可选，不能破坏当前客户端。
