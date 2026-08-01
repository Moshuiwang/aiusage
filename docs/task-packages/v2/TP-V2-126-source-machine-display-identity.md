# TP-V2-126 Source Machine Display Identity

Version: V2
ID: TP-V2-126
Status: done
Type: implementation
Depends on: TP-V2-103
Parallel with: TP-V2-122, TP-V2-123, TP-V2-124, TP-V2-125

## Goal

来源卡片始终展示真实采集机器名，网络 host 配置错误或与机器名不同时不能冒充设备身份。

## Context

2026-08-01 线上发现 `tz-wangzp` 和 `tz-wangzhipeng` 的 facts 均正确属于机器 `tz`，但两份旧配置的 host 误写成 MacBook。Native read model 优先展示 host，导致 TZ 来源卡片显示成 MacBook。

## Scope

- Dashboard source status 同时返回 machine 与 host。
- 用户可见 display_name 和 Mobile source machine 优先使用 machine。
- host 继续作为独立网络元数据保留。
- 不改事实、总量或历史 source report。

## Out of Scope

- 不直接编辑生产账户配置。
- 不直接修 D1 历史行。
- 不把 machine 与网络 host 强制设为相同。

## Red Test

- 当 source identity 的 host 与 machine 不同时，Dashboard 和 Mobile 必须展示 machine。
- 响应仍保留独立 host 字段供诊断。

## Implementation

1. Read model 明确输出 machine 与 host。
2. display_name 使用 machine + OS user。
3. Mobile 沿用 machine-first 合同。

## Acceptance Criteria

- 两个 TZ 来源卡片显示 `tz`，不再显示 MacBook。
- mac-local 仍显示本机机器名。
- 线上事实总量和 source_id 不变。
- 回归测试覆盖 host/machine 不一致场景。

## Verification

```bash
npx vitest run cloudflare/native-worker/test/web_surface.test.ts
git diff --check
```

## Handoff

- 回报生产 Dashboard/Mobile 两个 TZ source 的 machine/host，以及 D1 事实总量未变证据。
