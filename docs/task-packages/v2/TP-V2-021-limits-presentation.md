# TP-V2-021 Limits Presentation

Version: V2
ID: TP-V2-021
Status: ready
Type: implementation
Depends on: TP-V2-020
Parallel with: none

## Goal

在 Web Dashboard 和可选 Widget 只读展示 observed limits，不展示 mock 或 estimated official reset。

## Context

limits UI 只能使用 snapshot/API 中已有 `limits` 字段。没有 observed limits 时降级到 daily usage baseline。

## Scope

- Web Dashboard 展示 Claude/Codex 的 5h / weekly window、used percent、reset time。
- Widget Swift decode 若缺字段保持兼容。
- 视觉上区分 observed / stale / failed / missing。

## Out of Scope

- 不调用 provider。
- 不读取本地 credentials。
- 不做 Antigravity UI。
- 不显示 estimated 为官方额度。

## Red Test

- `limits: []` 时 UI 不显示 mock quota。
- observed limits fixture 显示 percentage 和 reset。
- stale / failed limits 显示弱化状态。

## Implementation

- Web dashboard 从 `/api/summary` 的 `limits` 渲染。
- Swift core 扩展 decode（如需要）。
- 添加 JS fixture 或 Python HTML smoke test。

## Acceptance Criteria

- 无 limits 时 baseline 页面不变。
- Claude/Codex observed limits 可读。
- 文案不把 estimated / missing 说成官方额度。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_web_server -v
cd widget/macos && swift test
rg -n "quota|reset|limits|estimated|observed" src widget docs
```

## Handoff

- 汇报 UI 降级行为。
- 汇报 Swift decode 是否修改。
- 汇报未支持的 providers。
