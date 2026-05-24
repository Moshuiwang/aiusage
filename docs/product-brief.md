# Product Brief

## 产品目标

做一个 macOS 端 AI usage widget，把多个 OS 用户、多个机器、多个 AI coding agent 的使用状态汇总到一个本机入口。

项目目标已经从“只显示今日 token”扩展为两层：

1. **Daily usage baseline**：稳定采集 `ccusage daily --json`，生成 `data/latest.json` 和 `data/usage.sqlite`，Widget 能展示今日 token 和拆分。
2. **Quota/reset-aware Widget**：在 baseline 之上补充 5h / week quota、reset time、usage percentage，并靠近 `docs/ui-direction/wight-ai-usage/` 的 Apple-style Widget 方向。

## 用户问题

用户同时在这些环境使用 AI coding agent：

- Mac 本机账户：本机开发和日常操作。
- 远程 Linux `wang` 账户：主要开发账户。
- 远程 Linux `ubuntu` 账户：生产账户，通常不开发，但也可能产生 usage。

如果没有统一入口，用户需要分别登录不同账户查看 Claude Code、Codex 的使用状态，容易漏看生产账户或远程账户，也无法一眼看到额度窗口和重置时间。

## 阶段划分

### P0 Daily Usage Baseline

已进入实现/验证阶段：

- 支持 `mac-local`、`linux-wang`、`linux-ubuntu` 三个 daily source。
- 对每个 source 执行 `ccusage daily --json --timezone Asia/Shanghai`。
- 采集失败时记录 `source_status`，不影响其他 source。
- 输出 `data/latest.json`。
- 写入 `data/usage.sqlite`。
- Widget 展示今日 total tokens、按 machine / account / agent 拆分、最近采集时间和失败 source 状态。

### P1 Quota/Reset Data Source

当前研发方向：

- 获取 Claude Code / Codex 的 5h / week quota 状态。
- 获取 reset time / reset date。
- 输出 usage percentage，并标明数据来源和可信度。
- 在无法取得可靠 quota/reset 时，Widget 必须降级为 daily usage 视图。

关键约束：

- `ccusage daily --json` 不能提供官方 quota/reset。
- `ccusage blocks --json` 只能作为本地 block/session 视角，不能直接声明为官方订阅额度。
- quota/reset 必须由单独的数据源或结构化导出提供，详见 `docs/subscription-usage-source.md`。

### P2 Target Widget UI

目标方向：

- 采用 `docs/ui-direction/wight-ai-usage/` 的 small / medium / large Widget 信息密度分层。
- 支持 light/dark 和 foreground/background 状态。
- 以 agent 为主线展示 quota/reset 进度。
- 在大号 Widget 中展示 token 类型结构、source/host 分布和后续趋势。

## 数据源范围

| 范围 | 阶段 | 说明 |
| --- | --- | --- |
| Mac 当前用户 Claude Code / Codex daily usage | P0 | 本地执行 `ccusage daily --json` |
| Linux `wang` Claude Code / Codex daily usage | P0 | SSH 到 `wang` 后执行 `ccusage daily --json` |
| Linux `ubuntu` Claude Code / Codex daily usage | P0 | SSH 到 `ubuntu` 后执行 `ccusage daily --json` |
| SQLite daily 存储 | P0 | 本地文件 `data/usage.sqlite`，保存 daily 标准化数据 |
| quota/reset 结构化 source | P1 | 单独设计，不从 daily token history 推断官方状态 |
| 历史趋势聚合 | P2 | 如果 Widget 需要，collector 预聚合后写入 `latest.json` |
| raw archive | Backlog | 只归档 ccusage 报表，不归档 `.claude`、`.codex` 原始目录 |

## 非功能需求

- 采集命令必须有超时。
- JSON 输出必须原子写入。
- 单个 source 错误不能导致整个 `latest.json` 缺失。
- 配置里的真实 host 和 SSH 信息放在 `config/sources.local.json`，不提交。
- 日志不要写入密钥、完整私有路径或大段原始 usage 内容。
- SQLite 是本地文件，不启动数据库服务。
- quota/reset 字段必须标明来源和可信度，不能把估算展示成官方结论。
- 不直接修改生产账户文件。
- 不同步远程 `.claude`、`.codex` 原始日志目录。

## Non-goals

- 不追求 billing-grade precision。
- 不自研聊天内容 token 估算。
- 不把 `ccusage blocks` 的本地窗口直接说成官方 subscription quota。
- 不在未明确授权前修改远程用户配置。
- 不在 Widget 内执行 collector、SSH 或 ccusage。

## 成功标准

- P0：三路 daily source 可采集，`latest.json` 和 SQLite 结构稳定，Widget 能显示今日 usage 和采集状态。
- P1：quota/reset source 能输出可信字段；缺失或过期时有明确降级状态。
- P2：SwiftUI/WidgetKit UI 能贴近目标设计稿，同时只展示当前数据契约真实支持的内容。
