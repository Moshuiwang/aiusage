# PRD: Account Hourly Usage

## 背景

当前产品已经能汇总多设备 AI coding 用量，但旧主链路依赖 `ccusage daily` 的当天累计值。这个口径适合看“今天总共用了多少”，不适合回答“这些 token 来自哪个 AI 账号、哪台机器、哪个机器登录用户”。

本轮目标是把 usage 从“按天累计”升级为“按小时增量事实”，并在每条事实上同时记录三层归因：

- 机器：这笔用量发生在哪台设备。
- 机器登录用户：这笔用量发生在哪个 OS 用户上下文。
- AI 登录账号：这笔用量当时归属哪个 Codex / Claude 账号。

## 用户问题

用户需要回答：

- 今天 Codex / Claude 分别用了多少 token。
- 这些 token 来自哪台机器。
- 这些 token 来自哪个机器登录用户。
- 这些 token 来自哪个 ChatGPT / Claude 账号。
- 最近一小时、今天、本周、本月的用量趋势。
- 哪些客户端可采，哪些客户端不可采或账号不可信。

## 用户体验目标

用户打开 Web dashboard 或 iPhone App 后，默认看到：

- 今日总用量。
- 最近一小时新增用量。
- 按 AI 账号拆分。
- 按机器拆分。
- 按机器登录用户拆分。
- 按工具拆分：Codex、Claude Code、后续其他 agent。
- 采集状态：正常、过期、失败、不支持。
- 账号归因状态：强归因、采集时账号推断、账号切换、账号未知。

用户点进某个账号时，能看到这个账号在不同机器、不同 OS 用户、不同 agent 上的用量。

用户点进某台机器时，能看到这台机器上不同 OS 用户和 AI 账号的用量。

用户点进某个 OS 用户时，能看到该用户上下文里 Codex / Claude Code 的用量和账号归属。

## 范围

### 本轮纳入

- Codex 本地 token 事件采集。
- Claude Code 本地 usage 事件采集。
- VS Code Claude Code 扩展的归属验证：如果它进入 Claude Code 本地日志，则纳入 Claude Code 口径。
- 机器身份采集。
- OS 登录用户采集。
- AI 登录账号采集。
- 小时增量事实上报。
- 服务端按小时、天、周、月聚合。
- UI 展示可信度。

### 本轮不承诺

- Claude Desktop App 普通聊天 token 采集。
- ChatGPT Desktop / Web 普通聊天 token 采集。
- 没有本地 token 事件的客户端。
- billing-grade 财务对账。
- 团队多租户。

## 已验证事实

在当前 Mac 上已验证：

- Codex 有本地 token 事件，可按时间戳切小时。
- Codex 当前 ChatGPT 账号可从本地登录 claim 识别。
- Claude Code 有本地 usage 事件，可按时间戳切小时。
- Claude Code 当前账号可通过 `claude auth status` 识别。
- VS Code 安装的是 Anthropic Claude Code 扩展，需用一次真实扩展消息确认它是否进入同一套 Claude Code usage 日志。
- Claude Desktop App 目录存在，但未确认有可用于普通聊天 token 统计的明细事件。

## 核心原则

1. 不再把 `ccusage daily` 作为账号归因主数据源。
2. 每条 usage fact 必须带机器、OS 用户、agent、AI 账号、时间窗口。
3. UI 不能把不可信归因显示成强结论。
4. 账号切换时，采集器必须保留证据，不得静默混算。
5. 不上传 prompt、response、工具输出、原始日志路径、auth token。
6. 服务端只接收结构化增量事实，不读取终端本地原始日志。

## 关键场景

### 场景 1: 查看今日账号用量

用户看到：

- `startimessocietegn@gmail.com / Codex / 今日 10.6M tokens`
- `wangzhipeng2010@gmail.com / Claude Code / 今日 760K tokens`

每一行可以展开机器和 OS 用户来源。

### 场景 2: 查看机器用量

用户看到：

- `MacBook Pro / wangzhipeng / Codex / startimessocietegn@gmail.com`
- `MacBook Pro / wangzhipeng / Claude Code / wangzhipeng2010@gmail.com`

机器和 OS 用户不再只是 metadata，而是可筛选、可 drilldown 的正式维度。

### 场景 3: 账号切换

如果采集器发现一个小时内同一个 source 出现账号变化，UI 显示：

- 该小时标记为“账号切换”。
- 可以展示机器和 OS 用户维度。
- AI 账号维度标记为 `mixed_account`，不强行归到最后登录账号。

### 场景 4: 不支持客户端

如果 Claude Desktop App 没有可读 token 事件，UI 显示：

- `Claude Desktop: 不支持 token 明细采集`
- 不把 Claude Code 的用量冒充 Claude Desktop。

## 数据可信度

可信度拆成两类，避免 UI 把“账号不确定”和“采集失败”混成一件事。

`attribution_confidence` 只描述这笔 token 的账号归因是否可信：

| 级别 | 含义 | UI 表达 |
| --- | --- | --- |
| observed | token 事件本身带账号证据，或客户端提供等价的事件级账号证据 | 强展示 |
| account_observed_usage_inferred | token 事件可信，账号来自采集窗口当前状态 | 可展示，带说明 |
| mixed_account | 同一窗口检测到账户变化 | 弱展示，不进账号强排行 |
| account_unknown | token 事件可信，但没有账号证据 | 不进账号强排行 |

`support_status` / `source_status` 描述客户端和采集是否可用：

| 级别 | 含义 | UI 表达 |
| --- | --- | --- |
| unsupported | 客户端存在但没有可采 token 明细 | 展示不可用 |
| missing | 没有发现客户端或采集源 | 展示缺失 |
| failed | 采集失败 | 展示错误摘要 |

## 成功指标

- 用户能按小时查看 Codex / Claude Code 用量。
- 用户能按 AI 账号查看日/周/月用量。
- 用户能按机器和机器登录用户查看日/周/月用量。
- 账号切换不会造成静默误归因。
- UI 能清楚区分“没有用量”和“采集失败/不支持”。

## 迁移策略

旧的 `ccusage daily` 数据保留为历史 daily baseline，但不用于 AI 账号强归因。

新数据从上线时开始生成小时事实。历史数据只能显示为：

- 按机器 / OS 用户 / agent 的历史用量。
- AI 账号归因如果没有当时证据，只能标记为 `account_observed_usage_inferred` 或 `account_unknown`。

## 与现有产品入口的关系

本轮不是另起一个用户看不到的新系统。新小时事实进入现有 HTTP push / SQLite / summary 链路：

- Web dashboard 继续通过现有 `/api/summary` 读取聚合结果。
- iPhone App 继续通过现有 `/api/mobile/summary` 读取移动端摘要。
- 新小时事实先作为现有 summary 的新增数据源接入；只有在旧接口无法表达时，才新增 versioned endpoint。
- 迁移期内，旧 daily 数据只用于历史 fallback，不参与 AI 账号强排行。
