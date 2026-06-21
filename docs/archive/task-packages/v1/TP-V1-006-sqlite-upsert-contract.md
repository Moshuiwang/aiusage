# TP-V1-006 SQLite Upsert Contract

Version: V1
ID: TP-V1-006
Status: ready
Type: implementation
Depends on: TP-V1-003
Parallel with: TP-V1-005

## Goal

把 SQLite canonical store 的建表、迁移和 upsert 行为固定下来。

## Context

SQLite 是本机事实库，不是服务端数据库。测试必须使用临时 DB。

## Scope

- `src/ai_usage_widget/storage_sqlite.py`
- SQLite tests

## Out of Scope

- 不写真实 `data/usage.sqlite`。
- 不新增 limits 表。

## Red Test

- temp SQLite 建表。
- 同一 source/date/agent 重复 upsert。
- model breakdown upsert。
- collection_runs 写入。
- source_reports 写入。

## Implementation

- 明确 migration。
- 明确 primary key。
- 保留 first_seen_at 和 last_seen_at。

## Acceptance Criteria

- 重复采集不产生重复 daily rows。
- model breakdown key 稳定。
- 测试不依赖真实数据。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报表结构和主键口径。
