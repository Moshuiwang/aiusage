# TP-V2-122 Production Runtime Identity Contract

Version: V2
ID: TP-V2-122
Status: done
Type: implementation
Depends on: TP-V2-093
Parallel with: TP-V2-123

## Goal

让正式入口始终明确报告 production 身份，缺少部署配置时显示 unknown，不能再回退成 staging。

## Context

2026-08-01 线上核查发现 `aiusage.chunbai.com/api/health` 正常使用 production D1，但 `backend_mode` 仍固定返回 `native_d1_staging`，用户无法判断正式入口实际环境。

## Scope

- 为 Native Worker 增加显式 backend mode 配置。
- 健康接口、Web summary 和 mobile summary 复用同一部署身份。
- 缺少配置时 fail closed 为 unknown。
- 增加配置和接口回归测试。

## Out of Scope

- 不重命名现有 Worker、D1 或域名。
- 不修改 D1 数据。
- 不切换 Route 或 DNS。

## Red Test

- 正式配置必须声明 `native_d1_production`。
- `/api/health` 和 summary metadata 必须返回该值。
- 缺少配置时不得出现 `native_d1_staging`。

## Implementation

1. 在 Worker env 和 summary request 中传递显式 backend mode。
2. 统一使用 fail-closed fallback。
3. 在 production Wrangler 配置中固定 production 值。

## Acceptance Criteria

- 正式健康接口和用户摘要环境口径一致。
- 代码和生产配置不再把缺省值解释为 staging。
- 线上发布后带认证回读为 `native_d1_production`。

## Verification

```bash
npm run cf:native:test -- --run cloudflare/native-worker/test/web_surface.test.ts
npm run cf:native:test -- --run
git diff --check
```

## Handoff

- 回报本地红绿测试、Worker 版本、正式接口回读和未改 D1 的证据。
