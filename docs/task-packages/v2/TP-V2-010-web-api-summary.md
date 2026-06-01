# TP-V2-010 Web API Summary

Version: V2
ID: TP-V2-010
Status: ready
Type: implementation
Depends on: TP-V2-008, TP-V2-009
Parallel with: none

## Goal

为 Web dashboard 提供只读 summary API。

## Context

Web dashboard 是 V2 主要查看入口。API 只读 server store 或 snapshot，不执行采集，不触发 SSH。

## Scope

- 添加 summary endpoint 或 handler。
- 返回 today summary、group totals、source health。
- 添加 API contract tests。

## Out of Scope

- 不做登录 UI。
- 不做写入接口。
- 不做 limits。
- 不做复杂历史图表。

## Red Test

- 空 store 返回明确 empty state。
- 多 source store 返回 total tokens 和 source health。
- failed/stale source 出现在响应中。

## Implementation

- API 响应字段与 snapshot 尽量对齐。
- handler 可在测试中直接调用，不要求真实端口。
- 响应不包含原始 payload。

## Acceptance Criteria

- dashboard 可用一个 endpoint 画 baseline 页面。
- API 不触发 collector。
- 错误状态可直接展示。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
rg -n "dashboard|summary|source_health|stale" tests src docs/task-packages/v2
```

## Handoff

- 汇报 API 字段。
- 汇报 empty/failed/stale 响应样例。
- 标出前端依赖。
