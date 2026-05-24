# Status

## 用途

这是 AI agent 的当前工作状态入口，只记录当前阶段、有效决策和下一步。项目背景、架构细节、任务拆解分别去读对应文档。

## 当前阶段

项目已从 daily token baseline 进入 quota/reset-aware Widget 方向收敛阶段。

已落地 baseline：

- Python collector、local / SSH / file import runner、normalizer 已建立。
- collector 已能写 `data/latest.json` 和 `data/usage.sqlite`。
- `latest.json` 已包含 `generated_at`、`timezone`、`items`、`source_status`。
- SwiftUI 预览层和 WidgetKit extension 初版已建立。
- `sync-widget` CLI 已能把仓库内快照同步到 WidgetKit extension sandbox container。
- `docs/ui-direction/wight-ai-usage/` 已归档目标 UI 设计原型。

## 当前决策

- Baseline 链路保持：Mac Collector -> local/SSH `ccusage daily --json` -> Normalizer -> `latest.json` + SQLite -> Widget。
- `latest.json` 仍是展示层第一读取入口；Widget 不直接读 SQLite。
- SQLite 只做本地 daily 历史文件，不是数据库服务。
- 固定 daily source 仍是 `mac-local`、`linux-wang`、`linux-ubuntu`。
- 当前 UI 研发方向转向 Apple-style quota/reset-aware Widget，但 quota/reset 必须来自单独设计的数据源，不能用 daily token history 伪装。
- `AGENTS.md` 只保留硬规则和文档入口，不承载详细项目状态。

## 当前待收敛点

- 为 quota/reset 扩展确定可靠数据源、字段可信度和降级策略。
- 扩展 `latest.json` 契约，使 daily usage、source status、quota windows 可以共存。
- 把目标 UI 原型翻译成 SwiftUI/WidgetKit 信息架构，缺失数据时必须有明确降级状态。
- 确认 agent 字段能否稳定区分 Claude Code / Codex；不能稳定时继续显示 `unknown` 或 `all`。
- 清理文档旧 MVP 表述，避免和当前研发方向冲突。

## 下一步

1. 完成 harness 和文档目标收敛，让 `status.md`、`product-brief.md`、`task-plan.md`、`display-options.md` 不再互相冲突。
2. 按 `docs/subscription-usage-source.md` 验证 quota/reset 数据源可行性。
3. 更新 `docs/architecture.md` 的 `latest.json` schema，加入 quota/reset 扩展字段。
4. 实现 collector 的 quota/reset source，并保留无数据时的 Widget 降级显示。
5. 再按 `docs/ui-direction/wight-ai-usage/` 改造 SwiftUI/WidgetKit UI。

## 文档读取顺序

- 当前状态和下一步：读本文件。
- 硬规则和禁止项：读 `AGENTS.md`。
- 项目入口和命令：读 `README.md`。
- 产品目标和阶段边界：读 `docs/product-brief.md`。
- 采集链路、模块边界、schema：读 `docs/architecture.md`。
- 下一步实现和验收：读 `docs/task-plan.md`。
- 展示数据、图表和 Widget 方案：读 `docs/display-options.md`。
- quota/reset 数据源方向：读 `docs/subscription-usage-source.md`。
- macOS Widget 构建和同步：读 `docs/widget-macos.md`。
- UI 目标设计稿和边界说明：读 `docs/ui-direction/wight-ai-usage/README.md`。
- Harness 文档规则、AI agent 读取和维护规则：读 `docs/agent-harness-rules.md`。
