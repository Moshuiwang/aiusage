# TP-V1-021 Baseline Visual Implementation

Version: V1
ID: TP-V1-021
Status: ready
Type: implementation
Depends on: TP-V1-020
Parallel with: none

## Goal

实现真实数据支撑的 baseline Widget UI。

## Context

baseline UI 展示 today usage、source health 和 group totals，不显示 mock limits。

## Scope

- SwiftUI views
- Swift tests or view state tests

## Out of Scope

- 不接 limits visual。
- 不做复杂趋势图。

## Red Test

- today data state。
- no today data state。
- source failed state。
- missing snapshot state。

## Implementation

- 调整 medium/large UI。
- 增加 small family if needed by IA。

## Acceptance Criteria

- UI 不显示 mock quota。
- 采集失败显式可见。

## Verification

```bash
cd widget/macos
swift test
```

## Handoff

- 汇报截图或预览验证方式。
