# Data Freshness and Accuracy Interface Plan

Date: 2026-06-23
Status: draft

## 结论

不需要为了本轮目标新增 UI 接口，也不需要新增 Watch 直连接口。需要做的是：

1. 保持 `/api/mobile/summary` 为所有轻客户端的统一 DTO。
2. 在现有 API 或 health metadata 中补充数据来源和新鲜度信息。
3. 在 iPhone/Watch 本地 diagnostic 文件中补充缓存写入结果。
4. fact-check skill 读取这些证据，不把裸 DB 或旧 cache 误当实时事实。

## HTTP 接口

### `/api/mobile/summary`

继续作为 iPhone、iOS Widget、Watch handoff、macOS 菜单栏等轻客户端的主接口。

建议新增可选 `metadata` 字段，不破坏现有客户端：

```json
{
  "metadata": {
    "backend_mode": "cloudflare_proxy",
    "canonical_store": "origin_sqlite",
    "read_model_generated_at": "2026-06-23T22:22:36.480719+08:00",
    "freshness_status": "ok",
    "limits_observed_at": "2026-06-23T22:20:43.669815+08:00"
  }
}
```

允许值建议：

| 字段 | 允许值 / 含义 |
| --- | --- |
| `backend_mode` | `cloudflare_proxy`、`native_d1_staging`、`native_d1_production`、`origin_direct` |
| `canonical_store` | `origin_sqlite`、`cloudflare_d1` |
| `freshness_status` | `ok`、`stale`、`partial`、`unknown` |

客户端可以忽略该字段；核查工具和 diagnostics 应优先使用。

### `/api/summary`

Web summary 保持现有合同。建议与 mobile 一致增加 metadata，便于网页与手机核查同源：

```json
{
  "metadata": {
    "backend_mode": "cloudflare_proxy",
    "canonical_store": "origin_sqlite",
    "read_model_generated_at": "...",
    "limits_observed_at": "..."
  }
}
```

### `/api/health`

建议强化为运维/核查入口，增加：

```json
{
  "backend_mode": "cloudflare_proxy",
  "canonical_store": "origin_sqlite",
  "limits": {
    "latest_observed_at": "2026-06-23T22:20:43.669815+08:00",
    "effective_window_count": 4,
    "raw_window_count": 6,
    "stale_window_count": 2
  },
  "d1": {
    "database": "aiusage-prod-db",
    "limit_windows_count": 0,
    "latest_collection_run_at": "2026-06-23T22:20:35.261689+08:00"
  }
}
```

在 proxy 阶段，health 可以说明“入口在 Cloudflare，但 canonical store 仍是 origin SQLite”。这能避免用户把 Cloudflare route 误读成 D1 已经生产接管。

## Ingest 接口

### `/ingest`

本轮不改 contract。

### `/ingest-limits`

不新增必填字段。需要强化验收：

- origin 写入成功；
- native D1 shadow/dual-write 写入成功；
- D1 `limit_windows` 非空；
- read model 有效窗口与 origin API 一致。

如果后续要提升可核查性，可在成功响应里增加可选字段：

```json
{
  "success": true,
  "status": "accepted",
  "windows_written": 4,
  "accepted_at": "...",
  "canonical_store": "cloudflare_d1",
  "effective_windows_after_write": 4
}
```

## 本地诊断接口

这些不是 HTTP endpoint，但对本轮目标是必需接口。

### iPhone runtime diagnostic

当前已有：

- `status`
- `requestURL`
- `period`
- `generatedAt`
- `totalTokens`

建议新增：

```json
{
  "cacheWriteStatus": "ok",
  "cacheWrittenAt": "2026-06-23T22:23:01+08:00",
  "cacheSummaryGeneratedAt": "2026-06-23T22:22:36.480719+08:00",
  "watchPushStatus": "queued",
  "safeCacheError": null
}
```

失败时：

```json
{
  "cacheWriteStatus": "failed",
  "safeCacheError": "app_group_container_unavailable"
}
```

不得包含 token、Authorization header、Keychain raw status、完整本地路径。

### iPhone App Group summary

文件：`last-mobile-summary.json`

合同：

- 必须是 `/api/mobile/summary` DTO。
- 只写 `period=today` 的 companion summary。
- 成功写入后 diagnostic 记录 `cacheWriteStatus=ok`。
- 写入失败不清空旧 cache。

### WatchConnectivity context

当前 context 可继续携带 encoded `MobileSummary`。

合同：

- 仅同步 `period=today`。
- 发送失败或 session 未激活时，iPhone diagnostic 记录安全状态。
- context 不是最终落盘证据，只是传输证据。

### Watch App Group summary

文件：`last-watch-summary.json`

合同：

- 收到 context/userInfo 后写入。
- 写入成功后生成 receipt。
- Watch App / complication 读取本地 summary，不直连 API。

## 是否需要新接口

P0 不需要新增 HTTP endpoint。

可选未来接口：

| 接口 | 当前建议 | 原因 |
| --- | --- | --- |
| `POST /api/client-receipts` | 暂不做 | 本地 diagnostic 足够，新增上报扩大范围 |
| `GET /api/fact-check/status` | 暂不做 | skill 可直接读 API/DB/device；先不加公开面 |
| Watch 专用 summary endpoint | 不做 | Watch 不保存 token，不直连服务器 |

## 兼容性

- 所有新增 HTTP 字段必须可选。
- 旧客户端忽略 `metadata` 后行为不变。
- 新 diagnostic 字段只影响核查，不影响主 App 展示。
- API 不得输出 token、原始 provider response、原始 usage 日志路径。

## 接口验收

| 验收项 | 通过标准 |
| --- | --- |
| Mobile summary metadata | origin/proxy/native 模式可区分 |
| Health metadata | 能说明 D1 是否有有效 `limit_windows` |
| iPhone diagnostic | 能证明 API 成功和 App Group cache 写入结果 |
| Watch diagnostic | 能证明 Watch 收到并写入本地 cache |
| Backward compatibility | 旧 mobile summary decoder 不因 metadata 缺失或存在而失败 |
