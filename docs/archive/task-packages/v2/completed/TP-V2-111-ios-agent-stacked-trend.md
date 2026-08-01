# TP-V2-111 iOS Agent Stacked Trend

Version: V2
ID: TP-V2-111
Status: done
Type: implementation
Depends on: TP-V2-110
Parallel with: none

## Goal

让日、周、月及全部趋势按 Claude、Codex、unknown 守恒堆叠，颜色、图例和 Tooltip 语义一致。

## Context

Issue #26 要求用户能一眼比较两家来源；底层 snapshot 已有按 bucket 的 `trend.by_agent`，但移动端
summary 当前丢弃该构成。

## Scope

- Python 与 Native Worker mobile summary 为每个点输出 Claude/Codex/unknown tokens。
- 未识别 agent 归入 unknown，不静默归给 Claude 或 Codex。
- Swift 解码兼容旧缓存缺失字段，SwiftUI 使用稳定三色堆叠、图例和分段 Tooltip。
- 每个点三段之和必须等于 `tokens`。

## Out of Scope

- 不按具体模型拆分。
- 不修改 Usage Ledger token 口径或生产数据。
- 不把 unknown 猜测为已知来源。

## Red Test

先写单来源为零、两来源并存、unknown 和逐点守恒的 Python/Worker/Swift 失败测试；旧 mobile
summary 不含分段字段，测试必须失败。

## Implementation

1. 按 trend axis 对齐 `by_agent.values`，规范化 Claude/Codex，其余为 unknown。
2. Python 与 Native Worker 保持同一 JSON 合同。
3. Swift point 解码新增兼容字段，图表改为堆叠柱与三色图例。
4. Tooltip 显示 Claude、Codex、unknown 与合计精确值。

## Acceptance Criteria

- 每个 bucket 的 Claude + Codex + unknown 等于总量。
- 单来源为零时另一段和总量正常；unknown 明确可见。
- 日、周、月颜色与图例一致，Tooltip 可核对各段与合计。
- Python、Native Worker、Swift 合同和非空模拟器 fixture 通过。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_snapshot_builder tests.test_mobile_summary tests.test_api_contract -v
npm run cf:native:test -- --run
swift test --package-path mobile/ios
python3 -m unittest tests.test_ios_xcode_integration -v
git diff --check
```

## Handoff

- 回报分段守恒红绿测试、模拟器截图、PR/CI 与 Review 证据。
