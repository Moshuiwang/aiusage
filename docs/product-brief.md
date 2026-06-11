# Product Brief

## 产品定位

AI Usage Widget 不是单纯的 Widget 原型，而是一个个人使用的 AI coding usage 观测工具。项目名称暂时保留历史命名，但后续产品形态不再以 macOS Widget 为核心。

它要把多台设备、多个 OS 用户、多个 AI coding agent 的用量事实、采集健康状态和可验证的额度窗口状态，汇总成一个可信的个人数据产品。Web dashboard 是当前完整查看入口；客户端按 `clients/` 分层推进：iPhone App + iOS Widget 是已落地方向，Android 复用移动端摘要合同，macOS 走菜单栏或轻量桌面入口，Windows 走托盘或轻量桌面入口。macOS Widget 退出后续产品路线，只保留历史兼容和参考价值。

## 核心问题

用户同时在这些上下文使用 AI coding 工具：

- Mac 本机账户。
- 两台或三台 Linux 服务器上的个人账户。
- Windows 台式机账户。
- 后续可能还有其他机器、手动导入报表或额外 agent。

没有统一观测入口时，会出现这些问题：

- 不知道今天总共用了多少 token。
- 不知道主要用量来自哪台机器、哪个 OS 用户、哪个 agent。
- 采集失败容易被误判成“没有用量”。
- quota/reset 信息如果没有可靠来源，容易被历史 token 估算误导。
- 展示 UI 一旦直接追设计稿，会把 mock 数据和真实能力混在一起。

## 产品原则

1. **可信优先**：只展示有来源、有时间、有可信度的数据；不能把估算包装成官方状态。
2. **个人 HTTP 汇聚**：部署一个个人 HTTP server 作为汇聚中心，只服务本人设备，不做团队 SaaS。
3. **主动上报**：各终端主动 push 结构化 usage payload；汇聚端不通过 SSH 登录远端机器抓取。
4. **账户隔离**：每个 OS 用户只在自己的账户上下文执行 `ccusage` 或读取明确设计过的结构化导出文件。
5. **数据产品先于 UI**：先稳定采集、ingest、存储、快照契约和错误模型，再做展示升级。
6. **展示只读**：Web dashboard、iPhone App、iOS Widget、Android、macOS 菜单栏、Windows 托盘和预览层只读 canonical store、Web API 或派生快照，不执行终端采集，不执行 SSH。
7. **一套事实，多端外壳**：所有客户端共享 server read model 和移动端摘要合同，不在平台侧重新计算 usage / limits / source health。
8. **TDD 驱动落地**：每个开发任务先写失败测试或契约测试，再实现最小代码。
9. **移动端优先设计**：后续原生客户端先围绕 iPhone App 的信息架构和交互设计推进，iOS / Android Widget 只承载 glanceable 摘要。

## 用户范围

当前只服务单个个人用户的多设备工程工作流。

不做团队 SaaS，不做多租户权限系统，不做公共云同步，不做 billing-grade 财务系统。

## 产品能力域

### D1 Usage Facts

目标：

- 采集 `ccusage daily --json --timezone <tz>` 的 daily usage。
- 统一标准化 token 分项、total tokens、agent、source、日期。
- 支持 Mac、Linux server、Windows desktop 终端侧本机采集后 HTTP push。
- 支持手动文件导入作为调试和兜底路径。

可信度：

- 来自 `ccusage daily --json` 的字段视为 observed usage facts。
- 如果 `ccusage` 无法区分 agent，记录为 `unknown`，不猜测。

### D2 Source Health

目标：

- 每个 source 都有结构化状态。
- 单个 source 失败时，其他 source 的数据仍能进入快照。
- UI 必须能区分“今日 0 用量”和“采集失败”。

状态示例：

- `ok`
- `disabled`
- `missing_file`
- `command_failed`
- `timeout`
- `invalid_json`
- `unsupported_shape`
- `stale`

### D3 Canonical Store

目标：

- SQLite 是个人 HTTP server 的 canonical store。
- `latest.json` 是面向展示层的派生快照，不是唯一事实来源。
- 后续趋势、摘要、source 成功率都从 canonical store 或快照构建器派生。

### D4 HTTP Ingest

目标：

- HTTP server 接收终端侧主动上报的结构化 daily usage payload。
- ingest payload 必须包含 source id、host、OS 用户、timezone、observed_at、采集窗口和 `ccusage daily` 标准化数据。
- server 校验 schema、认证信息、幂等 key 和时间戳，不接收原始日志目录。
- 同一个 source/date/agent 的重复 push 使用稳定 key upsert。

### D5 Display Snapshot

目标：

- 展示层只读稳定快照。
- 快照包含 schema version、生成时间、时区、summary、items、source status 和可选扩展。
- 快照缺失、损坏、过期或局部失败都必须有明确降级状态。

### D6 Limits / Quota Windows

目标：

- quota/reset 是可插拔能力，不是 baseline 的前置依赖。
- 只有可验证来源才能显示为 observed quota。
- 估算来源必须标记为 estimated，并在 UI 上弱化。
- Claude Code 和 Codex 的 MVP 目标是稳定获取官方 reset time 和 window usage。

禁止：

- 不从 `ccusage daily` 推断官方 quota。
- 不把 `ccusage blocks` 的本地窗口说成官方订阅额度。
- 不读取或同步 `.claude`、`.codex` 原始日志目录来倒推状态。

优先级：

- Claude Code：OAuth Usage API -> Claude CLI `/usage` -> Claude Web API。
- Codex：`~/.codex/auth.json` OAuth/WHAM usage -> `codex app-server` RPC `account/rateLimits/read`。
- Antigravity：后续通过本地 Language Server spike，不进入 Claude + Codex MVP。

## 展示面

### CLI

CLI 是工程化验证入口和终端侧 pusher 的基础，必须能执行：

- 本机采集。
- push 到 HTTP server。
- 构建快照。
- 检查配置。
- 输出 source health。
- 在测试环境使用 fixture 和临时路径运行。

### Web Dashboard

Web dashboard 是主要用户界面，目标是从浏览器查看所有终端：

- 今日 total tokens。
- source health。
- 按 account / agent / machine 的关键拆分。
- token 类型结构。
- 最近上报时间和 stale source。
- 失败 source 的非敏感错误摘要。
- 有可信 limits 时显示 5h / week 进度和 reset time。
- 没有可信 limits 时降级为 daily usage。

### iPhone App

iPhone App 是下一阶段目标客户端，负责承载完整个人查看体验：

- 今日、本周期和关键窗口的 usage / limits 摘要。
- 按机器、OS 用户、agent、模型和日期的 drilldown。
- source health、stale source、最近上报时间和非敏感错误摘要。
- 可靠 limits 来源存在时展示 5h / week 进度和 reset time。
- 没有可信 limits 时降级为 daily usage 和采集健康状态。

### iOS Widget

iOS Widget 是 iPhone App 的轻量 glanceable 展示面，只读 App 或 server 准备好的摘要数据：

- 今日 total tokens 或当前窗口使用进度。
- 关键 limits reset time。
- source health / stale 摘要。
- 最近更新时间。

Widget 不承载完整 dashboard，不做复杂 drilldown，不直接调用采集命令或官方 provider。

### Android App / Widget

Android 复用 iPhone 的移动信息架构：

- App 展示今日、本周期、source health、机器/账号/agent drilldown 和可信 limits 状态。
- Widget 只展示今日用量、可信额度窗口、采集健康和最近更新时间。
- Android 不重新计算 usage / limits；字段不够时先扩展 `/api/mobile/summary`。

### macOS Menu Bar / Desktop

macOS 后续只做轻量工作台入口：

- 菜单栏显示今日用量、可信额度状态、采集健康和最近更新时间。
- 点击进入 Web dashboard 或轻量详情页。
- 不承载完整 dashboard，不执行采集，不直接读取 SQLite。

### Windows Tray / Desktop

Windows 后续只做轻量工作台入口：

- 托盘显示健康状态和关键摘要。
- 完整查看打开 Web dashboard。
- Windows pusher / Task Scheduler 负责采集；展示端只读 API。

### macOS Widget

macOS Widget 不再作为后续产品交付目标。

既有 macOS Widget / SwiftUI / WidgetKit 代码和文档只保留为历史兼容、snapshot decode 参考或临时调试入口。后续不要围绕 macOS Widget 新增视觉、签名、发布或交互任务。

### 后续展示

历史报表导出、ChatGPT Apps 内嵌查看都是后续扩展，不作为当前工程化基础或跨端客户端设计的前置条件。

## 阶段边界

### Phase 0: 文档和工程方向重设

目标：

- 产品文档、架构文档、任务包一致。
- 明确哪些现有实现保留，哪些设计可推翻。
- 在进入开发前固定 TDD 规则。

### Phase 1: HTTP Ingest Contract

目标：

- 固化终端 push payload schema、认证模型、幂等 key 和错误响应。
- server ingest 使用 fixture 和 contract test 验证。
- 不引入 quota/reset。

### Phase 2: Device Pusher and Baseline Normalization

目标：

- 每台设备在本机账户上下文运行 `ccusage daily --json --timezone <tz>`。
- 终端侧把输出转换成 ingest payload 并 push 到 server。
- 配置、runner、normalizer 都有契约测试。

### Phase 3: Canonical Store and Snapshot API

目标：

- HTTP ingest 写入 SQLite canonical store。
- 明确 `latest.json` v1 schema。
- 把 summary、source health、token type totals 等展示所需聚合放进快照。

### Phase 4: Web Dashboard v1

目标：

- Web dashboard 先实现真实数据支撑的信息架构。
- 缺失数据和失败 source 有可靠 UI。
- 页面只展示 canonical store 或快照中已有字段，不现场执行采集。

### Phase 5: Mobile App Design and Limits Source

目标：

- 启动 iPhone App 信息架构、手机尺寸可交互原型和 iOS Widget 信息密度设计。
- 在 baseline 稳定后引入 limits/quota source。
- 先支持 Claude Code + Codex 的 official limits provider contract 和 fixtures。
- 每个字段都有 `source_type`、`confidence`、`observed_at`、`status`。
- Web dashboard / iPhone App / iOS Widget 只读 `limits` 快照或只读 API，不直接调用官方 API。

### Phase 6: iOS Implementation and Operations

目标：

- 将认可后的手机原型收敛成 SwiftUI App、WidgetKit、API contract、缓存和状态测试任务包。
- 补各平台定时 pusher、server 启动、认证、备份、App Group、签名、构建和运行文档。

### Phase 7: Cross-Platform Clients

目标：

- 在 `clients/` 下推进 Android、macOS、Windows 和 Web 目标目录。
- macOS / Windows 先做轻量入口，不复制完整 dashboard。
- Android 先复用 `/api/mobile/summary`，不新建独立口径。
- 共享展示合同进入 `packages/client-contracts/`，共享状态色和视觉语义进入 `packages/design-tokens/`。

## 关键技术决策

### 保留

- 保留 Python collector 作为数据管道实现语言。
- 保留 SQLite 作为个人 server canonical store。
- 保留 `latest.json` 作为展示层读取入口。
- 保留 `ccusage daily --json` 作为 daily usage baseline。
- 保留 Web dashboard 作为当前主展示面。
- 保留既有 macOS SwiftUI / WidgetKit 代码作为历史兼容和参考，不再作为后续产品路线。

### 调整

- 从 SSH pull 改为 device push：汇聚端提供 HTTP ingest，各终端主动上报。
- Web dashboard 成为当前完整展示面；后续客户端路线从 macOS Widget 调整为 `clients/` 分层：iOS 已落地，Android 复用移动摘要，macOS/Windows 做轻量入口。
- quota/reset 不再作为当前主线前置项；它是 limits 插件域。
- `latest.json` 不应只是一组扁平 `items`；需要演进为 versioned display snapshot。
- 趋势图优先由 server 从 canonical store 聚合；移动端只消费 Web API 或预聚合快照，不重复实现事实聚合。
- 配置需要 schema 和校验，不能靠隐式字典字段扩散。

### 暂不做

- 不做 SSH pull 采集。
- 不做远程 agent 安装器；终端侧 pusher 先用可手动安装和配置的 CLI。
- 不做官方 quota 抓取的逆向方案。
- 不做从本地历史 token 推官方 reset time 的方案。
- 不做多租户、云同步、团队看板。

## 非功能需求

- 所有采集命令必须有超时。
- 所有文件写入必须原子化。
- HTTP ingest 必须有认证、payload size 限制和结构化错误响应。
- 所有真实路径、host、密钥、token 放在本地配置或忽略目录。
- 测试不能依赖生产账户、真实 SSH、真实 `ccusage` 输出。
- 日志和错误信息需要截断，避免泄露完整原始 usage 内容。
- 文档、fixtures、schema、测试必须同步更新。

## 成功标准

项目进入工程化状态的最低标准：

- 从空测试数据到完整快照的路径可以用 fixture 重放。
- 任一 source 失败不会破坏其他 source 的展示。
- 任一终端离线或 stale 时，Web dashboard 能明确显示最近上报状态。
- HTTP ingest payload schema 有 fixture、认证失败测试和幂等 upsert 测试。
- `latest.json` schema 有版本、fixture 和 Swift/Python 双侧解码测试。
- Web dashboard 和当前/历史展示消费者的每个展示块都能追溯到 canonical store 或快照字段。
- iPhone App / iOS Widget / Android / macOS / Windows 的每个展示块都能追溯到 canonical store、Web API 或快照字段。
- limits/quota 缺失时仍有可用产品体验。
- 每个实现任务都有先红后绿的测试记录。
