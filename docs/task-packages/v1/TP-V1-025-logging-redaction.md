# TP-V1-025 Logging Redaction

Version: V1
ID: TP-V1-025
Status: ready
Type: implementation
Depends on: TP-V1-002, TP-V1-004
Parallel with: TP-V1-024

## Goal

日志和错误摘要可排查，但不泄露敏感内容。

## Context

source failure 需要可诊断；同时不能输出 token、key、大段原始 usage 或完整私有路径。

## Scope

- logging/redaction helper
- runner/collector error summary
- tests

## Out of Scope

- 不引入重型 logging framework。
- 不保存 raw reports。

## Red Test

- stderr 截断。
- token-like string 脱敏。
- private path 脱敏或截断。
- message length limit。

## Implementation

- 增加 redaction helper。
- 统一错误 message 处理。

## Acceptance Criteria

- source status 可读。
- 敏感内容不进入 snapshot。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报脱敏规则。
