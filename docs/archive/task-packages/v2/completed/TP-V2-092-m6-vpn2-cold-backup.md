# TP-V2-092 M6 VPN2 转冷备 + 7 天观察

Status: draft
Milestone: Cloudflare 迁移 M6（见 `docs/architecture/cloudflare-migration-objective.md`）
依赖：TP-V2-091（切流）

## Goal

VPN2 停止承载线上流量、转**长期冷备**（不物理下线，保留数据与可启动状态作回退）。`aiusage.chunbai.com` 所有入口连续 **7 天**正常、无人工干预、无降级 → 达成北极星。

## Context

M6 是北极星的关停验收。冷备＝随时可回退的安全网，不删 VPN2 数据。

## Scope

- 经运维 codex：停 VPN2 回源 / 流量；保留其数据与可重启状态。
- 7 天观察期：监控 Dashboard / iPhone / Watch / macOS 入口与设备 push；记录任何事故或人工干预。
- 维护说明：冷备如何保活、如何在需要时一键回退。

## Out of Scope

- 不物理下线 VPN2。

## Acceptance Criteria

- 连续 7 天 0 事故、0 人工干预。
- VPN2 处冷备且可回退。

## Verification

7 天观察记录。

## Handoff

北极星达成报告；冷备维护与回退说明。
