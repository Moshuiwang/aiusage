# TP-V2-110 iOS Complete Period Trend

Version: V2
ID: TP-V2-110
Status: done
Type: implementation
Depends on: TP-V2-112
Parallel with: none

## Goal

让 iPhone 周、月、全部趋势完整表达所选周期，并在 Tooltip 中提供可核对的日期与精确 token 数。

## Context

Issue #21 已确认服务端周期总量和日点守恒，用户可见错误来自 iOS 图表无条件截取最后 24 点。

## Scope

- 用可测试的图表展示策略替换 `suffix(24)`。
- 周保留 7 日、月保留 30 日、全部保留完整日序列，首尾范围可见。
- Tooltip 同时显示日期、compact 值和带千分位精确值。
- 使用非空确定性 fixture 做 iOS 模拟器验收。

## Out of Scope

- 不修改 Input / Output / Cache 计数口径。
- 不修改生产数据或安装 iPhone 构建。
- 不改 Mac 额度窗口。

## Red Test

先为 7、30、76 个日点写失败测试，断言展示点数、首尾 bucket、总量守恒和精确 Tooltip；旧
`suffix(24)` 必须使 30/76 日用例失败。

## Implementation

1. 新增纯 Swift 图表展示/Tooltip helper，并让 SwiftUI 图表使用它。
2. 保留完整点序列，通过稀疏首/中/尾标签保证范围可见。
3. 保持拖动选点与原始 bucket 一一对应。

## Acceptance Criteria

- 周、月、全部分别覆盖 7、30、全部日点，不能静默丢日期。
- 展示点之和等于周期点之和，首尾日期可验证。
- 选中 Tooltip 显示对应日期和精确 token 数。
- iOS 模拟器以非空 fixture 展示周/月/全部和选中 Tooltip。

## Verification

```bash
swift test --package-path mobile/ios
PYTHONPATH=src python3 -m unittest tests.test_mobile_summary tests.test_api_contract -v
python3 -m unittest tests.test_ios_xcode_integration -v
git diff --check
```

## Handoff

- 回报 7/30/76 日红绿测试、模拟器截图、PR/CI 与 Review 证据。
