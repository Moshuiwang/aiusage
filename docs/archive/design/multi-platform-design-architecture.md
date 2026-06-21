# Architecture: Multi-Platform AI Usage Experience

## 目标

让最新多端设计共用一条事实链路：

```text
Device Pushers
  -> HTTP Ingest
  -> SQLite Canonical Store
  -> Snapshot Builder
  -> Summary APIs
  -> Web / macOS / iOS Widget / Watch
```

展示层只负责看，不负责采集、推断或纠正数据。

## 当前可复用基础

项目已有这些基础能力：

- `/ingest` 接收 usage 上报。
- `/ingest-limits` 接收可信 limits 窗口。
- SQLite 保存 daily usage、hourly facts、limits、source health。
- `/api/summary` 服务 Web Dashboard。
- `/api/mobile/summary` 服务 iPhone App / iOS Widget / 轻量客户端。
- `source_status` 区分 ok、stale、failed、never_seen 等状态。

最新设计主要是展示体验升级，不需要重建采集链路。

## 展示端分层

| 客户端 | 数据入口 | 体验定位 |
| --- | --- | --- |
| Web Dashboard | `/api/summary` | 完整查看入口，保留最多信息。 |
| macOS 菜单栏 | `/api/mobile/summary` 优先 | 基于 TP-V2-064 已有入口改版；快速查看总量、额度、来源，打开 Dashboard。 |
| iOS Widget | `/api/mobile/summary` 或本地缓存摘要 | 桌面 glance，不做 drilldown。 |
| Apple Watch | iPhone 同步缓存或 `/api/mobile/summary` 派生摘要 | 本轮纳入 watchOS 只读摘要；抬腕查看，不做复杂图表。 |
| iPhone App | `/api/mobile/summary` | 移动端完整体验，仍是后续 App 主线。 |

规则：

- 客户端不直接读取 SQLite。
- 客户端不执行 `ccusage`。
- 客户端不 SSH 到其他机器。
- 客户端不访问原始 usage 日志目录。
- 本轮 UI 改版优先使用现有 `MobileSummary` / `/api/summary` 字段。字段不够时，先在客户端派生；确实需要新增 server 字段时，必须单独开 API/snapshot 任务包，不能阻塞 iOS App 高保真改版。

## 周期和时区口径

数据准确性的单一规则：

- `today`、`week`、`month`、`all` 的边界由服务端按 summary 返回的 `timezone` 统一计算。
- 客户端只传 `period` 和可选 `date`，不自行按本机时区切日、切周或切月。
- trend bucket、delta 对比周期、source contribution、limits observed time 都必须使用同一服务端时区口径。
- UI 可以显示相对时间，例如“2 分钟前”，但相对时间只来自 `generated_at` / `last_observed_at`，不改变统计边界。

## 统一展示模型

后续可以把现有 summary 输出整理成一个跨端展示模型，不一定新增 endpoint。本轮实现不要求先完成这个模型；Web 使用 `/api/summary`，iOS App、iOS Widget、macOS 菜单栏和 Watch 先复用现有 `MobileSummary` 能力。

```text
UsageDisplaySummary
  period
  totals
  delta
  trend
  quota_accounts
  sources
  freshness
```

### `period`

用于周期切换：

- `today`
- `week`
- `month`
- `all`

每次切换都必须重新读取对应 period 的 API 数据。

### `totals`

用于所有端的主数字：

- `total_tokens`
- `input_tokens`
- `output_tokens`
- `cache_tokens`
- `cache_ratio`

### `delta`

用于绿色 / 红色涨跌：

- `direction`: `up` / `down` / `flat` / `unknown`
- `percent`
- `comparison_label`

如果没有可比周期，UI 显示中性状态，不硬造涨跌。

### `trend`

用于柱状图：

- `points`
- `granularity`
- `chart_ceiling`
- `chart_ceiling_label`
- `axis_labels`

`chart_ceiling` 是展示上限，不代表 quota。

### `quota_accounts`

用于 Claude / OpenAI 双环：

- `provider`
- `label`
- `windows`
- `observed_count`
- `status`

每个账号最多展示两个主要窗口：

- 5h。
- 7d 或 weekly。

只有 `official=true` 且 `confidence=observed` 的窗口才能作为主环展示。

### `sources`

用于来源列表：

- `source_id`
- `display_name`
- `machine`
- `os_user`
- `platform`
- `status`
- `tokens`
- `last_observed_at`
- `relative_updated_text`

来源排序默认按当前周期 token 贡献降序；没有 token 的异常来源仍要保留状态提示。

## 组件映射

| 设计组件 | Web | macOS | iOS Widget | Watch |
| --- | --- | --- | --- | --- |
| 双环 App Icon | SVG / CSS | SwiftUI Shape 或 Image asset | App asset | Watch asset |
| 周期选择 | Segmented control | Segmented control | 不交互或跟随配置 | 不交互 |
| 主数字 | Hero block | Hero card | Widget headline | Watch headline |
| 趋势图 | 24 bar chart | 12 bar chart | Medium/Large mini chart | 不展示或极简 |
| 额度双环 | Quota card | Quota section | Large Widget | Watch rings |
| 来源列表 | Source cards | Source rows | Large Widget rows | 2-row summary |

## 刷新行为

- Dashboard 打开时拉取一次。
- macOS 菜单栏每次打开时拉取一次，可 60 秒轮询。
- iOS Widget 使用系统刷新机制，不承诺实时轮询。
- Watch 优先读取最近摘要，不为 Watch 单独跑采集。
- 刷新失败时保留最近成功数据，并显示 stale / failed 状态。

## 降级策略

| 缺失内容 | 用户看到什么 |
| --- | --- |
| 没有 usage | 显示 0 或空态，并说明数据是否新鲜。 |
| source failed | 显示失败来源，不把失败当 0 用量。 |
| limits 缺失 | 不显示双环主卡，或显示“额度暂不可用”。 |
| delta 缺失 | 不显示涨跌，或显示中性短横线。 |
| trend 缺失 | 显示总量和来源，不画假柱子。 |

## 安全边界

所有多端客户端禁止：

- 保存生产 token 到仓库。
- 打印 token。
- 展示 prompt、response、tool output。
- 上传或展示原始 JSONL 路径。
- 从本地 token history 推断官方 reset。

## 实现阶段建议

### Phase 1: 文档冻结和任务包拆分

- 修正产品、架构、数据库和接口文档。
- 创建 Web、macOS、iOS App、iOS Widget、Watch、共享图标/设计资产、数据验收任务包。
- 明确 iOS App 高保真改版不改变 mobile summary API contract。

### Phase 2: 共享视觉资产和现有合同适配

- 生成 App Icon。
- 固定双环、趋势柱、状态色的跨端 token。
- 优先在客户端 view model 派生 display text、chart ceiling、axis labels 和 relative time。

### Phase 3: 用户可见入口

- Web Dashboard 高保真对齐。
- macOS 菜单栏基于 TP-V2-064 高保真对齐。
- iOS App 高保真和图标对齐。
- iOS Widget 三尺寸对齐。

### Phase 4: Watch 本轮交付

- 新增 watchOS target 或 Swift Package 模块。
- Watch 只读 iPhone 同步缓存或移动端摘要，不新增业务口径。
- 验收模拟器截图；若真机在线、已信任且 Developer Mode 可用，再执行真机安装。
