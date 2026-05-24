# Product Brief

## 产品定位

AI Usage Widget 不是单纯的 Widget 原型，而是一个本机优先的 AI coding usage 观测工具。

它要把多个机器、多个 OS 用户、多个 AI coding agent 的用量事实、采集健康状态和可验证的额度窗口状态，汇总成一个可信的本机数据产品。Widget 只是第一展示面，不是系统边界。

## 核心问题

用户同时在这些上下文使用 AI coding 工具：

- Mac 本机账户。
- 远程 Linux `wang` 账户。
- 远程 Linux `ubuntu` 账户。
- 后续可能还有其他机器、手动导入报表或额外 agent。

没有统一观测入口时，会出现这些问题：

- 不知道今天总共用了多少 token。
- 不知道主要用量来自哪台机器、哪个 OS 用户、哪个 agent。
- 采集失败容易被误判成“没有用量”。
- quota/reset 信息如果没有可靠来源，容易被历史 token 估算误导。
- Widget UI 一旦直接追设计稿，会把 mock 数据和真实能力混在一起。

## 产品原则

1. **可信优先**：只展示有来源、有时间、有可信度的数据；不能把估算包装成官方状态。
2. **本机优先**：Mac 是汇聚和展示中心，默认不引入远端服务端或数据库服务。
3. **账户隔离**：每个 OS 用户只在自己的账户上下文执行 `ccusage` 或读取明确设计过的结构化导出文件。
4. **数据产品先于 UI**：先稳定采集、存储、快照契约和错误模型，再做 Widget 视觉升级。
5. **展示只读**：Widget 和预览层只读快照，不执行 collector、SSH、`ccusage`，不写数据。
6. **TDD 驱动落地**：每个开发任务先写失败测试或契约测试，再实现最小代码。

## 用户范围

当前只服务单个本机用户的个人工程工作流。

不做团队 SaaS，不做多用户权限系统，不做云端同步，不做 billing-grade 财务系统。

## 产品能力域

### D1 Usage Facts

目标：

- 采集 `ccusage daily --json --timezone <tz>` 的 daily usage。
- 统一标准化 token 分项、total tokens、agent、source、日期。
- 支持本机、SSH 远程和手动文件导入。

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

- SQLite 是本机 canonical store。
- `latest.json` 是面向展示层的派生快照，不是唯一事实来源。
- 后续趋势、摘要、source 成功率都从 canonical store 或快照构建器派生。

### D4 Display Snapshot

目标：

- 展示层只读稳定快照。
- 快照包含 schema version、生成时间、时区、summary、items、source status 和可选扩展。
- 快照缺失、损坏、过期或局部失败都必须有明确降级状态。

### D5 Limits / Quota Windows

目标：

- quota/reset 是可插拔能力，不是 baseline 的前置依赖。
- 只有可验证来源才能显示为 observed quota。
- 估算来源必须标记为 estimated，并在 UI 上弱化。

禁止：

- 不从 `ccusage daily` 推断官方 quota。
- 不把 `ccusage blocks` 的本地窗口说成官方订阅额度。
- 不读取或同步 `.claude`、`.codex` 原始日志目录来倒推状态。

## 展示面

### CLI

CLI 是工程化验证入口，必须能执行：

- 采集。
- 构建快照。
- 检查配置。
- 输出 source health。
- 在测试环境使用 fixture 和临时路径运行。

### macOS Widget

Widget 是第一用户界面，目标是 glanceable：

- 今日 total tokens。
- source health。
- 按 account / agent / machine 的关键拆分。
- token 类型结构。
- 有可信 limits 时显示 5h / week 进度和 reset time。
- 没有可信 limits 时降级为 daily usage。

### 后续展示

菜单栏详情页、历史 dashboard、报表导出都是后续扩展，不作为当前工程化基础的前置条件。

## 阶段边界

### Phase 0: 文档和工程方向重设

目标：

- 产品文档、架构文档、任务包一致。
- 明确哪些现有实现保留，哪些设计可推翻。
- 在进入开发前固定 TDD 规则。

### Phase 1: Baseline Pipeline Hardening

目标：

- 把现有 collector 从“可跑原型”收敛成可测试、可演进的 baseline pipeline。
- 配置、runner、normalizer、SQLite、snapshot writer 都有契约测试。
- 不引入 quota/reset。

### Phase 2: Snapshot API v1

目标：

- 明确 `latest.json` v1 schema。
- 把 summary、source health、token type totals 等展示所需聚合放进快照。
- 保留当前 Widget 兼容字段或提供迁移策略。

### Phase 3: Widget v1

目标：

- Widget 先实现真实数据支撑的信息架构。
- small / medium / large 分层。
- 缺失数据和失败 source 有可靠 UI。

### Phase 4: Limits Source

目标：

- 在 baseline 稳定后引入 limits/quota source。
- 先支持结构化导出文件和 fixture。
- 每个字段都有 `source_type`、`confidence`、`observed_at`、`status`。

### Phase 5: Visual Polish and Operations

目标：

- 向 `docs/ui-direction/wight-ai-usage/` 的 Apple-style 视觉靠近。
- 补 launchd、App Group、签名、构建和运行文档。

## 关键技术决策

### 保留

- 保留 Python collector 作为数据管道实现语言。
- 保留 SQLite 作为本机 canonical store。
- 保留 `latest.json` 作为展示层读取入口。
- 保留 Mac 汇聚中心，不部署远程 daemon。
- 保留 `ccusage daily --json` 作为 daily usage baseline。
- 保留 SwiftUI / WidgetKit 作为 macOS 展示实现。

### 调整

- Widget 不再定义项目主架构；它只是 read-only presentation surface。
- quota/reset 不再作为当前主线前置项；它是 limits 插件域。
- `latest.json` 不应只是一组扁平 `items`；需要演进为 versioned display snapshot。
- 趋势图不直接读 SQLite；由 snapshot builder 预聚合后输出。
- 配置需要 schema 和校验，不能靠隐式字典字段扩散。

### 暂不做

- 不做长期运行的后台服务进程，先用 CLI + 后续 launchd 定时触发。
- 不做远程 agent 安装器。
- 不做官方 quota 抓取的逆向方案。
- 不做多租户、云同步、团队看板。

## 非功能需求

- 所有采集命令必须有超时。
- 所有文件写入必须原子化。
- 所有真实路径、host、密钥、token 放在本地配置或忽略目录。
- 测试不能依赖生产账户、真实 SSH、真实 `ccusage` 输出。
- 日志和错误信息需要截断，避免泄露完整原始 usage 内容。
- 文档、fixtures、schema、测试必须同步更新。

## 成功标准

项目进入工程化状态的最低标准：

- 从空测试数据到完整快照的路径可以用 fixture 重放。
- 任一 source 失败不会破坏其他 source 的展示。
- `latest.json` schema 有版本、fixture 和 Swift/Python 双侧解码测试。
- Widget 的每个展示块都能追溯到快照字段。
- limits/quota 缺失时仍有可用产品体验。
- 每个实现任务都有先红后绿的测试记录。
