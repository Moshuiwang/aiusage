# Task Packages V2

Version: V2
Status: ready

## 方向

V2 替代 V1 的 SSH pull / Widget-first 路线。

新方向是个人 HTTP push 架构：

```text
Device pusher -> HTTP ingest server -> SQLite canonical store -> Web dashboard / snapshot / Widget
```

## 当前执行顺序

先固化 ingest contract，再做终端 pusher，再接 store/snapshot，再做 Web dashboard，最后补 Widget 和官方 limits provider。

推荐顺序：

1. TP-V2-001 到 TP-V2-003：HTTP ingest baseline。
2. TP-V2-004 到 TP-V2-006：Device pusher baseline。
3. TP-V2-007 到 TP-V2-009：Canonical store and snapshot。
4. TP-V2-010 到 TP-V2-012：Web dashboard v1。
5. TP-V2-013 到 TP-V2-015：Operations and optional Widget.
6. TP-V2-016 到 TP-V2-021：Official limits provider MVP.
7. TP-V2-022 起：Production hardening.

## 任务列表

| ID | 文件 | 状态 | 依赖 | 可并行 |
| --- | --- | --- | --- | --- |
| TP-V2-001 | [TP-V2-001-http-ingest-contract.md](TP-V2-001-http-ingest-contract.md) | ready | none | TP-V2-004 |
| TP-V2-002 | [TP-V2-002-ingest-auth-and-errors.md](TP-V2-002-ingest-auth-and-errors.md) | ready | TP-V2-001 | none |
| TP-V2-003 | [TP-V2-003-ingest-idempotent-upsert.md](TP-V2-003-ingest-idempotent-upsert.md) | ready | TP-V2-001 | TP-V2-006 |
| TP-V2-004 | [TP-V2-004-device-config-contract.md](TP-V2-004-device-config-contract.md) | ready | none | TP-V2-001 |
| TP-V2-005 | [TP-V2-005-device-pusher-fake-http.md](TP-V2-005-device-pusher-fake-http.md) | ready | TP-V2-004 | none |
| TP-V2-006 | [TP-V2-006-device-normalized-payload.md](TP-V2-006-device-normalized-payload.md) | ready | TP-V2-001, TP-V2-005 | TP-V2-003 |
| TP-V2-007 | [TP-V2-007-server-sqlite-schema.md](TP-V2-007-server-sqlite-schema.md) | ready | TP-V2-003 | none |
| TP-V2-008 | [TP-V2-008-server-snapshot-builder.md](TP-V2-008-server-snapshot-builder.md) | ready | TP-V2-007 | none |
| TP-V2-009 | [TP-V2-009-source-staleness-health.md](TP-V2-009-source-staleness-health.md) | ready | TP-V2-007 | TP-V2-008 |
| TP-V2-010 | [TP-V2-010-web-api-summary.md](TP-V2-010-web-api-summary.md) | ready | TP-V2-008, TP-V2-009 | none |
| TP-V2-011 | [TP-V2-011-web-dashboard-baseline.md](TP-V2-011-web-dashboard-baseline.md) | ready | TP-V2-010 | none |
| TP-V2-012 | [TP-V2-012-web-dashboard-failure-states.md](TP-V2-012-web-dashboard-failure-states.md) | ready | TP-V2-011 | none |
| TP-V2-013 | [TP-V2-013-server-operations.md](TP-V2-013-server-operations.md) | ready | TP-V2-010 | TP-V2-014 |
| TP-V2-014 | [TP-V2-014-device-schedulers.md](TP-V2-014-device-schedulers.md) | ready | TP-V2-005 | TP-V2-013 |
| TP-V2-015 | [TP-V2-015-widget-optional-snapshot.md](TP-V2-015-widget-optional-snapshot.md) | ready | TP-V2-008 | none |
| TP-V2-016 | [TP-V2-016-official-limits-contract.md](TP-V2-016-official-limits-contract.md) | done | TP-V2-010 | none |
| TP-V2-017 | [TP-V2-017-codex-official-provider.md](TP-V2-017-codex-official-provider.md) | done | TP-V2-016 | none |
| TP-V2-018 | [TP-V2-018-claude-official-provider.md](TP-V2-018-claude-official-provider.md) | done | TP-V2-016 | none |
| TP-V2-019 | [TP-V2-019-limit-windows-store.md](TP-V2-019-limit-windows-store.md) | done | TP-V2-016 | none |
| TP-V2-020 | [TP-V2-020-limits-snapshot-api.md](TP-V2-020-limits-snapshot-api.md) | done | TP-V2-017, TP-V2-018, TP-V2-019 | none |
| TP-V2-021 | [TP-V2-021-limits-presentation.md](TP-V2-021-limits-presentation.md) | done | TP-V2-020 | none |
| TP-V2-022 | [TP-V2-022-production-hardening-baseline.md](TP-V2-022-production-hardening-baseline.md) | done | TP-V2-013, TP-V2-014 | none |
| TP-V2-023 | [TP-V2-023-health-and-bounded-backups.md](TP-V2-023-health-and-bounded-backups.md) | done | TP-V2-022 | none |
| TP-V2-024 | [TP-V2-024-official-limits-runtime-wiring.md](TP-V2-024-official-limits-runtime-wiring.md) | done | TP-V2-021 | none |
| TP-V2-025 | [TP-V2-025-codex-wham-auth-adapter.md](TP-V2-025-codex-wham-auth-adapter.md) | done | TP-V2-024 | none |
| TP-V2-026 | [TP-V2-026-claude-oauth-auth-adapter.md](TP-V2-026-claude-oauth-auth-adapter.md) | done | TP-V2-024 | none |
| TP-V2-027 | [TP-V2-027-codex-app-server-rpc-adapter.md](TP-V2-027-codex-app-server-rpc-adapter.md) | done | TP-V2-024 | none |
| TP-V2-028 | [TP-V2-028-claude-cli-usage-adapter.md](TP-V2-028-claude-cli-usage-adapter.md) | done | TP-V2-024 | none |
| TP-V2-029 | [TP-V2-029-limits-config-contract.md](TP-V2-029-limits-config-contract.md) | done | TP-V2-024 | none |
| TP-V2-030 | [TP-V2-030-limits-dry-run.md](TP-V2-030-limits-dry-run.md) | done | TP-V2-029 | none |
| TP-V2-031 | [TP-V2-031-limits-scheduler-templates.md](TP-V2-031-limits-scheduler-templates.md) | done | TP-V2-030 | none |

## subagent 分配建议

- Server agent：TP-V2-001 到 TP-V2-003、TP-V2-007 到 TP-V2-010、TP-V2-013。
- Device pusher agent：TP-V2-004 到 TP-V2-006、TP-V2-014。
- Web UI agent：TP-V2-010 到 TP-V2-012。
- Widget agent：TP-V2-015。
- Limits provider agent：TP-V2-016 到 TP-V2-020。
- Docs / QA agent：检查 V2 链接、验收记录和文档一致性，不改实现。
