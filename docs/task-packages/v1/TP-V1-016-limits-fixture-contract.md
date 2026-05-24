# TP-V1-016 Limits Fixture Contract

Version: V1
ID: TP-V1-016
Status: ready
Type: contract
Depends on: TP-V1-007
Parallel with: none

## Goal

定义 limits/quota 结构化输入 fixture。

## Context

没有可信来源前，只能用 fixture 设计 parser 和 snapshot 行为。

## Scope

- `tests/fixtures/active_limits_sample.json`
- limits parser tests
- docs/subscription-usage-source.md if needed

## Out of Scope

- 不读取真实 `~/.claude` 或 `~/.codex`。
- 不执行 `ccusage blocks`。

## Red Test

- observed window。
- estimated window。
- stale window。
- missing status。
- unsupported shape。

## Implementation

- 添加 fixture。
- 添加 parser contract test。

## Acceptance Criteria

- 每个 limit fact 有 source_type、confidence、observed_at、status。
- estimated 和 observed 可区分。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报 fixture 字段。
