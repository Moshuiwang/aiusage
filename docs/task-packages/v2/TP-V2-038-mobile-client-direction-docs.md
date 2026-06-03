# TP-V2-038 Mobile Client Direction Docs

Version: V2
ID: TP-V2-038
Status: done
Type: documentation
Depends on: none
Parallel with: none

## Goal

把下一阶段客户端方向从 legacy macOS Widget 收敛为 iPhone App + iOS Widget，并新增移动端设计 brief 作为后续 prototype 和 iOS 实现任务入口。

## Context

V2 的采集、canonical store、Web dashboard、official limits baseline 和 doctor readiness 已完成。既有 macOS Widget 仍可作为历史兼容和 snapshot decode 参考，但不应继续作为后续产品交付目标。

## Scope

- 新增 `docs/mobile-app-design-brief.md`。
- 更新 `README.md`、`docs/product-brief.md`、`docs/architecture.md`、`docs/status.md` 和 `docs/task-plan.md` 的客户端方向。
- 更新 V2 索引的 next candidate 和 agent 分配说明。

## Out of Scope

- 不实现 Web prototype。
- 不创建 iOS SwiftUI / WidgetKit target。
- 不修改 server API 或 snapshot schema。
- 不删除 legacy macOS Widget 代码。

## Red Test

- 修改前 `rg -n "iPhone App|iOS Widget|mobile-app-design-brief|legacy macOS" README.md docs/product-brief.md docs/architecture.md docs/status.md docs/task-plan.md docs/task-packages/v2/INDEX.md docs/mobile-app-design-brief.md` 应缺少统一方向。

## Implementation

- 标记 macOS Widget 为 legacy / historical compatibility。
- 明确 iPhone App 负责完整查看和 drilldown，iOS Widget 负责 glanceable 摘要。
- 顺延后续任务包候选：TP-V2-039 prototype、TP-V2-040 API contract、TP-V2-041 SwiftUI shell。

## Acceptance Criteria

- 长期文档不再把 macOS Widget 当成后续产品目标。
- 移动端设计入口明确存在。
- 后续任务包编号不与 TP-V2-038 冲突。
- 不触碰实现代码和生成数据。

## Verification

```bash
rg -n "iPhone App|iOS Widget|mobile-app-design-brief|legacy macOS" README.md docs/product-brief.md docs/architecture.md docs/status.md docs/task-plan.md docs/task-packages/v2/INDEX.md docs/mobile-app-design-brief.md
rg -n "TP-V2-039-mobile-app-design-prototype|TP-V2-040-ios-api-contract|TP-V2-041-ios-swiftui-shell" docs/mobile-app-design-brief.md
git diff --check
```

## Handoff

- 汇报这是产品方向和设计入口文档收敛，不包含 prototype 或 iOS 实现。
