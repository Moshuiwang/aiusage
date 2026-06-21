# TP-V1-012 Swift Snapshot V1 Decode

Version: V1
ID: TP-V1-012
Status: ready
Type: implementation
Depends on: TP-V1-007
Parallel with: TP-V1-013

## Goal

Swift core 能解码 `latest.json` v1。

## Context

Swift 侧必须跟 Python snapshot contract 对齐。

## Scope

- `widget/macos/Sources/AIUsageWidgetCore/*`
- Swift tests
- shared fixture copy or test fixture path

## Out of Scope

- 不改 Widget 视觉。
- 不接 limits UI。

## Red Test

- 解码 v1 fixture。
- summary/groups/source_status/limits 空数组可读。
- malformed JSON 返回 unreadable。

## Implementation

- 增加 Swift model。
- 保留 legacy snapshot 兼容策略或明确迁移。

## Acceptance Criteria

- Swift test 使用 fixture 通过。
- v1 字段命名与 Python 一致。

## Verification

```bash
cd widget/macos
swift test
```

## Handoff

- 汇报 Swift model 字段。
