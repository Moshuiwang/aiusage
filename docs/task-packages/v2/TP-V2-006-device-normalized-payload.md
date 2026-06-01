# TP-V2-006 Device Normalized Payload

Version: V2
ID: TP-V2-006
Status: ready
Type: implementation
Depends on: TP-V2-001, TP-V2-005
Parallel with: TP-V2-003

## Goal

把终端侧 `ccusage daily --json` 输出转换成 HTTP ingest payload。

## Context

daily token baseline 仍来自 `ccusage daily --json --timezone <tz>`。变化点是采集发生在各终端本机，输出被包装成结构化 payload 后 push。

## Scope

- 复用或扩展现有 daily normalizer。
- 添加 payload builder。
- 添加 ccusage fixture 到 ingest payload fixture 的 contract test。

## Out of Scope

- 不推断官方 quota。
- 不解析 `.claude`、`.codex` 原始日志。
- 不做 server store。
- 不做 Web dashboard。

## Red Test

- ccusage fixture 生成包含 source metadata 的 ingest payload。
- timezone 显式写入 payload。
- agent 缺失时记录为 `unknown`，不猜测。
- malformed ccusage JSON 返回 `invalid_json`。

## Implementation

- normalizer 只解析输入，不执行命令。
- payload builder 合并 device config metadata 和 normalized daily facts。
- payload 不包含原始日志路径。

## Acceptance Criteria

- payload 符合 TP-V2-001 contract。
- token totals 与 fixture 一致。
- 错误模型与 source health 对齐。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
rg -n "ccusage|timezone|unknown|invalid_json" tests src docs/task-packages/v2
```

## Handoff

- 汇报输入 fixture 和输出 fixture。
- 汇报 agent fallback 行为。
- 明确未实现 limits/quota。
