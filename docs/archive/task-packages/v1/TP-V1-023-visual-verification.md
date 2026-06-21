# TP-V1-023 Visual Verification

Version: V1
ID: TP-V1-023
Status: ready
Type: QA
Depends on: TP-V1-021
Parallel with: none

## Goal

验证 light/dark、foreground/background、small/medium/large 的 UI 状态。

## Context

视觉任务必须有明确验收清单，不能只靠主观描述。

## Scope

- Swift previews
- WidgetKit build
- docs/widget-macos.md if commands change

## Out of Scope

- 不新增业务字段。
- 不改 collector。

## Red Test

- 先定义手动/截图验收清单。
- 如有可自动化快照测试，先让缺失状态失败。

## Implementation

- 增加 preview states。
- 修正布局溢出。

## Acceptance Criteria

- small/medium/large 都能渲染。
- 文本不重叠。
- source failure 可见。

## Verification

```bash
cd widget/macos
swift test
cd ../macos-xcode
xcodegen generate
xcodebuild -project AIUsageWidget.xcodeproj \
  -scheme AIUsageWidgetApp \
  -configuration Debug \
  -destination 'platform=macOS' \
  build
```

## Handoff

- 汇报构建结果和视觉验收记录。
