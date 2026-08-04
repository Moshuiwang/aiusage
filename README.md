# AI Usage Widget

> 代码平台为 GitHub 仓库：[AI Usage](https://github.com/Moshuiwang/aiusage)。开发、Issue、PR、同步和发布均以该仓库为准。

个人使用的 AI coding usage 观测工具，用来汇总多台设备、多 OS 用户、多 AI coding agent 的用量事实、采集健康状态和可验证的额度窗口状态。

当前项目已经从 Widget-first 原型重设为个人 HTTP 汇聚数据产品，并开始进入跨端客户端分层阶段。生产入口已经切到 Cloudflare Worker + D1，VPN2 旧后端不再承载 AI Usage 读写链路。

- **Device push pipeline**：每台设备在自己的账户上下文运行本机 Python pusher，读取本机 Codex / Claude / `ccusage` 结构化用量并主动 push。
- **Usage Ledger**：本机只上传去敏后的小时用量事实，不上传 `.codex` / `.claude` 原始日志、prompt、response、tool output 或原始路径；服务端负责去重、入账和聚合。
- **Canonical store**：生产 canonical store 是 Cloudflare D1（SQLite-compatible serverless SQL）。#74 起服务端没有本地 SQLite；采集端唯一的本地库是 outbox 缓冲（`collector_store.py`）。
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
- Web dashboard 静态资源在 `cloudflare/native-worker/static`（#74/PM-1 起归 Worker 管）。
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

- 每个 OS 用户只在自己的账户上下文运行本机采集；`ccusage` 只作为日级对账和历史兜底，不应阻断 Codex / Claude Usage Ledger 明细上报。
- `wang` 不读取 `/home/ubuntu`。
- 不暴露 SSH 给汇聚端抓取 usage。
- 汇聚端不主动登录远端机器。
- 各终端不上传 `.claude`、`.codex` 原始日志目录，只上传设计过的结构化 usage payload。
- Mac 不同步或解析远程 `.claude`、`.codex` 原始日志目录。
- `config/sources.local.json`、`data/latest.json`、`data/usage.sqlite` 不提交。

## 安装与升级（采集端，#124）

三个 OS 同一条命令（uv 单文件自举、自管 Python 版本）：

```bash
# 安装/升级到指定版本（发版即打 tag，tag 与 COLLECTOR_VERSION 同名，如 v0.3.0；
# tag 随发版才存在，可先用分支名或 commit 验证通道）
uv tool install "ai-usage-widget @ git+https://github.com/Moshuiwang/aiusage@<tag>"

# 没有 uv 时先装它（Linux/Mac；Windows 用 powershell 版安装脚本）
curl -LsSf https://astral.sh/uv/install.sh | sh
```

- **版本单源**：包版本动态取自 `version_contract.COLLECTOR_VERSION`（pyproject 不手写版本，
  `tests/test_version_single_source.py` 守着）。发版流程 = 升 `COLLECTOR_VERSION` → 打同名 tag。
- **定时单元**：`deploy_units.py` 渲染三个 OS 的定时任务（systemd / launchd / Windows Task
  Scheduler）。Windows 侧用 `render_windows_task_xml()` 生成任务 XML（UTF-16 写盘），
  `schtasks /Create /TN <任务名> /XML <文件>` 导入；任务名见 `CollectorUnitSpec.windows_task_name`。
- **体检**：`ai-usage-widget doctor` 认得两种部署形态——版本化 release 目录，以及
  uv tool install / pip 的已安装包（版本可追溯）。
- 自动升级暂不开启（#106/D7 决策）：升级 = 重跑一条 `uv tool install ...@新tag`。

## 常用命令

验证（唯一入口，会按改动面自动裁剪：不动 `cloudflare/` 就不跑 Worker 测试）：

```bash
scripts/verify.sh                 # 按改动面裁剪
scripts/verify.sh --full          # 强制全量
scripts/verify.sh --explain-scope # 只看裁剪判定，不跑测试
```

重新生成服务端合同 golden（`value_golden` / `provider_slots_golden` / `api_contract_golden`
/ macOS owner fixture）——**只在 Worker 输出确实要变时才跑，跑完必须逐条复核 `git diff`**：

```bash
npm run cf:golden:gen
```

本地起**服务端**（Worker + 本地 D1，与生产同款实现）：

```bash
scripts/dev_worker.sh --seed      # 应用 migrations + 灌示例数据 + 起服务
```

需要 Node >= 22。完全离线可用（首次 `npm ci` 之后）。
详见 [`docs/architecture/local-worker-development.md`](docs/architecture/local-worker-development.md)。

> Python 服务端（`cli server` 及整条读模型路径）已按 #67 决策于 #74 **删除**，
> 服务端唯一实现是 Cloudflare Worker + D1。采集端仍是 Python，照常开发。

只跑 Python 测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

> legacy 的 `cli collect`（本地采集写 `latest.json` / 本地 SQLite）已随 #74 删除；
> 采集主线是 `DevicePusher push -> /ingest`。

HTTP push 终端侧命令：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli push \
  --config config/sources.local.json \
  --ledger-mode incremental \
  --ledger-lookback-hours 48 \
  --lock-file /tmp/ai-usage-pusher.lock
```

官方额度上报（给了 `--config` 才走本地 outbox：断网时观测先落盘、恢复后补推；不给就是直推）：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli push-limits \
  --limits-config config/limits.local.json \
  --url https://aiusage.chunbai.com/ingest-limits \
  --config config/sources.local.json
```

本地 outbox 的运维入口（关闭 outbox 回退直推前必须先排空，**不允许静默丢弃**）：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli outbox-status --config config/sources.local.json
PYTHONPATH=src python3 -m ai_usage_widget.cli outbox-export --config config/sources.local.json --dest /tmp/outbox-export.json
PYTHONPATH=src python3 -m ai_usage_widget.cli outbox-drain  --config config/sources.local.json --export-to /tmp/outbox-export.json --yes
```

`outbox-drain` 会先导出再清空，且必须显式加 `--yes`；没有无条件清空的入口。

当前 macOS 本机生产上报由 LaunchAgent `com.chunbai.aiusage.pusher` 每 300 秒触发一次，实际运行 `/usr/bin/python3 -m ai_usage_widget.cli push`。它把最近窗口内有用量的 Codex / Claude 小时桶上报到 `https://aiusage.chunbai.com/ingest`，服务端按同一来源、账号、agent 和小时窗口 upsert；重复上报不会累加成假用量。

生产健康检查走 `verify-cloud health`（下方）或
`curl -H "Authorization: Bearer <token>" https://aiusage.chunbai.com/api/health`。

云端数据只读核对（无图形界面的环境用它自行判定数值对不对）：

```bash
# 离线重放：无网络、无凭据，回放已落盘的读模型响应
PYTHONPATH=src python3 -m ai_usage_widget.cli verify-cloud summary \
  --fixture-dir tests/fixtures/verify_cloud/healthy

# 在线只读：凭据只从环境变量读，只发只读请求
export AI_USAGE_READ_TOKEN=...
PYTHONPATH=src python3 -m ai_usage_widget.cli verify-cloud limits \
  --base-url https://aiusage.chunbai.com --period today
```

四个只读子命令：`summary`（周期用量关键口径）、`limits`（额度窗口逐条标注
official / confidence / status）、`health`（各来源最后上报时间、新鲜度、覆盖范围、
准确性）、`parity`（比对 `/api/summary` 与 `/api/mobile/summary` 的口径）。
加 `--json` 输出机器可判定结构。

退出码有语义，可直接进 CI：`0` 核对通过、`3` 数据异常（额度降级 / 来源掉线 /
用量归属不完整）、`4` 两端口径不一致、`5` 取数失败。

它证明的是**数据正确**，不证明**用户看得到**：Mac Popover / iPhone / Watch 的
界面验收不能用它替代。

离线 fixture 采集 official limits（只打印，不落任何本地库——PM-2，云端 D1 是唯一正本）：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --provider-fixture tests/fixtures/limits_runtime_fixture.json
```

使用本地 limits config 采集 official limits：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --limits-config config/limits.local.json
```

只检查 limits config 并输出脱敏 provider plan：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --limits-config config/limits.local.json \
  --check-config
```

真实 smoke 前做本机 readiness 诊断，不读取 auth 内容：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --limits-config config/limits.local.json \
  --doctor
```

`config/limits.local.json` 支持同一 provider 的多个账号实例。为每个实例设置稳定的 `source_id`，云端 D1 会用它区分账号，避免两个 Claude 账号互相覆盖。Claude CLI provider 会先解析 `/usage` 文本；如果当前 Claude Code 只返回订阅说明，会回退读取同一配置目录下的 `active_limits.json` 当前额度 cache；如果 cache 也不存在，会执行一个极短 probe 来解析 session limit reset 文本，此时只生成 session window，不推断 weekly window。第二个 Claude Code 配置目录可以通过脱敏的 `env` map 表达，例如：

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
  --codex-auth-file /path/to/codex/auth.json
```

显式指定 Codex app-server RPC 采集 rate limits：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --provider codex \
  --codex-rpc \
  --codex-rpc-sock /path/to/codex-app-server.sock
```

显式指定 Claude auth 文件和 Usage API URL 采集 OAuth usage：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --provider claude \
  --claude-auth-file /path/to/claude/auth.json \
  --claude-usage-url https://example.invalid/claude/usage
```

显式指定 Claude CLI `/usage` 采集 usage：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits \
  --provider claude \
  --claude-cli
```

> `sync-widget` 与 `collect --sync-widget` 已于 #72 移除。它们把 `latest.json` 同步进
> macOS WidgetKit extension 容器，而 macOS Widget 已非产品目标（见 `docs/status.md`）。
> 历史资料在 `docs/archive/legacy/widget-macos.md`。

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

- [AGENTS.md](./AGENTS.md)：每次会话自动读取的最小硬规则和文档路由。
- [project-map.md](./docs/project-map.md)：项目地图、文档索引、客户端当前/目标目录映射。
- [status.md](./docs/status.md)：当前阶段、有效决策和下一步。
- [architecture/architecture.md](./docs/architecture/architecture.md)：当前真实架构、模块 owner 和禁止事项。
- [architecture/database.md](./docs/architecture/database.md)：当前 Cloudflare D1 / 本地 SQLite 边界和表结构索引。
- [architecture/interfaces.md](./docs/architecture/interfaces.md)：当前 HTTP / summary / mobile 接口索引。
- [product-brief.md](./docs/product-brief.md)：产品定位、能力域、阶段边界和关键技术决策。
- [archive/INDEX.md](./docs/archive/INDEX.md)：历史设计稿和 review 记录索引。
- [operations-python-server.md](./docs/archive/legacy/operations-python-server.md)：已删除的 Python Ingest 服务端历史运维文档（#74 归档）。
- [schedulers.md](./docs/schedulers.md)：各平台终端定时任务配置文档。
- [subscription-usage-source.md](./docs/subscription-usage-source.md)：limits/quota 数据源方向。

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

`latest.json` 现在只属于 legacy/local compatibility。当前 Web、iPhone、Watch 和 macOS 菜单栏优先读取 Cloudflare API 或派生摘要，不再把本地快照文件作为生产事实源。
