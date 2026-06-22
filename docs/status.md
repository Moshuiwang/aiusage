# Status

## 当前阶段

项目已完成个人 HTTP push 架构的基础部署，并完成 official limits provider MVP 的离线可测基线、runtime wiring、Codex WHAM 显式 auth adapter、Claude OAuth 显式 auth adapter、Codex app-server RPC adapter、Claude CLI `/usage` adapter、limits 本地配置契约、limits doctor readiness、limits dry-run、config-only check、scheduler 模板、真实 smoke handoff、V2 索引状态对齐、V2 backlog 入口清理、Antigravity limits fixture parser baseline、移动端 Web 原型、移动端只读 summary API contract、iOS SwiftUI shell Swift Package、iOS Widget summary content views、Xcode iPhone App / Widget extension 集成、物理 iPhone 签名安装、iOS App Icon 资产接入、SwiftUI 内部页面原型结构对齐、模拟器内周期选择、趋势详情、明细 drilldown 和深浅色外观验证、模拟器只读 live `/api/mobile/summary` 数据接入、模拟器 today / week / month / all live 周期数据口径修正，以及生产 `https://aiusage.chunbai.com` 移动端 summary API 部署。

有效决策：

- 产品方向：个人使用的多设备 AI usage 观测数据产品。
- 采集方向：各终端在自己的 OS 用户上下文运行 `ccusage`，主动 push 结构化 usage payload 到个人 HTTP server。
- 展示方向：Web dashboard 继续作为完整查看入口；客户端按 `clients/` 分层推进。iPhone App + iOS Widget 是已落地方向；macOS 下一步只做菜单栏或轻量桌面入口，不回到 macOS Widget 主线；Windows 走托盘或轻量桌面入口；Android 复用移动端摘要合同。
- 客户端设计方向：iPhone App 信息架构和手机尺寸可交互原型已收敛；Swift Package 已固定 DTO、view model 和可复用视图；Xcode App / Widget extension target 已生成；Personal Team 签名、物理 iPhone 安装和 AppIcon 资产均已打通；SwiftUI App 内部页面已从系统 List 占位改为原型结构，并在模拟器内补齐周期选择、趋势点详情、Breakdown row 明细卡和随系统深浅色表现。当前 iPhone App 已配置到生产 `https://aiusage.chunbai.com`，today / week / month / all 切换会重新请求生产对应 period 并同步 UI 状态；真机首次安装验收走本地 `ai-usage-first-install` skill。
- 工程顺序：HTTP ingest、终端 pusher、canonical store / snapshot、Web dashboard 已形成 baseline；official limits contract、Codex / Claude offline provider parser、limits store、snapshot/API、Web 展示、`collect-limits` fixture runtime、Codex WHAM 显式 auth adapter、Claude OAuth 显式 auth adapter、Codex app-server RPC adapter、Claude CLI `/usage` adapter、limits 本地配置契约、doctor readiness、dry-run、config-only check、scheduler 模板、真实 smoke handoff、V2 索引状态对齐、V2 backlog 入口清理和 Antigravity limits fixture parser baseline 已形成 baseline。
- 任务入口：`docs/task-packages/README.md` + `docs/task-packages/v2/INDEX.md`；跨端客户端下一步应从 `docs/project-map.md` 的客户端目录边界和 `clients/` 目标目录开始，单独开包做 iOS 配置 UX、macOS 菜单栏、Windows 托盘或 Android App，不混在同一个实现任务里。
- 执行规则：所有开发任务必须 TDD。
- limits 原则：历史 token / session logs 只做统计，不参与官方 reset time 计算。
- Codex provider 决策：参考 CodexBar 源码，后台采集采用 OAuth/WHAM usage 优先，`codex app-server` RPC `account/rateLimits/read` fallback。
- Claude provider 决策：OAuth Usage API 优先，Claude CLI `/usage` fallback。

## 下一步

下一步按既有 ready 任务包继续：

- App 工程：下一步把 simulator env 真实数据配置演进为 App 内 server/token 设置、Keychain 保存、连接状态提示，并继续保持只读展示和 fixture fallback。
- 客户端架构：如要推进 macOS、Windows 或 Android，先新建对应任务包，目标落点分别是 `clients/macos`、`clients/windows`、`clients/android`；不要直接复用 legacy macOS Widget 路线。
- 工程延续：准备本机 `config/limits.local.json` 后执行真实命令 smoke、Antigravity real LS reader、或提交/PR 整理。

## 注意

- 不要把任务细节重新写回本文件。
- V1 任务包代表旧的 SSH pull / Widget-first 方向；新开发默认不要从 V1 继续执行。
- 既有 macOS Widget 文档和任务包只作为历史/兼容资料；不要再把 macOS Widget 当成后续产品交付目标。
