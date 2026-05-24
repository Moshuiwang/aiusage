# TP-V1-001 Config Schema Contract

Version: V1
ID: TP-V1-001
Status: ready
Type: implementation
Depends on: none
Parallel with: TP-V1-003

## Goal

为 sources config 定义最小 schema、版本号和结构化错误。

## Context

当前配置读取依赖隐式字典字段，后续 runner、collector 和 subagent 执行都需要稳定配置契约。

## Scope

- `src/ai_usage_widget/config.py`
- `config/sources.example.json`
- config fixtures and tests

## Out of Scope

- 不改 runner 执行。
- 不连接真实 SSH。
- 不读取 `config/sources.local.json`。

## Red Test

- valid local source。
- valid ssh source。
- valid file import source。
- missing timezone。
- duplicate source id。
- unknown source type。

## Implementation

- 增加 config schema version。
- 增加 source 必填字段校验。
- 返回或抛出结构化 config error。

## Acceptance Criteria

- invalid config 不进入 runner。
- duplicate source id 被拒绝。
- example config 与 schema 对齐。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报新增 fixture。
- 汇报失败测试如何变绿。
