# TP-V1-008 Snapshot Builder Extraction

Version: V1
ID: TP-V1-008
Status: ready
Type: implementation
Depends on: TP-V1-007
Parallel with: none

## Goal

从 collector 中抽出 snapshot builder，生成 versioned display snapshot。

## Context

collector 负责采集编排，snapshot builder 负责展示聚合。

## Scope

- 新增或调整 snapshot builder module
- `src/ai_usage_widget/collector.py`
- snapshot builder tests

## Out of Scope

- 不改 Widget UI。
- 不接 limits。

## Red Test

- 给定 usage facts 和 source status，生成 v1 snapshot。
- summary date 使用指定 timezone。
- groups 按 total 降序。
- items 保留兼容字段。

## Implementation

- builder 接收 facts、status、generated_at、timezone。
- collector 调用 builder。

## Acceptance Criteria

- collector 不再手写全部 snapshot shape。
- v1 fixture contract 通过。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报 builder API。
