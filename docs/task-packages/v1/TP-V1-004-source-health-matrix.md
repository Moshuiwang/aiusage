# TP-V1-004 Source Health Matrix

Version: V1
ID: TP-V1-004
Status: ready
Type: implementation
Depends on: TP-V1-002, TP-V1-003
Parallel with: none

## Goal

collector 对每个 source 输出稳定 source health，部分失败不破坏成功数据。

## Context

UI 必须区分“今日 0 用量”和“采集失败”。

## Scope

- `src/ai_usage_widget/collector.py`
- collector tests

## Out of Scope

- 不改 Widget UI。
- 不引入 limits。
- 不改变 SQLite schema，除非测试暴露必须同步。

## Red Test

- source ok。
- source disabled。
- command failed。
- timeout。
- invalid JSON。
- unsupported shape。
- partial_failed 仍写成功 items。

## Implementation

- 标准化 source status。
- collector 继续处理后续 source。
- run status 按 ok / failed / partial_failed 汇总。

## Acceptance Criteria

- 每个 enabled source 都有 status。
- 失败 source 有 error_type。
- 成功 source 数据不被失败 source 丢弃。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报 failure matrix 测试表。
