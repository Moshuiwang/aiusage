# TP-V1-018 Limits Canonical Storage

Version: V1
ID: TP-V1-018
Status: ready
Type: implementation
Depends on: TP-V1-016, TP-V1-006
Parallel with: none

## Goal

将 limit windows 写入 SQLite canonical store。

## Context

limits 是事实数据扩展，应与 usage facts 一样可重放、可 upsert。

## Scope

- SQLite migration
- limit_windows writer
- SQLite tests

## Out of Scope

- 不做 Widget 展示。
- 不做远程 limits source。

## Red Test

- 建立 limit_windows 表。
- upsert same source/agent/window。
- confidence/status/observed_at 写入。
- stale record 更新。

## Implementation

- 增加 migration。
- 增加 limits upsert function。

## Acceptance Criteria

- limits 缺失不影响 usage 表。
- upsert key 稳定。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报表结构和 key。
