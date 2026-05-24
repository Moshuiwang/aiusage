# AI Usage Widget

macOS 端 AI usage widget，用来汇总多台机器、多 OS 用户、多 AI coding agent 的 token 使用和额度窗口状态。

当前项目分两层推进：

- **Daily usage baseline**：collector 采集 `ccusage daily --json`，写入 `data/latest.json` 和 `data/usage.sqlite`，Widget 展示今日 token 和 source 状态。
- **Quota/reset-aware Widget**：补充 5h / week quota、reset time、usage percentage，并靠近 `docs/ui-direction/wight-ai-usage/` 的目标 UI。

## 数据源

固定 daily source：

| Source ID | 机器 | OS 用户 | 执行方式 |
| --- | --- | --- | --- |
| `mac-local` | Mac 本机 | 当前 macOS 用户 | `ccusage daily --json` |
| `linux-wang` | `ai.chunbai.com` | `wang` | `ssh wang@ai.chunbai.com 'ccusage daily --json'` |
| `linux-ubuntu` | `ai.chunbai.com` | `ubuntu` | `ssh ubuntu@ai.chunbai.com 'ccusage daily --json'` |

quota/reset source 仍在设计和验证阶段，见 `docs/subscription-usage-source.md`。

硬规则：

- 每个 OS 用户只在自己的账户上下文运行 `ccusage`。
- `wang` 不读取 `/home/ubuntu`。
- Mac 不同步或解析远程 `.claude`、`.codex` 原始日志目录。
- `config/sources.local.json`、`data/latest.json`、`data/usage.sqlite` 不提交。

## 常用命令

运行测试：

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
- `docs/product-brief.md`：产品目标、阶段范围和 non-goals。
- `docs/architecture.md`：collector、schema、SQLite、错误模型。
- `docs/task-plan.md`：当前可执行任务和验收标准。
- `docs/display-options.md`：Widget 展示候选和信息块。
- `docs/subscription-usage-source.md`：quota/reset 数据源方向。
- `docs/widget-macos.md`：SwiftUI/WidgetKit 构建、预览和同步。
- `docs/ui-direction/wight-ai-usage/README.md`：目标 UI 设计稿归档说明。

## `latest.json`

Widget 的第一读取入口是 `data/latest.json`。当前 baseline 字段：

```json
{
  "generated_at": "2026-05-22T08:30:00+08:00",
  "timezone": "Asia/Shanghai",
  "items": [
    {
      "machine": "macbook",
      "account": "local",
      "agent": "codex",
      "date": "2026-05-22",
      "input_tokens": 12345,
      "output_tokens": 6789,
      "cache_creation_tokens": 1000,
      "cache_read_tokens": 2000,
      "total_tokens": 22134
    }
  ],
  "source_status": [
    {
      "source_id": "mac-local",
      "status": "ok"
    }
  ]
}
```

quota/reset 扩展会在不破坏 `items` 和 `source_status` 的前提下新增字段。
