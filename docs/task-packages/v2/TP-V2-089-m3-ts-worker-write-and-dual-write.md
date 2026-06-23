# TP-V2-089 M3 TS Worker 写入 + 双写

Status: done
Milestone: Cloudflare 迁移 M3（见 `docs/architecture/cloudflare-migration-objective.md`）
依赖：TP-V2-087（D1 schema）、TP-V2-088（TS 只读 API）

## Goal

TS Worker 实现写入路径 `/ingest`、`/ingest-limits` 写 D1，并建立 **VPN2 ↔ D1 影子写**：真实设备 push 经统一入口时，主响应仍来自 VPN2，同时异步写一份进 D1，保证切流前 D1 已是热数据、且随时可比可退。

## Context

写入是整个迁移最敏感处：幂等 upsert key 必须与 `storage_sqlite.py` 完全一致，否则会重复计数或漏更新。统一入口本来就过 Worker，所以**影子写选在 Worker 层**（转发 VPN2 拿主响应 + 异步写 D1），是改动最小、最易回退的方案。

## Scope

- TS 实现 `/ingest`、`/ingest-limits` 的 payload 校验（对齐 `ingest.py` 与 `server_services.validate_limits_ingest_payload`）与写 D1（对齐 `storage_sqlite.py` 的主键、`ON CONFLICT DO UPDATE` 幂等语义）。
- 影子写：Worker 转发请求到 VPN2 取主响应返回客户端；同一 payload 异步写入 D1；写 D1 失败不影响主响应，但要可观测（计数/日志，不含敏感内容）。
- 幂等测试：同一 source/date/agent 重复 push，D1 结果与 SQLite 一致。
- 写后读 parity：写入后 D1 经 M2 的只读 API 输出与老后端一致（复用 M0 golden 口径）。
- 一键开关：可关闭 D1 影子写，回退到纯 VPN2。
- **写入量最小化（M1 额度发现）**：D1 Free 上限 100,000 row-writes/day，M1 估算「每 30 分钟全量重灌」≈ 99,840/day（贴顶）。影子写必须只 upsert 值有变化的行（delta），不每次重灌历史；并核算每日写行数须显著低于上限。依据 `docs/architecture/d1-schema-quota-import-plan.md`。

## Out of Scope

- 本里程碑只做**本地可测的写入实现**（写 D1 + 幂等 + 写量最小化 + 写后读 value parity）。与 VPN2 的真实 dual-write 接线（统一入口转发 + 异步写）在 M4/M5 部署时完成，因为它需要线上入口和生产 D1。
- 不切流（主响应仍来自 VPN2，M5 才切）。
- 不导历史数据（M4）。
- 不改设备采集 / pusher 逻辑。

## Red Test

先写幂等 + 写后读 parity 测试跑红，再实现写入与影子写转绿。

## Acceptance Criteria

- 写入幂等与口径与 SQLite 一致。
- 影子写可观测、可比对、可一键关闭回退。
- 写 D1 失败不影响用户主响应。
- 每日 billable write rows 显著低于 D1 Free 的 100,000/day（delta upsert 生效）。

## Verification

幂等/parity 测试输出；影子写计数与 VPN2↔D1 比对。

## Handoff

报告：写入实现、幂等结果、影子写机制与开关、对 M4（历史数据导入）的建议。不要 `git add` / `commit`。
