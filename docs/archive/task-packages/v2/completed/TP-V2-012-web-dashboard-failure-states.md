# TP-V2-012 Web Dashboard Failure States

Version: V2
ID: TP-V2-012
Status: done
Type: implementation
Depends on: TP-V2-011
Parallel with: none

## Goal

完善 Web dashboard 的缺失、失败、stale、空数据状态。

## Context

产品必须避免把采集失败显示成 0 usage。主动 push 架构尤其需要清楚表达设备最后一次上报时间。

## Scope

- 展示 empty、partial_failed、stale、never_seen。
- 展示最近错误摘要。
- 添加 UI 状态 fixture 和测试。

## Out of Scope

- 不做通知。
- 不做自动修复。
- 不暴露完整 stderr 或 payload。

## Red Test

- 部分 source 失败时，总量仍展示成功 source，失败 source 单独显示。
- never_seen source 不显示成今日 0。
- 错误 message 被截断。

## Implementation

- 使用 source status 驱动状态，不从 usage items 反推。
- 错误摘要限制长度。
- 空态和 0 usage 视觉区分。

## Acceptance Criteria

- 用户能判断是没用量、没上报还是上报失败。
- 不泄露敏感路径、token、原始 usage。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
rg -n "partial_failed|never_seen|stale|error" tests src
```

## Handoff

- 汇报状态列表。
- 汇报错误脱敏策略。
- 汇报未覆盖的视觉验证。
