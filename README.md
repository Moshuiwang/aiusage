# AI Usage Widget

个人使用的 AI coding usage 观测工具，用来汇总多台设备、多 OS 用户、多 AI coding agent 的用量事实、采集健康状态和可验证的额度窗口状态。

当前项目已经从 Widget-first 原型重设为个人 HTTP 汇聚数据产品，并开始进入跨端客户端分层阶段：

- **Device push pipeline**：每台设备在自己的账户上下文运行 `ccusage daily --json`，把结构化用量主动 push 到个人 HTTP server。
- **Server canonical store**：HTTP server 校验 ingest payload，写入 SQLite canonical store，并生成展示快照。
- **Web presentation**：Web dashboard 是当前完整查看入口；CLI report 只读派生快照。
- **Client direction**：后续客户端按 `clients/` 分层，iPhone/iOS Widget 是已落地方向，macOS 走菜单栏或轻量桌面入口，Windows 走托盘或轻量桌面入口，Android 复用移动端摘要合同。
- **Optional limits source**：quota/reset 只作为可插拔 limits 能力；没有可信来源时不展示为强结论。

## 当前边界

- 先完成产品文档和任务包。
- 文档收敛前不开发代码。
- 后续开发遵守 TDD：先写失败测试，再实现最小代码。

## 目录结构

用户可见客户端的目标目录：

```text
clients/
  ios/       # iPhone App + iOS Widget 目标落点
  android/   # Android App + Android Widget 目标落点
  macos/     # macOS 菜单栏 / 轻量桌面入口目标落点
  windows/   # Windows 托盘 / 轻量桌面入口目标落点
  web/       # Web dashboard 目标落点
packages/
  client-contracts/ # 跨端展示数据合同
  design-tokens/    # 跨端视觉 token 和状态语义
```

迁移期保留现有实现路径：

- iOS Swift Package / Xcode 工程暂时仍在 `mobile/ios` 和 `mobile/ios-xcode`。
- Web dashboard 静态资源暂时仍在 `src/ai_usage_widget/static`。
- legacy macOS Widget 暂时仍在 `widget/macos` 和 `widget/macos-xcode`，只作历史兼容。

不要为了“目录好看”直接移动现有 iOS 或 Web 文件；迁移必须单独开任务包，先补构建或路由验证。

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

Legacy/local compatibility：本地采集 daily usage：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect \
  --config config/sources.local.json \
  --output data/latest.json \
  --sqlite data/usage.sqlite
```

当前 V2 推荐主线是 `DevicePusher push -> /ingest`。上面的 `collect` 命令只作为 legacy/local compatibility 和本地验证入口，不作为新部署主路径。

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

离线 fixture 采集 official limits 并写入 SQLite：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --provider-fixture tests/fixtures/limits_runtime_fixture.json \
  --sqlite data/usage.sqlite \
  --latest data/latest.json
```

使用本地 limits config 采集 official limits：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --limits-config config/limits.local.json
```

部署前 dry-run 验证 limits config，不写 SQLite / latest：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --limits-config config/limits.local.json \
  --dry-run
```

只检查 limits config 并输出脱敏 provider plan：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --limits-config config/limits.local.json \
  --check-config
```

真实 smoke 前做本机 readiness 诊断，不读取 auth 内容、不写 SQLite / latest：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --limits-config config/limits.local.json \
  --doctor
```

`config/limits.local.json` 支持同一 provider 的多个账号实例。为每个实例设置稳定的 `source_id`，SQLite / snapshot 会用它区分账号，避免两个 Claude 账号互相覆盖。Claude CLI provider 会先解析 `/usage` 文本；如果当前 Claude Code 只返回订阅说明，会回退读取同一配置目录下的 `active_limits.json` 当前额度 cache；如果 cache 也不存在，会执行一个极短 probe 来解析 session limit reset 文本，此时只生成 session window，不推断 weekly window。第二个 Claude Code 配置目录可以通过脱敏的 `env` map 表达，例如：

```json
{
  "provider": "claude",
  "source_id": "claude-w",
  "cli": true,
  "env": {
    "CLAUDE_CONFIG_DIR": "/Users/<user>/.claudew"
  }
}
```

`env` 只放运行环境变量，不放 token、secret、password 或 API key；`--check-config` / `--doctor` 只输出 env key，不输出 value。

显式指定 Codex auth 文件采集 WHAM usage：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --provider codex \
  --codex-auth-file /path/to/codex/auth.json \
  --sqlite data/usage.sqlite \
  --latest data/latest.json
```

显式指定 Codex app-server RPC 采集 rate limits：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --provider codex \
  --codex-rpc \
  --codex-rpc-sock /path/to/codex-app-server.sock \
  --sqlite data/usage.sqlite \
  --latest data/latest.json
```

显式指定 Claude auth 文件和 Usage API URL 采集 OAuth usage：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --provider claude \
  --claude-auth-file /path/to/claude/auth.json \
  --claude-usage-url https://example.invalid/claude/usage \
  --sqlite data/usage.sqlite \
  --latest data/latest.json
```

显式指定 Claude CLI `/usage` 采集 usage：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --provider claude \
  --claude-cli \
  --sqlite data/usage.sqlite \
  --latest data/latest.json
```

采集后同步给 legacy macOS WidgetKit extension：

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

Legacy macOS SwiftUI 预览：

```bash
cd widget/macos
swift run ai-usage-widget-preview
```

Legacy macOS Swift 测试：

```bash
cd widget/macos
swift test
```

Legacy macOS WidgetKit App 构建：

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
- [clients/README.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/clients/README.md)：跨端客户端目标目录和迁移规则。
- [client-platforms.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/architecture/client-platforms.md)：iOS、Android、macOS、Windows、Web 的展示边界。
- [mobile-app-design-brief.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/mobile-app-design-brief.md)：iPhone App + iOS Widget 的设计入口、信息架构和原型协作方式。
- [multi-platform-design-prd.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/multi-platform-design-prd.md)：最新多端设计包对应的产品体验、范围和优先级。
- [multi-platform-design-architecture.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/multi-platform-design-architecture.md)：Web、macOS、iOS Widget 和 Watch 共用事实链路的架构方案。
- [multi-platform-design-database.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/multi-platform-design-database.md)：多端设计所需展示字段与现有 SQLite 表的映射。
- [multi-platform-design-interface.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/multi-platform-design-interface.md)：多端展示所需 Summary API 字段和降级约定。
- [task-plan.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/task-plan.md)：旧任务入口兼容层，指向任务包目录。
- [task-packages/README.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/task-packages/README.md)：任务包目录入口。
- [task-packages/RULES.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/task-packages/RULES.md)：任务包详细规则、编号、状态、TDD 和 subagent 执行规则。
- [task-packages/v2/INDEX.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/task-packages/v2/INDEX.md)：V2 任务包索引，面向个人 HTTP push 架构。
- [task-packages/v1/INDEX.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/task-packages/v1/INDEX.md)：V1 任务包索引，旧 SSH pull / Widget-first 执行序列，仅作历史参考。
- [operations.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/operations.md)：个人 Ingest 服务端运维、配置与备份文档。
- [schedulers.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/schedulers.md)：各平台终端定时任务配置文档。
- [handoff.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/handoff.md)：项目重构完成后的交接及后续部署指引。
- [display-options.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/display-options.md)：历史 Widget 展示候选和信息块，仅作移动端设计参考。
- [subscription-usage-source.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/subscription-usage-source.md)：limits/quota 数据源方向。
- [widget-macos.md](file:///Users/wangzhipeng/Documents/ai-usage-widget/docs/widget-macos.md)：legacy macOS SwiftUI/WidgetKit 构建、预览和同步。
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

工程化目标是 versioned display snapshot，详见 `docs/architecture.md`。迁移期需要保留 `items` 和 `source_status`，避免立即破坏现有 legacy macOS Widget 和 CLI report；后续 iPhone App / iOS Widget 可以改读 Web API 或移动端专用摘要。
