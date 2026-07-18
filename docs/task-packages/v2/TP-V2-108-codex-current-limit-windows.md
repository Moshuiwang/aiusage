# TP-V2-108 Codex Current Limit Windows

Version: V2
ID: TP-V2-108
Status: in_progress
Type: implementation
Depends on: TP-V2-107
Parallel with: none

## Goal

Mac Popover 只展示当前可验证的 Codex 官方额度窗口，并让用户看见真实窗口名称、来源、更新时间和不可用状态。

## Context

GitHub Issue #25 / Epic #29 要求停止把上游 `primary` 固定解释为旧 5h 概念。Codex 官方返回可能缺少窗口、改变字段或只返回可验证的周窗口；这些情况不能沿用旧数字或估算。

## Scope

- Codex WHAM / app-server RPC 解析兼容缺失、字段变化和未知窗口。
- 仅保留具有官方百分比、重置时间、窗口时长和观测时间的窗口。
- Mac Popover 使用实际窗口时长生成名称，并展示官方来源与更新时间。
- 过期或不可验证时展示“暂不可用”，不展示旧百分比。
- 允许修改 Codex provider、mobile summary 合同、macOS Core/App 与对应测试/fixture。

## Out of Scope

- 不读取凭据值，不修改生产数据。
- 不安装或启动 Mac App。
- 不使用 daily、blocks、旧缓存或本地估算补额度。
- 不改 Input / Output / Cache token 口径和 iPhone 趋势。

## Red Test

- 先写 Codex 缺少旧 primary、未知窗口、字段变化与过期观测的失败测试。
- 先写 Mac 动态窗口名称、来源/更新时间和暂不可用降级的失败测试。

## Implementation

1. 解析上游实际窗口时长，不再硬编码 `primary = session/5h`。
2. 缺失或无法验证的窗口跳过；全部不可验证时向客户端保留安全的不可用状态与最后可信更新时间。
3. Mac 卡片根据窗口实际时长显示名称、百分比、重置时间、来源和更新时间。
4. 对旧缓存、过期观测和未知字段 fail closed。

## Acceptance Criteria

- 已取消或无法验证的 Codex 5h 窗口不显示。
- 仍显示的名称、比例和重置时间来自当前官方状态。
- 用户能看到来源和最近更新时间。
- 字段变化、断连或过期时显示“暂不可用”，不沿用错误数字。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_codex_limits_provider tests.test_codex_wham_adapter tests.test_codex_app_server_rpc_adapter tests.test_mobile_summary -v
npm run cf:native:test -- --run
swift test --package-path clients/macos
```

## Handoff

- 回报红绿测试、最终 head SHA、PR checks 和 Issue #25 单一证据评论。
- Mac 安装/启动与真实截图留到 Epic #29 人类检查点之后。
