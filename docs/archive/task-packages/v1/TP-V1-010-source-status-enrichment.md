# TP-V1-010 Source Status Enrichment

Version: V1
ID: TP-V1-010
Status: ready
Type: implementation
Depends on: TP-V1-008
Parallel with: none

## Goal

source status 增加 observed_at、duration_ms 和非敏感错误摘要。

## Context

source health 是产品核心，错误要可排查但不能泄露敏感内容。

## Scope

- collector status building
- snapshot builder
- source status tests

## Out of Scope

- 不引入完整日志系统。
- 不输出完整 stderr。

## Red Test

- ok source 有 observed_at。
- failed source 有 error_type。
- message 截断。
- duration_ms 进入 status。

## Implementation

- 将 runner duration 映射到 status。
- 统一 message 截断长度。

## Acceptance Criteria

- `source_status` 可直接驱动 UI health。
- 不泄露完整 command output。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报错误字段和截断策略。
