# TP-V2-020 Limits Snapshot API

Version: V2
ID: TP-V2-020
Status: done
Type: implementation
Depends on: TP-V2-017, TP-V2-018, TP-V2-019
Parallel with: none

## Goal

把 canonical store 中的 official limits facts 输出到 `latest.json` 和 `/api/summary` 的 `limits` 字段。

## Context

展示层只读快照/API，不直接调用 Claude/Codex provider。缺失 limits 时 baseline usage dashboard 必须保持可用。

## Scope

- Snapshot builder 查询 `limit_windows`。
- 输出 `limits` 数组。
- stale / failed / missing 状态保留。
- API summary 返回相同字段。

## Out of Scope

- 不做 limits 视觉实现。
- 不调用真实 provider。
- 不改变 usage summary 计算。

## Red Test

- 无 `limit_windows` 表或无数据时，`limits: []` 合法。
- 有 observed limits 时输出 provider/window/reset_at。
- failed/stale limits 不破坏 usage summary。

## Implementation

- 扩展 snapshot builder。
- 新增 fixture DB 或 temp DB tests。
- 保持旧 Widget decode 兼容。

## Acceptance Criteria

- `limits` 缺失/为空不破坏 Dashboard。
- observed limits 字段完整。
- `/api/summary` 返回 `limits`。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_snapshot_builder tests.test_web_server -v
rg -n "\"limits\"|limit_windows|reset_at" src tests widget docs
```

## Handoff

- 汇报 snapshot `limits` shape。
- 汇报兼容性结果。
- 汇报未做的 UI 部分。
