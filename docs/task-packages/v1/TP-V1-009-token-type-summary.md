# TP-V1-009 Token Type Summary

Version: V1
ID: TP-V1-009
Status: ready
Type: implementation
Depends on: TP-V1-008
Parallel with: none

## Goal

snapshot summary 输出 token 类型汇总。

## Context

Widget 不应重复实现复杂聚合。

## Scope

- snapshot builder
- snapshot tests

## Out of Scope

- 不改 normalizer 字段来源。
- 不改 Swift UI。

## Red Test

- 多 source、多 agent、多日期 fixture。
- 只汇总今日 input/output/cache creation/cache read。
- total_tokens 与分项关系明确。

## Implementation

- 在 `summary` 中输出 token 分项。
- 只基于 snapshot date 聚合。

## Acceptance Criteria

- token type totals 可由 fixture 验证。
- 今日无数据时分项为 0。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报 summary 字段。
