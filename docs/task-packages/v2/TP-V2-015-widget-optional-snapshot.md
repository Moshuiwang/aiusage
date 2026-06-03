# TP-V2-015 Widget Optional Snapshot

Version: V2
ID: TP-V2-015
Status: done
Type: implementation
Depends on: TP-V2-008
Parallel with: none

## Goal

把 macOS Widget 调整为个人 server snapshot 的可选只读展示面。

## Context

V2 的主展示面是 Web dashboard。Widget 仍可作为 Mac 上的 glanceable view，但不再承担主产品入口。

## Scope

- Swift snapshot decode 兼容 V2 snapshot。
- Widget 展示 today total、source health 摘要、关键拆分。
- Widget 空态指向 server snapshot 缺失或过期。

## Out of Scope

- 不执行 pusher。
- 不调用 HTTP ingest。
- 不读取 SQLite。
- 不做完整 Web dashboard 功能。

## Red Test

- V2 snapshot fixture 可被 Swift core 解码。
- stale source 在 Widget health 摘要可见。
- snapshot 缺失时显示明确空态。

## Implementation

- 复用现有 Widget core。
- 保持 Widget 只读 snapshot。
- 需要同步 snapshot 时由 server 或 CLI 完成。

## Acceptance Criteria

- Widget 不依赖 SSH 或 ccusage。
- V2 snapshot 字段映射清楚。
- 缺失 limits 不影响 baseline 展示。

## Verification

```bash
cd widget/macos
swift test
```

```bash
cd widget/macos-xcode
xcodegen generate
xcodebuild -project AIUsageWidget.xcodeproj \
  -scheme AIUsageWidgetApp \
  -configuration Debug \
  -destination 'platform=macOS' \
  build
```

## Handoff

- 汇报 Swift 测试和构建结果。
- 汇报未跑的视觉验证。
- 汇报 snapshot fixture 路径。
