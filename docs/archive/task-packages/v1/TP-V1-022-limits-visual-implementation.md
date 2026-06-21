# TP-V1-022 Limits Visual Implementation

Version: V1
ID: TP-V1-022
Status: ready
Type: implementation
Depends on: TP-V1-019, TP-V1-021
Parallel with: none

## Goal

有 limits 时显示 5h / week 进度和 reset time。

## Context

limits visual 必须区分 observed、estimated、stale、missing。

## Scope

- Swift core view model
- SwiftUI views
- Swift tests

## Out of Scope

- 不实现 limits 采集。
- 不把 estimated 写成官方额度。

## Red Test

- observed strong display。
- estimated weak display。
- stale shows observed_at。
- missing fallback baseline。

## Implementation

- 将 limits 映射成 progress rows。
- 根据 confidence/status 调整展示。

## Acceptance Criteria

- missing limits 不占用主 UI。
- estimated 文案明确。

## Verification

```bash
cd widget/macos
swift test
```

## Handoff

- 汇报 confidence 到 UI 的映射。
