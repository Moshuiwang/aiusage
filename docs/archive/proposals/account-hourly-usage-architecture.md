# Architecture: Account Hourly Usage

## 目标架构

```text
Local Usage Collectors
  -> Hourly Delta Builder
  -> Account / Machine / OS User Identity
  -> HTTP Ingest
  -> SQLite Canonical Store
  -> Summary API
  -> Web Dashboard / iPhone App / iOS Widget
```

这条链路替代 `ccusage daily` 作为账号归因主链路。`ccusage` 可以保留为历史对照或 fallback，但不再作为“按 AI 账号统计”的事实来源。

## 核心对象

### Device

表示真实机器。

示例：

- `macbook-pro`
- `vpn2`
- `windows-desktop`

机器身份用于回答“哪台机器产生了这些 token”。

### OS User

表示机器上的登录用户。

示例：

- `wangzhipeng`
- `wang`
- `ubuntu`

OS 用户用于回答“哪个机器登录用户产生了这些 token”。采集器必须在该用户上下文运行，不能跨用户读 home 目录。

### AI Account

表示 AI 产品登录账号。

示例：

- Codex / ChatGPT: `startimessocietegn@gmail.com`
- Claude Code: `wangzhipeng2010@gmail.com`

AI 账号用于回答“哪个 AI 账号消耗了这些 token”。

### Usage Event

本地客户端留下的 token 使用事件，必须至少包含：

- 时间戳。
- agent。
- token 分项或总数。
- session id 或可去重 id。

Usage Event 不上传原始内容，只在本地被解析成小时增量。

### Hourly Usage Fact

服务端最终保存的事实。它是产品展示的基本单位。

包含：

- 时间窗口：`window_start` / `window_end`。
- 机器：`machine_id`。
- OS 用户：`os_user`。
- AI 账号：`ai_account_id`。
- agent：`codex` / `claude_code`。
- token 分项。
- 可信度。
- 采集状态。

## 本地采集层

### Codex Collector

输入：

- 当前 OS 用户的 Codex 本地 session 事件。
- 当前 OS 用户的 Codex / ChatGPT 登录状态。

输出：

- Codex 小时增量 facts。
- 当前 ChatGPT 账号。
- 账号证据状态。

可信边界：

- token 事件可信。
- 当前账号状态可信，但它只证明“采集时看到的账号”，不等于 token 事件自带账号。
- 默认账号归因标记为 `account_observed_usage_inferred`。
- 只有事件本身带账号证据，或客户端提供等价事件级账号证据时，才标记 `observed`。
- 如果同一窗口内账号切换，需要标记 `mixed_account`。

### Claude Code Collector

输入：

- 当前 OS 用户的 Claude Code 本地 project/session usage 事件。
- `claude auth status` 返回的账号状态。

输出：

- Claude Code 小时增量 facts。
- 当前 Claude 账号。
- 账号证据状态。

可信边界：

- Claude Code CLI usage 事件可信。
- VS Code Claude Code 扩展只有在验证写入同一套 usage 日志后，才纳入 Claude Code。
- Claude Desktop App 不默认纳入。
- 本轮 Claude Code 小时来源先保持现有已验证口径；Claude 自有 parser 只作为后续验证任务，不阻塞本轮。

### Client Support Matrix

| 客户端 | token 明细 | 账号身份 | 本轮状态 |
| --- | --- | --- | --- |
| Codex CLI / Codex desktop session | 可采 | 可采 | 纳入 |
| Claude Code CLI | 可采 | 可采 | 纳入 |
| VS Code Claude Code extension | 待最终 smoke | 复用 Claude Code | 条件纳入 |
| Claude Desktop App | 未确认 | 可见配置不足 | 不承诺 |
| ChatGPT Desktop / Web | 未确认 | 未纳入 | 不承诺 |

## 小时增量策略

采集器每次运行时：

1. 读取本地事件。
2. 只解析 token、时间戳、model、session id 等非内容字段。
3. 按目标时区切小时窗口。
4. 与本地 cursor / last seen event 去重。
5. 生成本轮新增的 hourly facts。
6. 附加机器、OS 用户、AI 账号。
7. 上传服务端。

账号归因和小时趋势不依赖“今天累计值”，而是读取小时事实。迁移期 headline daily total 继续保护现有 daily baseline，避免小时采集漏一段时用户看到今日总量突然变小。只有当 hourly 覆盖率、drift 和健康状态达标后，headline 才能切到纯 hourly 聚合。

## 账号切换处理

账号切换是最大误归因风险。

处理规则：

- 一个采集窗口只看到一个账号：默认标记 `account_observed_usage_inferred`。
- 同一 source 在同一小时出现多个账号证据：标记 `mixed_account`。
- 只有 token 事件，没有账号证据：标记 `account_unknown`。
- 账号证据来自采集时刻，不来自事件本身：标记 `account_observed_usage_inferred`。
- 只有 token 事件本身或客户端事件级元数据提供账号证据：标记 `observed`。

UI 规则：

- `observed` 可以进入账号排行。
- `account_observed_usage_inferred` 只能在账号详情或单独的 inferred 分段展示，不进入强账号排行。
- `mixed_account` 不进入强账号排行，只进入机器/OS 用户/agent 统计。

## 服务端聚合层

服务端提供这些聚合：

- 最近一小时。
- 今日。
- 本周。
- 本月。
- 任意时间范围。

每个范围都支持按这些维度拆分：

- AI 账号。
- 机器。
- OS 用户。
- agent。
- model。
- source。

## 安全边界

本地采集器禁止上传：

- prompt。
- response。
- tool output。
- shell output。
- auth token。
- refresh token。
- 原始 JSONL 行。
- 本地原始日志路径。

服务端禁止：

- SSH 到设备抓 usage。
- 跨 OS 用户读取 home 目录。
- 把 token history 推断成官方额度。
- 把不支持客户端显示为 0 用量。

## 与现有 V2 架构关系

保留：

- HTTP push 架构。
- SQLite canonical store。
- source health。
- Web API / mobile summary。
- limits provider 与 usage pipeline 分离。

替换：

- 账号归因主链路不再依赖 `ccusage daily`。
- Codex 小时口径从 session fallback 改为本地 token event。
- Claude Code 小时口径保持现有已验证口径，账号归因通过 `claude auth status` 补充；自有 parser 另开任务验证。

兼容：

- 旧 daily 数据可继续展示历史趋势。
- 新账号视图只对新 hourly facts 给强结论。
