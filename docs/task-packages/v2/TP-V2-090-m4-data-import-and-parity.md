# TP-V2-090 M4 历史数据导入 + 结果对比

Status: in_progress
Milestone: Cloudflare 迁移 M4（见 `docs/architecture/cloudflare-migration-objective.md`）
依赖：TP-V2-088（只读 parity）、TP-V2-089（写入 + 影子写）、TP-V2-087（导入计划）

## Goal

新建 production D1，按 M1 导入计划把 VPN2 SQLite 历史数据导入 D1，过**行数 + 抽样字段双重校验**；VPN2 与 D1-backed Native 的 API 逐项对齐；截一张切换前 macOS 菜单栏 popover 作为人眼验收基线。

## Context

M4 是「敢不敢切」的决策门。VPN2 冷备保证源数据不删，最坏可回退。账号操作（新建 D1、应用迁移、导入命令）经 `cloud-flare` 运维 codex；真实数据导入由 Claude 主导执行。影子写（M3）已让近期数据进 D1，本步补齐历史并解决重叠。

## 数据策略（访问现实下的修订）

运维 channel 只管 Cloudflare，**没有阿里/VPN2 文件系统访问**；Mac 侧也禁止 SSH-pull 远端原始数据。因此**不假设能拿到 VPN2 raw SQLite 导出**。

主路线 = **前向填充（forward-fill）**：`ccusage` 每次运行都返回全量历史，`/ingest` 幂等，所以 D1 可由正常设备 push（影子写）逐步填满当前全量历史，无需导出 VPN2 SQLite。完整性用 **API 级 parity**（VPN2 vs Native）验证，不需要原始行访问。

回退路线（仅当 API parity 暴露「已停用/退役 source 的历史」缺失时）：才需要 VPN2 SQLite 导出 —— 这需要阿里 box 访问，届时属于**人类决策/访问升级**点。

## 已决策

- 生产 D1 名称：**`aiusage-prod-db`**（与 dev 库 `aiusage-dev-db` 分离）。现有 `aiusage-api` 入口暂不动，仍代理 VPN2，直到 M5 切流。
- 生产 D1 **已创建**：`aiusage-prod-db`，id `be19e4de-4fa3-446c-8028-0d31ff0bb9f2`，已应用 `0001_initial_schema.sql`（13 张用户表）。
- 前置：Native worker 必须功能完整（含 web surface，见 TP-V2-093）才能 staging 部署与切流。
- Native worker **已部署 staging**：`https://aiusage-native-staging.chunbai.workers.dev`（绑 prod D1，已设 `AIUSAGE_TOKEN`，smoke 通过）。
- 前向填充机制：live 入口影子写，见 TP-V2-094。

## Scope

- 经运维 codex：新建 production D1 `aiusage-prod-db`（free），应用 `cloudflare/migrations/0001_initial_schema.sql`。
- 部署 Native worker（read+write）+ 配 Secrets（会话密钥沿用、ingest/api token；不读明文）+ 绑定 prod D1；在统一入口开启**影子写**（用户主响应仍走 VPN2，异步写 D1）。
- 前向填充：让 4 个活跃 source 至少各 push 一轮（等 30 分钟周期或手动触发）。
- API 级 parity：同请求打 VPN2（现入口）与 Native，`today/week/month/all` + machine/account filter 逐项一致（复用 M0/M2 口径）。
- 截切换前 macOS 菜单栏 popover 基线（存 `tmp/`，不提交）。
- 仅在 parity 暴露缺失时，才走 VPN2 SQLite 导出回退（升级）。

## Out of Scope

- 不切流（M5）。
- 不下线 / 不改 VPN2 现状（仍是主）。

## Acceptance Criteria

- 行数校验 + 抽样字段级校验全通过。
- VPN2 与 Native API 逐项一致。
- popover 切换前基线已截存。

## Verification

校验脚本输出；两边 API 比对报告；基线截图。

## Handoff

报告：导入结果、差异（应为空）、基线截图位置、对 M5（切流）的建议。不要 `git add` / `commit`。
