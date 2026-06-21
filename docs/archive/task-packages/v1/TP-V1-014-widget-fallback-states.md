# TP-V1-014 Widget Fallback States

Version: V1
ID: TP-V1-014
Status: ready
Type: implementation
Depends on: TP-V1-013
Parallel with: none

## Goal

Widget core 明确缺失、损坏、过期、今日无数据、部分 source 失败的状态。

## Context

Widget 不能把采集失败显示成 0 usage。

## Scope

- Swift core load/view state
- Swift tests

## Out of Scope

- 不做最终视觉。
- 不触发 collector。

## Red Test

- missing snapshot。
- unreadable snapshot。
- stale snapshot。
- no today data。
- partial source failure。

## Implementation

- 增加 view state mapping。
- UI 层根据 view state 展示。

## Acceptance Criteria

- 每种状态都有可测试映射。
- failed source 不被吞掉。

## Verification

```bash
cd widget/macos
swift test
```

## Handoff

- 汇报状态枚举。
