# TP-V1-003 Usage Normalizer Contract

Version: V1
ID: TP-V1-003
Status: ready
Type: implementation
Depends on: none
Parallel with: TP-V1-001

## Goal

固化 `ccusage daily --json` 到内部 usage fact 的映射。

## Context

daily usage 是 baseline。normalizer 只能解析输入，不执行命令、不写文件。

## Scope

- `src/ai_usage_widget/normalize.py`
- `src/ai_usage_widget/models.py`
- `tests/fixtures/*daily*.json`
- normalizer tests

## Out of Scope

- 不改 runner。
- 不改 SQLite。
- 不推断 quota/reset。

## Red Test

- normal daily。
- missing total，使用分项求和。
- unknown agent 保留为 `unknown` 或当前明确口径。
- malformed JSON。
- unsupported shape。

## Implementation

- 明确必填字段和默认值。
- 输出稳定 usage fact。
- unsupported shape 返回结构化错误。

## Acceptance Criteria

- token 分项和 total 可重复计算。
- model breakdown 保留。
- normalizer 无副作用。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报 fixture 覆盖范围。
- 汇报 agent 字段口径。
