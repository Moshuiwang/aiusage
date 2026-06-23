# TP-V2-091 M5 切流到 Native Worker

Status: draft
Milestone: Cloudflare 迁移 M5（见 `docs/architecture/cloudflare-migration-objective.md`）
依赖：TP-V2-090（数据导入 + 基线）

## Goal

把 `aiusage.chunbai.com` 后端从「代理回源 VPN2」切到「D1-backed Native Worker」。切后用 macOS popover 截图 + 字段级 API 比对，与 M4 基线一致才放行（上传、展示都对）；保留一键切回代理的回退路径。

## Context

M5 最敏感但可逆：切回代理只是改一个路由/配置。账号操作经 `cloud-flare` 运维 codex：部署 Native worker、配 Secrets（**会话密钥沿用**以保登录态无感；ingest/api token；Claude 不读明文）、改 route。

## Scope

- 经运维 codex：部署 Native worker、配置 Secrets、把 `aiusage.chunbai.com/*` 切到 Native（代理 worker 保留可快速切回）。
- **禁止在生产设置 `AIUSAGE_NOW`**：它只是测试用固定时钟 seam；生产必须用真实当前时间，否则 stale / 短窗口过滤会错。
- 设备 `/ingest`、`/ingest-limits` 主路径改为直写 D1（影子写转正）。
- 切后验收（DoD）：popover 截图 + 字段级 API 比对与 M4 基线一致；Dashboard 登录/静态/summary 正常；真实设备 push 成功；iPhone/Watch/macOS 不退化。
- 回退演练：确认能一键切回代理 + VPN2。

## Out of Scope

- 不下线 VPN2（M6 转冷备）。

## Acceptance Criteria

- 切后 popover 与基线一致（上传 + 展示都正确）。
- DoD 全部勾选。
- 回退路径已演练可用。

## Verification

切后 popover 截图比对；线上 smoke；回退演练记录。

## Handoff

报告：切流结果、DoD 勾选、回退方式、对 M6 的建议。不要 `git add` / `commit`。
