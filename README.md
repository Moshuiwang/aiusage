# AI Usage Widget

个人使用的 AI coding usage 观测工具，用来汇总多台设备、多 OS 用户、多 AI coding agent 的用量事实、采集健康状态和可验证的额度窗口状态。

当前项目正在从 Widget-first 原型重设为个人 HTTP 汇聚数据产品：

- **Device push pipeline**：每台设备在自己的账户上下文运行 `ccusage daily --json`，把结构化用量主动 push 到个人 HTTP server。
- **Server canonical store**：HTTP server 校验 ingest payload，写入 SQLite canonical store，并生成展示快照。
- **Web presentation**：Web dashboard 是主要查看入口；Widget、SwiftUI preview 和 CLI report 都只读派生快照。
- **Optional limits source**：quota/reset 只作为可插拔 limits 能力；没有可信来源时不展示为强结论。

## 当前边界

- 先完成产品文档和任务包。
- 文档收敛前不开发代码。
- 后续开发遵守 TDD：先写失败测试，再实现最小代码。

## 数据源

目标 daily source：

| Source ID | 机器 | OS 用户 | 执行方式 |
| --- | --- | --- | --- |
| `mac-local` | Mac 终端 | 当前 macOS 用户 | 本机采集后 HTTP push |
| `linux-server-1` | Linux 服务器 | 该服务器上的目标 OS 用户 | 本机采集后 HTTP push |
| `linux-server-2` | Linux 服务器 | 该服务器上的目标 OS 用户 | 本机采集后 HTTP push |
| `windows-desktop` | Windows 台式机 | 当前 Windows 用户 | 本机采集后 HTTP push |

limits/quota source 仍是后续可插拔能力，见 `docs/subscription-usage-source.md`。

硬规则：

- 每个 OS 用户只在自己的账户上下文运行 `ccusage`。
- `wang` 不读取 `/home/ubuntu`。
- 不暴露 SSH 给汇聚端抓取 usage。
- 汇聚端不主动登录远端机器。
- 各终端不上传 `.claude`、`.codex` 原始日志目录，只上传设计过的结构化 usage payload。
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

目标形态下，终端侧命令会演进为本机采集后 push 到 HTTP server；当前 CLI 命令仍是旧 baseline 的本地验证入口，具体以 `docs/task-packages/v2/INDEX.md` 后续任务包为准。

HTTP push 终端侧命令：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli push \
  --config config/sources.local.json \
  --lock-file /tmp/ai-usage-pusher.lock
```

服务端 SQLite 在线备份：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli backup \
  --db data/usage.sqlite \
  --backup-dir data/backups \
  --keep 14 \
  --max-total-mb 512
```

服务端健康检查：

```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/health
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

- [AGENTS.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/AGENTS.md)：每次会话自动读取的最小硬规则和文档路由。
- [status.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/status.md)：当前阶段、有效决策和下一步。
- [product-brief.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/product-brief.md)：产品定位、能力域、阶段边界和关键技术决策。
- [architecture.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/architecture.md)：工程架构、数据链路、schema 目标和测试架构。
- [task-plan.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/task-plan.md)：旧任务入口兼容层，指向任务包目录。
- [task-packages/README.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/task-packages/README.md)：任务包目录入口。
- [task-packages/RULES.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/task-packages/RULES.md)：任务包详细规则、编号、状态、TDD 和 subagent 执行规则。
- [task-packages/v2/INDEX.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/task-packages/v2/INDEX.md)：V2 任务包索引，面向个人 HTTP push 架构。
- [task-packages/v1/INDEX.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/task-packages/v1/INDEX.md)：V1 任务包索引，旧 SSH pull / Widget-first 执行序列，仅作历史参考。
- [operations.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/operations.md)：个人 Ingest 服务端运维、配置与备份文档。
- [schedulers.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/schedulers.md)：各平台终端定时任务配置文档。
- [handoff.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/handoff.md)：项目重构完成后的交接及后续部署指引。
- [display-options.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/display-options.md)：Widget 展示候选和信息块。
- [subscription-usage-source.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/subscription-usage-source.md)：limits/quota 数据源方向。
- [widget-macos.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/widget-macos.md)：SwiftUI/WidgetKit 构建、预览和同步。
- [ui-direction/wight-ai-usage/README.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/ui-direction/wight-ai-usage/README.md)：目标 UI 设计稿归档说明。

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
