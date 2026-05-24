# TP-V1-011 CLI Check Report

Version: V1
ID: TP-V1-011
Status: ready
Type: implementation
Depends on: TP-V1-008, TP-V1-010
Parallel with: none

## Goal

提供 CLI 工程排查入口，检查 config、snapshot 和 source health。

## Context

后续 launchd 和 Widget 问题都需要一个不依赖 UI 的排查命令。

## Scope

- `src/ai_usage_widget/cli.py`
- CLI tests

## Out of Scope

- 不触发真实采集，除非用户运行 collect。
- 不读取生产配置。

## Red Test

- temp config check。
- temp latest report。
- missing snapshot。
- invalid snapshot。

## Implementation

- 增加 `check` 或 `report` 子命令。
- 输出简短 source health 和 schema version。

## Acceptance Criteria

- CLI report 可用于排查。
- 测试全部用 temp path。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报命令示例和测试输出摘要。
