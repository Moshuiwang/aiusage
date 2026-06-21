# TP-V1-013 Swift Summary Mapping

Version: V1
ID: TP-V1-013
Status: ready
Type: implementation
Depends on: TP-V1-012
Parallel with: none

## Goal

Swift 展示 view model 直接使用 snapshot summary 和 groups。

## Context

聚合应尽量在 snapshot builder 完成，Swift 只做轻量映射。

## Scope

- Swift core summary/view model
- Swift tests

## Out of Scope

- 不改 SwiftUI 视觉布局。
- 不重新实现 Python 聚合规则。

## Red Test

- v1 snapshot 生成 view model。
- legacy snapshot 生成 fallback view model，或明确失败状态。
- today/timezone 不漂移。

## Implementation

- 调整 UsageSummaryBuilder。
- 映射 summary、groups、source health。

## Acceptance Criteria

- Widget 数据块来源清晰。
- 今日无数据状态稳定。

## Verification

```bash
cd widget/macos
swift test
```

## Handoff

- 汇报 legacy 兼容策略。
