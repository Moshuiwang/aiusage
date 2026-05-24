# AI Usage Widget

本机优先的 AI coding usage 观测工具，用来汇总多台机器、多 OS 用户、多 AI coding agent 的用量事实、采集健康状态和可验证的额度窗口状态。

当前项目正在从 Widget-first 原型重设为工程化数据产品：

- **Baseline pipeline**：稳定采集 `ccusage daily --json`，写入 SQLite canonical store，并生成展示快照。
- **Snapshot presentation**：Widget、SwiftUI preview 和 CLI report 都只读 `latest.json` 派生快照。
- **Optional limits source**：quota/reset 只作为可插拔 limits 能力；没有可信来源时不展示为强结论。

## 当前边界

- 先完成产品文档和任务包。
- 文档收敛前不开发代码。
- 后续开发遵守 TDD：先写失败测试，再实现最小代码。

## 数据源

固定 daily source：

| Source ID | 机器 | OS 用户 | 执行方式 |
| --- | --- | --- | --- |
| `mac-local` | Mac 本机 | 当前 macOS 用户 | `ccusage daily --json` |
| `linux-wang` | `ai.chunbai.com` | `wang` | `ssh wang@ai.chunbai.com 'ccusage daily --json'` |
| `linux-ubuntu` | `ai.chunbai.com` | `ubuntu` | `ssh ubuntu@ai.chunbai.com 'ccusage daily --json'` |

limits/quota source 仍是后续可插拔能力，见 `docs/subscription-usage-source.md`。

硬规则：

- 每个 OS 用户只在自己的账户上下文运行 `ccusage`。
- `wang` 不读取 `/home/ubuntu`。
- Mac 不同步或解析远程 `.claude`、`.codex` 原始日志目录。
- `config/sources.local.json`、`data/latest.json`、`data/usage.sqlite` 不提交。

## 常用命令

运行 Python 测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

采集 daily usage：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect \
  --config config/sources.local.json \
  --output data/latest.json \
  --sqlite data/usage.sqlite
```

采集后同步给 WidgetKit extension：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect \
  --config config/sources.local.json \
  --output data/latest.json \
  --sqlite data/usage.sqlite \
  --sync-widget
```

只同步现有快照：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli sync-widget --input data/latest.json
```

SwiftUI 预览：

```bash
cd widget/macos
swift run ai-usage-widget-preview
```

Swift 测试：

```bash
cd widget/macos
swift test
```

WidgetKit App 构建：

```bash
cd widget/macos-xcode
xcodegen generate
xcodebuild -project AIUsageWidget.xcodeproj \
  -scheme AIUsageWidgetApp \
  -configuration Debug \
  -destination 'platform=macOS' \
  build
```

## 关键文件

- `AGENTS.md`：每次会话自动读取的最小硬规则和文档路由。
- `docs/status.md`：当前阶段、有效决策和下一步。
- `docs/product-brief.md`：产品定位、能力域、阶段边界和关键技术决策。
- `docs/architecture.md`：工程架构、数据链路、schema 目标和测试架构。
- `docs/task-plan.md`：旧任务入口兼容层，指向任务包目录。
- `docs/task-packages/README.md`：任务包目录入口。
- `docs/task-packages/RULES.md`：任务包详细规则、编号、状态、TDD 和 subagent 执行规则。
- `docs/task-packages/v1/INDEX.md`：V1 任务包索引。
- `docs/display-options.md`：Widget 展示候选和信息块。
- `docs/subscription-usage-source.md`：limits/quota 数据源方向。
- `docs/widget-macos.md`：SwiftUI/WidgetKit 构建、预览和同步。
- `docs/ui-direction/wight-ai-usage/README.md`：目标 UI 设计稿归档说明。

## 快照方向

`latest.json` 是展示层读取入口。当前原型字段是：

```json
{
  "generated_at": "2026-05-24T12:30:00+08:00",
  "timezone": "Asia/Shanghai",
  "items": [],
  "source_status": []
}
```

工程化目标是 versioned display snapshot，详见 `docs/architecture.md`。迁移期需要保留 `items` 和 `source_status`，避免立即破坏现有 Widget。
