# Interface Design: Multi-Platform AI Usage Experience

## 目标

接口要支持最新多端设计，同时保持展示端只读：

- Web Dashboard 读完整 summary。
- macOS、iOS Widget、Watch 读轻量 summary。
- 所有端看到同一个 period 下的同一套事实。

优先复用现有接口，不为了视觉改版新增采集接口。

## 现有接口

| Endpoint | 用途 | 新设计使用方式 |
| --- | --- | --- |
| `GET /api/summary` | Web Dashboard 完整摘要 | Web 高保真改版继续使用。 |
| `GET /api/mobile/summary` | 移动端 / 轻量端摘要 | macOS、iOS Widget、Watch 优先复用。 |
| `POST /ingest` | 终端 usage 上报 | 不因本设计改动。 |
| `POST /ingest-limits` | limits 上报 | 不因本设计改动。 |
| `GET /api/health` | 服务健康 | 可用于设置页或诊断，不进入主视觉。 |

## 查询参数

`/api/summary` 和 `/api/mobile/summary` 当前主屏默认只需要全局摘要：

| 参数 | 示例 | 说明 |
| --- | --- | --- |
| `period` | `today` | `today` / `week` / `month` / `all`。 |
| `date` | `2026-06-19` | 可选，默认服务端按配置时区计算当前日期。 |

过滤参数只用于 drilldown 或调试，不用于 Web、macOS、iOS Widget、Watch 的主屏总量：

| 参数 | 示例 | 说明 |
| --- | --- | --- |
| `machine` | `macbook-pro` | 可选，仅用于机器明细。 |
| `account` | `wangzhipeng` | 可选，仅用于用户或账号明细。 |

周期切换必须重新请求 API，例如：

```http
GET /api/mobile/summary?period=week
Authorization: Bearer <token>
```

时区规则：

- 客户端不传 timezone，也不按本机时区自行计算 today/week/month/all。
- 服务端按返回的 `timezone` 计算 period 边界、trend bucket、source contribution 和 delta 对比周期。
- 所有入口展示同一个 period 时，必须使用同一个服务端响应。

## 轻量摘要响应建议

`/api/mobile/summary` 当前已经有 period、trend、sources、breakdown、limits。本轮 iOS App 高保真改版必须先使用现有 `MobileSummary` 合同；下面的 `display` 区块只是后续独立 API/snapshot 任务的可选增强，不能作为 Web、macOS、iOS Widget 或 Watch UI 交付的前置条件。

```json
{
  "schema_version": 1,
  "client": "ios",
  "generated_at": "2026-06-19T10:20:00+08:00",
  "timezone": "Asia/Shanghai",
  "period": {
    "id": "today",
    "total_tokens": 1670000000,
    "input_tokens": 8100000,
    "output_tokens": 78300000,
    "cache_tokens": 1580000000,
    "cache_ratio": 0.946
  },
  "display": {
    "total_text": "1.67B",
    "breakdown_text": "Input 8.1M · Output 78.3M · Cache 1.58B",
    "updated_text": "2 分钟前",
    "delta": {
      "direction": "up",
      "percent": 5.0,
      "text": "↑5%"
    }
  }
}
```

`display` 是展示辅助字段，不是 canonical facts。旧客户端可以忽略；本轮客户端也可以在本地 view model 中从现有字段派生这些文案。

## 趋势接口

现有 `trend.points` 可继续使用。本轮客户端可以本地计算柱状图高度、上限标签和轴标签；下面字段是后续 API 增强建议：

```json
{
  "trend": {
    "period": "today",
    "granularity": "hour",
    "chart_ceiling": 2000000000,
    "chart_ceiling_label": "2B",
    "axis_labels": ["00:00", "06:00", "12:00", "18:00", "23:59"],
    "points": [
      {
        "bucket": "2026-06-19T10:00:00+08:00",
        "label": "10:00",
        "tokens": 123000000,
        "input_tokens": 1000000,
        "output_tokens": 8000000,
        "cache_tokens": 114000000
      }
    ]
  }
}
```

如果服务端未来返回 `chart_ceiling`，客户端可以用 `tokens / chart_ceiling` 画柱子高度；没有该字段时，客户端按当前 points 最大值向上取整，不改变真实 tokens。

## 额度接口

现有 `limits.windows` 可继续使用。本轮客户端可以按 provider 本地分组生成双环；下面的 `limits.accounts` 是后续 API 增强建议：

```json
{
  "limits": {
    "observed_count": 2,
    "total_count": 2,
    "accounts": [
      {
        "provider": "anthropic",
        "label": "Claude",
        "status": "ok",
        "windows": [
          {
            "window": "5h",
            "used_percent": 68,
            "remaining_percent": 32,
            "reset_at": "2026-06-19T12:51:00+08:00",
            "confidence": "observed",
            "official": true
          },
          {
            "window": "7d",
            "used_percent": 45,
            "remaining_percent": 55,
            "reset_at": "2026-06-20T21:00:00+08:00",
            "confidence": "observed",
            "official": true
          }
        ]
      }
    ]
  }
}
```

展示规则：

- `official=true` 且 `confidence=observed` 才能进入主双环。
- 只有 estimated 或 unknown 时，UI 要降级，不显示成官方额度。
- 没有 7d 时，可以只显示 5h，不补假内环。

## 来源接口

来源列表需要同时表达贡献和健康：

```json
{
  "sources": [
    {
      "source_id": "mac-local",
      "display_name": "wangzhipeng@MacBook Pro",
      "machine": "MacBook Pro",
      "os_user": "wangzhipeng",
      "platform": "macOS",
      "status": "ok",
      "tokens": 1170000000,
      "last_observed_at": "2026-06-19T10:18:00+08:00",
      "updated_text": "2 分钟前",
      "error_message": null
    }
  ]
}
```

如果某来源失败：

```json
{
  "source_id": "linux-dev",
  "display_name": "wang@linux-dev",
  "status": "failed",
  "tokens": 0,
  "error_message": "command_failed"
}
```

UI 不能把 failed source 隐藏成 0 用量。

## 平台取数方式

### Web Dashboard

```http
GET /api/summary?period=today
Authorization: Bearer <token>
```

Web 使用完整 summary，可以展示更多 breakdown。

### macOS 菜单栏

```http
GET /api/mobile/summary?period=today
Authorization: Bearer <token>
```

基于 TP-V2-064 已有菜单栏入口改版。弹窗打开时刷新；刷新按钮再次请求当前 period。主屏不得附带 `machine` 或 `account` 过滤，避免显示局部总量。

### iOS Widget

Widget 不应直接持有复杂业务逻辑：

- 优先由 iPhone App 拉取 `/api/mobile/summary` 后写入 Widget 可读缓存。
- 如果直接请求 API，必须走安全存储的 token，不写入仓库。
- Small / Medium / Large 共用同一份摘要，只裁剪展示。
- Widget 主屏不得自行切 period 边界；如果展示固定 period，必须使用 App 或服务端生成的同一 period 摘要。

### Apple Watch

Watch 本轮纳入实现，第一版读取 iPhone App 同步的轻量摘要，或读取与 `/api/mobile/summary` 等价的缓存摘要：

- 不新增 Watch 专用采集。
- 不新增 Watch 专用业务口径。
- 网络不可用时展示最近缓存和更新时间。
- 缓存过期时必须显示 stale 状态，不把旧数据当实时数据。
- 真机安装前需要已配对、已信任、已解锁，并开启 Apple Watch Developer Mode。

## 错误响应

保持现有结构化错误：

```json
{
  "status": "error",
  "error_type": "auth_required",
  "message": "Authentication required"
}
```

客户端展示规则：

- `auth_required`：提示连接配置不可用。
- `read_failed`：提示服务端摘要读取失败。
- `internal_error`：提示服务端暂不可用。
- 网络错误：显示最近缓存，并标记 stale。

## 兼容原则

- 新增字段必须向后兼容。
- 不删除当前客户端依赖字段。
- 新视觉所需字段优先由客户端 view model 从现有合同派生；只有跨端重复计算或数据准确性需要服务端统一时，才在独立任务包中新增 `display`、`trend`、`limits.accounts`、`sources.tokens` 等字段。
- 不新增生产 token、secret 或本地路径字段。
- 不把 HTML 设计稿里的样例数字作为 API fixture 的真实默认值。
