# Database Design: Multi-Platform AI Usage Experience

## 目标

最新多端设计不要求重建数据库。它需要的是把现有 canonical store 中的 usage、limits、source health 聚合成更适合多端展示的摘要。

数据库层的原则：

- SQLite 继续是个人 canonical store。
- 展示端不直接读库。
- 视觉字段优先在 snapshot / API 层派生。
- 只有真实事实需要长期保存，纯展示样式不进数据库。

## 现有表复用

| 表 | 用途 | 对新设计的价值 |
| --- | --- | --- |
| `usage_daily` | 每天 usage baseline | 主数字和历史兼容。 |
| `usage_daily_models` | daily model 拆分 | 后续 model drilldown。 |
| `usage_hourly` | 小时聚合 | 今日趋势柱状图。 |
| `usage_blocks` | Claude blocks 口径 | Claude 趋势和小时补充。 |
| `usage_hourly_facts` | 账号 / 机器 / 用户维度小时事实 | 后续更可信的多维趋势和来源贡献。 |
| `usage_hourly_models` | 小时事实的模型拆分 | 后续 model 维度。 |
| `limit_windows` | 可信 limits 窗口 | Claude / OpenAI 双环额度。 |
| `source_identities` | source 到机器 / 用户 / 平台 | 来源列表展示名。 |
| `source_reports` | 采集运行结果 | source health 和失败提示。 |
| `collection_runs` | 采集批次 | 最近更新时间和运行状态。 |
| `machines` / `os_identities` / `ai_accounts` | 账号小时事实维度 | 后续账号、机器、用户强 drilldown。 |

## 新设计字段映射

### 总用量

| UI 字段 | 数据来源 | 是否需要新表 |
| --- | --- | --- |
| `total_tokens` | snapshot summary | 否 |
| `input_tokens` | snapshot summary | 否 |
| `output_tokens` | snapshot summary | 否 |
| `cache_tokens` | snapshot summary 派生 | 否 |
| `delta_percent` | API 对比相邻周期派生 | 否 |

### 趋势图

| UI 字段 | 数据来源 | 是否需要新表 |
| --- | --- | --- |
| bars | `usage_hourly` / `usage_hourly_facts` 聚合 | 否 |
| axis labels | API 根据 period 派生 | 否 |
| chart ceiling | API 根据最大值向上取整派生 | 否 |
| ref line label | API 派生，例如 `2B` | 否 |

### 额度双环

| UI 字段 | 数据来源 | 是否需要新表 |
| --- | --- | --- |
| provider | `limit_windows.provider` | 否 |
| 5h percent | `limit_windows` | 否 |
| 7d / weekly percent | `limit_windows` | 否 |
| reset time | `limit_windows.reset_at` | 否 |
| confidence | `limit_windows.confidence` | 否 |

### 来源列表

| UI 字段 | 数据来源 | 是否需要新表 |
| --- | --- | --- |
| source name | `source_identities` + source config | 否 |
| platform | `source_identities.platform` | 否 |
| last seen | `source_reports` / snapshot source status | 否 |
| status | snapshot source status | 否 |
| tokens | 当前 period 聚合贡献 | 否，优先 snapshot 派生 |

## 不进数据库的内容

这些内容属于展示或客户端资源，不应进 SQLite：

- 颜色 token。
- 卡片圆角、阴影、字体。
- App Icon SVG path。
- Widget 尺寸布局。
- 相对时间文案，例如“2 分钟前”。
- dark / light 当前切换状态。
- 图表柱子高度百分比。

## 可能需要的 API 派生字段

为了减少各端重复计算，后续可以在 summary 层增加这些派生字段，而不是新增表。本轮 UI 改版不以这些字段为前置条件；客户端 view model 可以先从现有 summary 字段派生：

```json
{
  "display": {
    "total_text": "1.67B",
    "delta": {
      "direction": "up",
      "percent": 5.0,
      "text": "↑5%"
    },
    "trend": {
      "chart_ceiling": 2000000000,
      "chart_ceiling_label": "2B",
      "axis_labels": ["00:00", "06:00", "12:00", "18:00", "23:59"]
    }
  }
}
```

这类字段可以由 snapshot builder 或 mobile summary builder 生成，不改变 canonical facts。

## 后续可选表

第一版不需要新增表。只有出现下面需求时，再考虑新增。

### `client_snapshot_cache`

当 Watch / Widget 需要服务端记录每个客户端最后拉取或推送的摘要时再建。

```sql
CREATE TABLE client_snapshot_cache (
  client_id TEXT PRIMARY KEY,
  client_type TEXT NOT NULL,
  period TEXT NOT NULL,
  snapshot_json TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  expires_at TEXT
);
```

默认不建议第一版使用，因为 Widget / Watch 更适合用本地系统缓存。

### `display_preferences`

当用户需要自定义默认 period、隐藏某个 source、切换主题时再建。

```sql
CREATE TABLE display_preferences (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

默认不建议第一版使用，因为当前是个人产品，先用客户端本地偏好即可。

## 数据验收标准

- 新视觉上线不改变 `usage_daily` baseline。
- limits 缺失时，不生成假的双环数据。
- source failed 时，source status 仍可被 API 返回。
- 图表展示上限由数据派生，不写死进数据库。
- 数据库不保存生产 token、cookie、prompt、response、原始日志路径。
