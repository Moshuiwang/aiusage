# TP-V1-019 Limits In Snapshot

Version: V1
ID: TP-V1-019
Status: ready
Type: implementation
Depends on: TP-V1-017, TP-V1-018
Parallel with: none

## Goal

snapshot 输出 `limits`，供 Widget 根据 confidence 展示或降级。

## Context

展示层不能自己推断 quota/reset。

## Scope

- snapshot builder
- snapshot fixture/tests

## Out of Scope

- 不改 Widget UI。
- 不把 estimated 当 observed。

## Red Test

- observed limits 进入 snapshot。
- estimated limits 保留 confidence。
- stale limits 保留 status。
- missing limits 输出空数组或明确降级。

## Implementation

- builder 接收 limits facts。
- 输出 `limits` 字段。

## Acceptance Criteria

- `limits` 缺失不破坏 baseline snapshot。
- UI 可根据 confidence 决策。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报 snapshot limits shape。
