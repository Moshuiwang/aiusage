# TP-V1-026 Packaging Signing

Version: V1
ID: TP-V1-026
Status: ready
Type: operations
Depends on: TP-V1-023
Parallel with: none

## Goal

梳理真实 macOS App 发布、bundle id 和签名路径。

## Context

Debug build 可用后，才进入发布工程化。

## Scope

- `widget/macos-xcode/project.yml`
- signing docs
- build verification

## Out of Scope

- 不提交证书。
- 不处理 App Store 发布。

## Red Test

- 先定义构建配置检查清单。
- 如可自动化，测试 bundle id、entitlements、App Group 设置。

## Implementation

- 固定 Debug build 配置。
- 补发布文档。

## Acceptance Criteria

- 本机 Debug build 可重复。
- 签名要求清楚，不泄露证书。

## Verification

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

- 汇报 build 命令和签名注意事项。
