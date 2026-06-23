# TP-V2-095 WAF 拦截 ingest 真实 payload — 诊断 + 范围跳过

Status: in_progress
Milestone: Cloudflare 迁移 M4 阻塞项（见 `docs/architecture/cloudflare-migration-objective.md`）

## Goal

定位 WAF 命中的具体规则，并对 `/ingest`、`/ingest-limits` 加**范围跳过**，使真实设备 payload 能到达后端。

## Context（关键诊断）

真实 ccusage payload 被 WAF 以 **403** 拦截，在两层都发生：
- Cloudflare（`aiusage.chunbai.com` zone 与 `aiusage-native-staging.chunbai.workers.dev`，`cf-ray` 证实）。
- 阿里 Caddy（`vpn2.chunbai.com:8443`，`server: Caddy`）。

token / auth / 代码均正常：同一 token 下 **reads → 200**，**minimal body POST /ingest → 400**（到达 app），**real payload → 403**（边缘拦截）。pusher 把 403 误报为 `http_auth_failed`，所以日志看起来像鉴权问题。这是**当前生产 ingest 故障**（设备数据没在落库）**+ 迁移数据步阻塞**。

## Scope

- ops 拉 Cloudflare WAF / security events，定位命中 `/ingest` 的具体 managed rule（规则 ID / 描述）。
- ops 在 `chunbai.com` zone 加 **skip** 规则：表达式命中 `/ingest`、`/ingest-limits`（POST），action = skip 托管 WAF（最小放松，仅这两条 token 鉴权路径）。
- 排查 `workers.dev`（aiusage-native-staging）是否有独立保护（Bot Fight Mode 等）导致 Native 403；如有，记录并给方案（例如把 Native 放到 zone 子域而非 workers.dev，或调整设置）。
- 阿里 Caddy WAF（当前路径）cutover 后退役；如需在 cutover 前恢复当前上报，另议（需阿里机器访问，属升级项）。

## Acceptance Criteria

- 加 skip 后，真实 payload POST 到 `aiusage.chunbai.com/ingest` 不再被 Cloudflare WAF 403（到达 origin/worker）。
- 记录：命中的规则 + 所加 skip 规则 + workers.dev 保护情况。

## Verification

WAF 事件日志；skip 后由 Claude 用真实 pusher 复测。

## Handoff

报告：命中规则、所加 skip、workers.dev 保护情况、复测建议。不输出任何密钥。
