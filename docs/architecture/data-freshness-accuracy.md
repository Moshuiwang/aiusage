# Data Freshness and Accuracy Architecture

Date: 2026-06-23
Status: draft

## 结论

数据准确性的架构目标不是让所有端“实时同一秒刷新”，而是让每一层都具备可证明的事实：

```text
device collectors
  -> ingest / ingest-limits
  -> canonical store
  -> read model API
  -> platform cache
  -> user-visible surface
```

用户可见数字只能来自 read model API 或它写入的客户端缓存。裸表、旧 fixture、WatchConnectivity 内部文件、调试日志只能作为核查证据，不能直接定义产品事实。

## 当前问题分层

| 层 | 当前发现 | 架构判断 |
| --- | --- | --- |
| Collector | Mac current limits 能拿到最新 official/runtime 值 | 采集本身可用，但和展示缓存存在时间差 |
| Origin API | 阿里源站 `/api/mobile/summary` 输出接近用户可见事实 | API read model 是当前生产主事实源 |
| Origin DB | `limit_windows` 裸表有旧 `active_limits_cache` 行 | 裸表不能直接当 UI 事实源 |
| Cloudflare | `aiusage.chunbai.com` 仍是 proxy，D1 `limit_windows` 当前为空 | Cloudflare 入口不等于 Cloudflare 数据源 |
| Mac cache | popover `last-summary.json` 可能落后当前采集 | 需要核查时区分 current collection 和 cache |
| iPhone cache | runtime diagnostic 可读，但 App Group summary cache 未核到 | 需要把 cache write 变成可证明事件 |
| Watch sync | iPhone-side WatchConnectivity context 可读 | 只能证明 iPhone 发出，不证明 Watch 写入 |
| Watch cache | Watch App Group cache 设计存在，但真机核查未稳定证明 | 需要 Watch 侧 cache receipt |

## 事实源定义

### Canonical Store

中心事实存储：

- 当前生产：阿里源站 SQLite。
- 迁移目标：Cloudflare D1 production。

Canonical store 保存采集事实，不直接定义每端 UI 状态。

### Read Model

用户可见事实源：

- Web：`/api/summary`
- Mobile/light clients：`/api/mobile/summary`

Read model 负责把 usage、source health、quota windows、账号标签、周期信息整理成客户端可显示 DTO。客户端不得绕过 read model 自己聚合。

### Platform Cache

客户端本地缓存：

| 平台 | 缓存 | 用途 | 是否权威 |
| --- | --- | --- | --- |
| Mac menu bar | `macos-menu-bar/last-summary.json` | popover 快速展示 | 不是；是上一次 API/summary cache |
| iPhone App | runtime diagnostic | 核查请求和写缓存状态 | 不是；是证据 |
| iPhone App Group | `last-mobile-summary.json` | iOS Widget / Watch handoff fallback | 是该设备的 last good summary |
| WatchConnectivity | application context | iPhone 到 Watch 的传输证据 | 不是；是传输层 |
| Watch App Group | `last-watch-summary.json` | Watch App / complication 本地展示 | 是 Watch 端 last good summary |

## 数据新鲜度合同

每个 summary 或 cache receipt 至少要能回答四个问题：

| 字段 | 含义 |
| --- | --- |
| `generated_at` | 服务端 read model 生成时间 |
| `observed_at` | provider/source 采集到事实的时间，尤其是 limits windows |
| `cache_written_at` | 客户端成功写入本地 cache 的时间 |
| `source_endpoint` / `backend_mode` | 数据来自 origin proxy 还是 native D1 |

`generated_at` 不是 `observed_at`。例如 quota window 可能在 22:20 被观测，API 在 22:22 生成，iPhone cache 在 22:23 写入。核查表必须保留这些差异。

## 推荐链路

### iPhone 前台刷新

```text
iPhone App foreground
  -> GET /api/mobile/summary?period=<visible period>
  -> if period == today:
       write iPhone App Group last-mobile-summary.json
       write runtime diagnostic with cache_write_status
       push WatchConnectivity context
       schedule Watch refresh
  -> if period != today:
       only update visible app state
```

Watch 和 widget 的 companion 口径固定为 `today`，不跟随用户当前停留的 week/month/all 页面。

### iPhone 后台刷新

```text
BGAppRefreshTask
  -> GET /api/mobile/summary?period=today
  -> write App Group cache
  -> push WatchConnectivity
  -> diagnostic receipt
```

后台刷新不能承诺准点执行；因此缓存 receipt 比 UI 承诺更重要。

### Watch 接收

```text
WCSession didReceiveApplicationContext / didReceiveUserInfo
  -> decode MobileSummary
  -> write Watch App Group last-watch-summary.json
  -> reload WidgetKit timelines when applicable
  -> write a small receipt for diagnostics
```

Watch 不直接调服务器，也不保存 token。

## 服务端 read model 规则

Quota windows 的展示候选必须满足：

- `official == true` 或来源被明确标记为可信 runtime/official；
- `confidence == observed`；
- `status == ok`；
- `observed_at` 在当前 freshness window 内，或者 `reset_at` 尚未过期；
- 同一 `(source_id, provider, window)` 只选择最新有效行；
- 旧 `active_limits_cache` 行不能覆盖更新的 official/runtime 行。

如果没有有效行，read model 应输出“无可用官方窗口”，而不是从旧缓存补一个看似正常的百分比。

## Cloudflare / Origin 边界

当前必须显式区分：

| 名称 | 含义 |
| --- | --- |
| `cloudflare_proxy` | `aiusage.chunbai.com` Worker 反代阿里源站 |
| `origin_sqlite` | 阿里源站 SQLite 是生产事实源 |
| `native_d1_staging` | Cloudflare Native Worker + D1 staging/prod DB，用于 parity |
| `native_d1_production` | 切流后 D1 成为生产事实源 |

Cloudflare D1 如果没有 `limit_windows` 数据，就不能被描述为“当前 Cloudflare quota 数据正确”。只能说入口在 Cloudflare，事实源仍在 origin。

## 核查工具对齐

`ai-usage-fact-check` 应按固定顺序核查：

1. Mac current collection。
2. Mac popover cache。
3. iPhone runtime diagnostic。
4. iPhone App Group summary cache。
5. iPhone WatchConnectivity context。
6. Watch App Group cache。
7. Aliyun origin API + DB。
8. Cloudflare route + D1。

每个来源输出同一列：`Codex 5h`、`Codex 7d`、`Claude 5h`、`Claude 7d`、更新时间、核查方式、可能问题。

## 不做的架构变化

- 不让 Watch 直连 API。
- 不把 token 放进 App Group。
- 不让客户端聚合 SQLite/D1。
- 不把 URLCache 当作可核查事实源；iPhone API client 继续 `reloadIgnoringLocalCacheData`。
- 不通过 UI 改版掩盖数据链路问题。
