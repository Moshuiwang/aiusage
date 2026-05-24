# TP-V1-020 Widget Information Architecture

Version: V1
ID: TP-V1-020
Status: ready
Type: implementation
Depends on: TP-V1-014
Parallel with: none

## Goal

固定 small / medium / large Widget 的信息密度。

## Context

UI 先承载真实 snapshot 字段，再靠近视觉设计稿。

## Scope

- Swift view model
- docs/display-options.md if needed
- Swift tests

## Out of Scope

- 不做最终视觉 polish。
- 不显示 mock quota。

## Red Test

- small family data blocks。
- medium family data blocks。
- large family data blocks。
- no limits fallback。

## Implementation

- 为每个 family 定义 view model。
- 选择 token、source、group、limits 数据块。

## Acceptance Criteria

- small 不依赖 limits。
- medium/large 有 baseline fallback。

## Verification

```bash
cd widget/macos
swift test
```

## Handoff

- 汇报每个 family 的信息块。
