# TP-V1-007 Snapshot V1 Fixture

Version: V1
ID: TP-V1-007
Status: ready
Type: contract
Depends on: TP-V1-004
Parallel with: none

## Goal

新增 `latest.json` v1 fixture 和 schema contract 测试。

## Context

后续 Python builder 和 Swift decode 都依赖同一份 snapshot contract。

## Scope

- `tests/fixtures/latest_v1_sample.json`
- Python schema/contract tests
- docs if schema text needs sync

## Out of Scope

- 不改生产 collector 输出。
- 不改 Swift。

## Red Test

- 读取 fixture。
- 断言 `schema_version`、`generated_at`、`timezone`、`summary`、`groups`、`items`、`source_status`。
- 空 `limits` 合法。
- legacy `items` 和 `source_status` 仍存在。

## Implementation

- 添加 fixture。
- 添加 contract test。

## Acceptance Criteria

- fixture 可作为 Python 和 Swift 共同输入。
- schema 缺字段测试会失败。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报 fixture 路径和字段口径。
