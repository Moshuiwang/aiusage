# TP-V2-094 Live 入口影子写（forward-fill）

Status: done (实现已验收；部署+启用由 ops 执行)
Milestone: Cloudflare 迁移 M4 forward-fill（见 `docs/architecture/cloudflare-migration-objective.md`）
依赖：staging Native 已部署

## Goal

让 `aiusage-api` 代理在把 `/ingest`、`/ingest-limits` 转发给 VPN2 的同时，**异步**把同一请求影子转发到 staging Native（写 prod D1），用真实设备 push 前向填充 D1。**主响应仍来自 VPN2，影子失败绝不影响用户。**

## Context

这是迁移中**第一处改动 live 入口**。设计为完全可逆 + 失败隔离：
- 可逆：清空 `SHADOW_INGEST_URL` env 即停；或重部署当前 proxy。
- 隔离：影子用 `ctx.waitUntil` fire-and-forget，吞掉所有错误，不阻塞、不改变 VPN2 主响应。

## Scope

- 改 `cloudflare/aiusage-api-worker.js`：对 `POST /ingest`、`/ingest-limits`，body 读一次；正常转发 VPN2 取主响应返回；同时 `ctx.waitUntil` 异步把相同 method / headers（含 `Authorization`）/ body 发到 `env.SHADOW_INGEST_URL`。
- gating：`env.SHADOW_INGEST_URL` 未设则不影子（默认关，安全）。
- 其它路径与所有 GET 行为不变。
- 测试（vitest）：主响应来自 VPN2；影子确实打到 `SHADOW_INGEST_URL`；影子失败不影响主响应；未设 env 时不影子。

## Out of Scope

- 不切流：route 不变，`aiusage.chunbai.com` 仍由 proxy 服务，主响应仍来自 VPN2。
- 不改 Native worker；不 `git add`/`commit`。

## Acceptance Criteria

- 测试绿；主路径零回归。
- 行为可逆（清 `SHADOW_INGEST_URL` 即停）。

## Verification

测试输出；部署后观察 prod D1 是否随设备 push 增长。

## Rollback

清空 `SHADOW_INGEST_URL`，或重部署当前 proxy 版本。

## Handoff

报告：实现、测试结果、部署与 env 设置建议（`SHADOW_INGEST_URL=https://aiusage-native-staging.chunbai.workers.dev`）。
