> 本目录为已弃用路线（SSH pull / macOS Widget-first），已由 V2 HTTP push / mobile-first 取代，仅作历史追溯。

# Task Packages V1

Version: V1
Status: ready

## 当前执行顺序

先稳 baseline，再建 snapshot API，再改 Widget，再接 limits。

推荐顺序：

1. TP-V1-001 到 TP-V1-006：Baseline pipeline hardening。
2. TP-V1-007 到 TP-V1-011：Snapshot API v1。
3. TP-V1-012 到 TP-V1-015：Widget data contract。
4. TP-V1-016 到 TP-V1-019：Limits source。
5. TP-V1-020 到 TP-V1-023：Widget UI v1。
6. TP-V1-024 到 TP-V1-026：Operations。

## 任务列表

| ID | 文件 | 状态 | 依赖 | 可并行 |
| --- | --- | --- | --- | --- |
| TP-V1-001 | [TP-V1-001-config-schema-contract.md](TP-V1-001-config-schema-contract.md) | ready | none | TP-V1-003 |
| TP-V1-002 | [TP-V1-002-runner-fake-executor.md](TP-V1-002-runner-fake-executor.md) | ready | TP-V1-001 | none |
| TP-V1-003 | [TP-V1-003-usage-normalizer-contract.md](TP-V1-003-usage-normalizer-contract.md) | ready | none | TP-V1-001 |
| TP-V1-004 | [TP-V1-004-source-health-matrix.md](TP-V1-004-source-health-matrix.md) | ready | TP-V1-002, TP-V1-003 | none |
| TP-V1-005 | [TP-V1-005-atomic-json-writer.md](TP-V1-005-atomic-json-writer.md) | ready | none | TP-V1-006 |
| TP-V1-006 | [TP-V1-006-sqlite-upsert-contract.md](TP-V1-006-sqlite-upsert-contract.md) | ready | TP-V1-003 | TP-V1-005 |
| TP-V1-007 | [TP-V1-007-snapshot-v1-fixture.md](TP-V1-007-snapshot-v1-fixture.md) | ready | TP-V1-004 | none |
| TP-V1-008 | [TP-V1-008-snapshot-builder-extraction.md](TP-V1-008-snapshot-builder-extraction.md) | ready | TP-V1-007 | none |
| TP-V1-009 | [TP-V1-009-token-type-summary.md](TP-V1-009-token-type-summary.md) | ready | TP-V1-008 | none |
| TP-V1-010 | [TP-V1-010-source-status-enrichment.md](TP-V1-010-source-status-enrichment.md) | ready | TP-V1-008 | none |
| TP-V1-011 | [TP-V1-011-cli-check-report.md](TP-V1-011-cli-check-report.md) | ready | TP-V1-008, TP-V1-010 | none |
| TP-V1-012 | [TP-V1-012-swift-snapshot-v1-decode.md](TP-V1-012-swift-snapshot-v1-decode.md) | ready | TP-V1-007 | TP-V1-013 |
| TP-V1-013 | [TP-V1-013-swift-summary-mapping.md](TP-V1-013-swift-summary-mapping.md) | ready | TP-V1-012 | none |
| TP-V1-014 | [TP-V1-014-widget-fallback-states.md](TP-V1-014-widget-fallback-states.md) | ready | TP-V1-013 | none |
| TP-V1-015 | [TP-V1-015-app-group-snapshot-path.md](TP-V1-015-app-group-snapshot-path.md) | ready | TP-V1-005 | TP-V1-014 |
| TP-V1-016 | [TP-V1-016-limits-fixture-contract.md](TP-V1-016-limits-fixture-contract.md) | ready | TP-V1-007 | none |
| TP-V1-017 | [TP-V1-017-limits-file-adapter.md](TP-V1-017-limits-file-adapter.md) | ready | TP-V1-016 | none |
| TP-V1-018 | [TP-V1-018-limits-canonical-storage.md](TP-V1-018-limits-canonical-storage.md) | ready | TP-V1-016, TP-V1-006 | none |
| TP-V1-019 | [TP-V1-019-limits-in-snapshot.md](TP-V1-019-limits-in-snapshot.md) | ready | TP-V1-017, TP-V1-018 | none |
| TP-V1-020 | [TP-V1-020-widget-information-architecture.md](TP-V1-020-widget-information-architecture.md) | ready | TP-V1-014 | none |
| TP-V1-021 | [TP-V1-021-baseline-visual-implementation.md](TP-V1-021-baseline-visual-implementation.md) | ready | TP-V1-020 | none |
| TP-V1-022 | [TP-V1-022-limits-visual-implementation.md](TP-V1-022-limits-visual-implementation.md) | ready | TP-V1-019, TP-V1-021 | none |
| TP-V1-023 | [TP-V1-023-visual-verification.md](TP-V1-023-visual-verification.md) | ready | TP-V1-021 | none |
| TP-V1-024 | [TP-V1-024-launchd-dry-run-plan.md](TP-V1-024-launchd-dry-run-plan.md) | ready | TP-V1-011 | TP-V1-025 |
| TP-V1-025 | [TP-V1-025-logging-redaction.md](TP-V1-025-logging-redaction.md) | ready | TP-V1-002, TP-V1-004 | TP-V1-024 |
| TP-V1-026 | [TP-V1-026-packaging-signing.md](TP-V1-026-packaging-signing.md) | ready | TP-V1-023 | none |

## subagent 分配建议

- Python data pipeline agent：TP-V1-001 到 TP-V1-011、TP-V1-016 到 TP-V1-019、TP-V1-024、TP-V1-025。
- Swift Widget agent：TP-V1-012 到 TP-V1-015、TP-V1-020 到 TP-V1-023、TP-V1-026。
- Docs / QA agent：检查任务包状态、验收记录和文档链接，不改实现。
