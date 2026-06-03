# TP-V2-007 Server SQLite Schema

Version: V2
ID: TP-V2-007
Status: done
Type: implementation
Depends on: TP-V2-003
Parallel with: none

## Goal

让 HTTP ingest 后的 usage facts 和 source reports 写入 server SQLite canonical store。

## Context

SQLite 仍是 canonical store，但现在属于个人 HTTP server，而不是 Mac pull collector 的本地副产品。

## Scope

- 新增或调整 SQLite schema。
- 写入 usage facts、source reports、ingest runs。
- 使用临时 SQLite 跑测试。

## Out of Scope

- 不写生产 `data/usage.sqlite`。
- 不做 Web API。
- 不做 Widget 同步。
- 不做 limits 表，除非已有 schema 需要兼容。

## Red Test

- valid ingest payload 写入 usage fact。
- 重复 payload 触发 upsert，不新增重复行。
- source report 记录 observed_at、status、duration_ms。

## Implementation

- 表职责至少覆盖：
  - `ingest_runs`
  - `source_reports`
  - `usage_daily`
  - `usage_daily_models`
- 使用稳定 primary key 和 migration test。

## Acceptance Criteria

- 临时库测试可重复运行。
- 不触碰生产数据。
- upsert key 与 TP-V2-003 一致。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报 schema 变更。
- 汇报 upsert 行为。
- 汇报临时数据库路径策略。
