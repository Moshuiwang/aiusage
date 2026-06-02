# TP-V2-019 Limit Windows Store

Version: V2
ID: TP-V2-019
Status: ready
Type: implementation
Depends on: TP-V2-016
Parallel with: none

## Goal

在 SQLite canonical store 中保存 provider/window 级官方 limits facts。

## Context

当前 SQLite 只保存 daily usage facts。官方 limits provider 输出需要独立表，不能混进 usage_daily，也不能保存原始 provider token、cookie 或完整 API 响应。

## Scope

- 新增 `limit_windows` 表。
- 新增 upsert contract。
- 保存 provider、window、used_percent、remaining_percent、reset_at、window_duration_minutes、source_type、confidence、status、observed_at、first_seen_at、last_seen_at。

## Out of Scope

- 不实现 provider API。
- 不改 Dashboard UI。
- 不保存 secret 或原始响应。

## Red Test

- 同 provider/source/window 的重复写入 upsert 覆盖。
- `confidence` / `source_type` 保留。
- usage 表缺失时 limits 仍可写入。

## Implementation

- 扩展 SQLite schema 和 migration。
- 新增 `write_limit_windows` 或等价函数。
- 新增 temp SQLite tests。

## Acceptance Criteria

- `limit_windows` schema 有测试。
- upsert key 稳定。
- WAL / busy timeout 仍启用。
- 不写入任何 token/cookie 字段。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_limit_windows_store -v
rg -n "limit_windows|reset_at|source_type|confidence" src tests docs/architecture.md
```

## Handoff

- 汇报表结构。
- 汇报 upsert key。
- 汇报是否影响现有 usage tests。
