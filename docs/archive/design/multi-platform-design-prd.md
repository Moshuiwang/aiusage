# PRD: Multi-Platform AI Usage Experience

## 背景

最新设计包 `AI Usage Widget.zip` 把 AI Usage 从单一 Dashboard / Widget 方向，推进到一套统一的多端体验：

- Web Dashboard。
- macOS 菜单栏弹窗。
- iOS Widget Small / Medium / Large。
- Apple Watch 单屏查看。
- 统一 App Icon 和双环品牌图形。

这批 HTML 文件是高保真设计参考，不是生产代码。后续实现要用各平台原生能力复刻体验：Web 继续走当前 Dashboard 技术栈，Apple 平台走 SwiftUI / WidgetKit / watchOS。

## 产品定位

AI Usage 是个人 AI coding 用量观测产品。它要让用户在不同设备上快速回答：

- 今天、本周、本月、全部周期用了多少 token。
- 用量比上个周期是上升还是下降。
- 主要用量来自哪台机器。
- Claude / OpenAI 的可信额度窗口还剩多少。
- 数据是不是新鲜，最近一次上报是什么时候。

产品不是团队 SaaS，不做公共云同步，不做 billing-grade 财务对账，也不把估算额度伪装成官方状态。

## 目标用户体验

用户打开任意入口，都应看到同一套事实：

- 一个醒目的总用量数字。
- Input / Output / Cache 的简单拆分。
- 今天 / 本周 / 本月 / 全部 的周期切换。
- 柱状趋势图，帮助判断用量节奏。
- Claude 和 OpenAI 的双环额度卡。
- 来源列表，显示机器、平台、更新时间和用量贡献。

入口之间的差异只在信息密度：

| 入口 | 用户体验目标 |
| --- | --- |
| Web Dashboard | 完整查看入口，适合看趋势、来源、额度和后续 drilldown。 |
| macOS 菜单栏 | 工作中快速瞄一眼今日用量、额度、来源，必要时打开 Dashboard。 |
| iOS Widget Small | 只看总用量和涨跌。 |
| iOS Widget Medium | 看总用量、涨跌、简单拆分和迷你趋势。 |
| iOS Widget Large | 看总用量、趋势、额度双环和两个主要来源。 |
| Apple Watch | 抬腕看总用量、额度百分比和主要来源，不做复杂交互。 |

## 核心设计语言

### 品牌图形

App Icon 和所有核心卡片使用同一个双环符号：

- Claude 使用橙色外环。
- OpenAI 使用蓝色内环。
- 深色径向背景。
- 中心白色小点。

这个符号是产品的统一识别，不应在各平台重新设计成不同图形。

### 信息层级

每个入口都遵守同一优先级：

1. 总用量。
2. 周期切换和涨跌。
3. Token 类型拆分。
4. 趋势图。
5. 可信额度窗口。
6. 来源健康和主要来源。

Apple Watch 和 Small Widget 可以省略部分信息，但不能改变字段含义。

### 视觉状态

- 正向变化使用绿色。
- 负向变化使用红色。
- Claude 额度使用橙色 / 桃色。
- OpenAI 额度使用蓝色 / 青色。
- 所有端支持深浅色或系统外观。
- 玻璃感和系统字体是主要质感，不额外引入装饰性视觉。

## 功能范围

### 本轮文档纳入

- 固定多端体验目标。
- 固定展示端只读边界。
- 固定数据来源和接口复用方向。
- 明确哪些字段已有，哪些字段需要扩展。
- 为后续 Web / macOS / iOS Widget / Watch 实现拆任务包提供依据。

### 本轮实现纳入

- Web Dashboard 对齐最新高保真视觉。
- macOS 菜单栏基于已完成的 TP-V2-064 现有轻入口做视觉、图标和数据展示对齐；不新建第二条 macOS 客户端路线。
- iOS App 基于现有 `MobileSummary` live 数据管线做图标和高保真 UI 对齐；不把 API 合同变更作为前置条件。
- iOS Widget 补齐 Small / Medium / Large 视觉和数据绑定。
- App Icon 按最新双环图形生成各平台资源。
- Apple Watch 本轮纳入：新增 watchOS 代码、摘要界面、缓存/过期状态和模拟器或真机验收；不新增采集能力。

### 不纳入

- 不改采集器。
- 不改生产 token 或本机私密配置。
- 不读取远程 `.claude` / `.codex` 原始日志。
- 不让客户端执行 `ccusage`、SSH 或 provider 采集。
- 不把历史 token 估算展示成官方 quota。
- 不把 HTML 设计稿直接复制为生产代码。

## 平台优先级建议

1. App Icon：统一产品识别，改动独立，风险低。
2. Web Dashboard：当前完整查看入口，用户感知最高。
3. macOS 菜单栏：基于 TP-V2-064 已有入口改版，符合当前桌面轻入口路线。
4. iOS Widget：已有 Widget 基础，适合补齐 glance 体验。
5. Apple Watch：本轮新增 watchOS 展示端，优先做只读摘要和数据新鲜度，不做复杂交互。

## 成功标准

- 用户在 Web、macOS、iOS App、iOS Widget、Apple Watch 上看到的总用量和周期一致。
- 周期切换不会只换标签，必须换对应数据。
- 额度双环只展示可信 limits；缺失时有明确降级文案。
- 来源列表能看出主要机器和数据新鲜度。
- Small / Watch 这类小屏入口不展示过密信息。
- 各端视觉统一，但不牺牲平台原生体验。
- Watch 无网络或缓存过期时明确显示最近更新时间和 stale 状态，不把旧数据当实时数据。

## 风险

| 风险 | 产品影响 | 处理方式 |
| --- | --- | --- |
| 设计稿样例数字被当成真实数据 | 用户误解当前用量 | 实现只绑定 API 数据，fixture 仅用于视觉测试。 |
| 额度字段不完整 | 双环显示不可信 | 只展示 observed / official limits，缺失则降级。 |
| 多端各自计算 | 不同入口数字不一致 | 所有客户端只读同一套 API / snapshot。 |
| Watch 范围过早扩大 | 分散当前主线 | Watch 本轮只做只读摘要、缓存和验收，不做采集、通知或复杂 drilldown。 |

## 后续任务拆分建议

- 多端设计资源归档与 App Icon 资源生成。
- Web Dashboard 高保真视觉对齐。
- macOS 菜单栏弹窗基于 TP-V2-064 高保真视觉对齐。
- iOS Widget Small / Medium / Large 高保真对齐。
- Apple Watch watchOS shell、摘要缓存、stale 状态和截图验收。
- API / snapshot 字段补齐只作为独立后续增强：delta、chart ceiling、relative updated text、quota ring grouping；不能阻塞现有 `MobileSummary` 能支撑的 UI 改版。
