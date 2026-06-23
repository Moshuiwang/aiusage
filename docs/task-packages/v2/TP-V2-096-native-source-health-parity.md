# TP-V2-096 Native 采集健康(source_status)真实数据缺口修复

Status: done（真实端到端通过：根因是大 payload 逐行远程写 D1 超时导致尾部 source_report 漏写；改 D1 batch 后，直推真实数据 source_status 非空、幂等、VPN2/Native mac-local 口径逐项一致）
Milestone: Cloudflare 迁移 M4 阻塞项（切流前必修）

## Goal

让 Native read-model 生成 `source_status`（采集健康），对齐 Python `snapshot_source_health.build_source_status`；并补一个会产生 source health 的真实场景 parity 测试。

## Context（真实数据暴露的缺口）

真实 D1 数据下，Native `/api/summary` 返回 `source_status: []`（Python 非空），导致 `/api/mobile/summary` 的 `sources` 为空。`groups.by_machine` 有数据，但缺 `source_ids`/source health。M2 的 fixture parity 没抓到（seed 未构造出会触发 source health 的数据，两边都空就通过了）。这是 D2 Source Health 能力缺口。

## Scope

- 实现 Native `source_status` 生成：从 `collection_runs` + `source_reports` + `source_identities` 计算每个 source 的 status / 最近上报时间 / stale 判定，对齐 `snapshot_source_health.py` 与 `snapshot_builder.py` 中 source_status 的组装。
- `groups.by_machine` 补 `source_ids`（mobile `visible_source_ids` 依赖它）。
- `mobile_summary` 的 `sources` 由 source_status 派生，对齐 Python。
- 补 parity 测试：seed 构造含 `collection_runs`/`source_reports`/`source_identities`（含 ok + stale/失败场景），断言 Native source_status 与 Python value-golden 逐字段一致且**非空**。

## Out of Scope

- 不部署、不切流、不改 live proxy/wrangler.toml/Python src、不 commit。

## Acceptance Criteria

- 含 source health 的 seed 下，Native `source_status` 与 Python 一致且非空；`mobile.sources` 非空且一致。
- `pnpm run cf:native:test` 全绿；`PYTHONPATH=src python3 -m unittest discover -s tests` 不回归。

## Verification

测试输出。

## Handoff

报告：实现、parity 结果、对 cutover 的建议。
