# TP-V2-064 macOS Menu Bar Client

Version: V2
ID: TP-V2-064
Status: done
Type: implementation
Depends on: TP-V2-043
Parallel with: TP-V2-060, TP-V2-061

## Goal

新增 macOS 菜单栏轻入口，让用户从菜单栏查看当前 AI usage 摘要、额度窗口、采集健康和明细入口，同时安装后不再反复触发 `Documents` 访问弹窗。

## Context

V2 客户端统一消费 `/api/mobile/summary`。macOS 目标落点是 `clients/macos`，不继续推进 legacy macOS Widget。当前用户关心的是低资源占用、正常安装、菜单栏可见数据完整、不要每次提示访问文稿。

## Scope

- 在 `clients/macos` 下新增 macOS 菜单栏 App。
- App 只读 `/api/mobile/summary`，不执行 `ccusage`、SSH、collector、provider，不读 SQLite。
- 菜单栏弹窗展示 today / week / month / all、token 汇总、趋势、额度窗口、采集来源和 breakdown。
- 运行时配置和缓存只放在 `~/Library/Application Support/ai-usage-widget/macos-menu-bar`。
- 提供本机安装脚本，把 App 构建到用户可运行位置，避免运行时访问 `~/Documents/ai-usage-widget`。
- 保持 production token 和本地敏感配置不进入仓库。

## Out of Scope

- 不改采集口径。
- 不改生产账户文件。
- 不实现自动升级。
- 不迁移旧 macOS Widget。
- 不把 `ccusage daily`、`ccusage blocks` 或本地估算伪装成官方额度状态。

## Red Test

- Swift 单元测试先验证菜单栏 view model 能从 mobile summary fixture 产出菜单栏标题、健康、额度和明细行。
- Swift 单元测试先验证运行时路径不包含 `Documents`，默认配置落在 Application Support。
- Python 或 shell-level 安装测试先验证安装脚本/产物路径不把运行时缓存、配置或日志放入 `Documents`。

## Implementation

- 复用 mobile summary DTO 字段，必要时在 macOS 包内复制最小 Decodable 合同。
- 使用 AppKit `NSStatusItem` + SwiftUI popover，默认 10 分钟低频刷新，用户点击或手动刷新时再请求。
- 用 `URLSession` 请求 `/api/mobile/summary?period=<id>`，从环境或配置文件读取 server URL/token。
- 增加安装脚本，构建 release App 并默认安装到 `/Applications`，退出后可从 macOS「应用程序」重新打开；仍支持用户指定目录，运行时目录固定在 Application Support。
- 保留 Web dashboard 打开入口。

## Acceptance Criteria

- 菜单栏常驻占位小，不打开弹窗时不持续渲染复杂 UI。
- 打开菜单栏后能看到总 token、输入/输出/cache、趋势、额度、采集健康、来源、明细。
- 安装后 App 的配置、缓存、日志不在 `Documents` 下。
- App 不读取 legacy `data/latest.json`，不触发采集。
- 没有新增 token、SSH key、原始 usage 日志或生产配置入仓。

## Verification

```bash
cd clients/macos
swift test
swift build -c release
python3 scripts/install_menu_bar_app.py --dry-run
```

## Handoff

- 汇报改动文件、菜单栏用户体验、安装命令和验证命令。
- 说明未做自动升级。
