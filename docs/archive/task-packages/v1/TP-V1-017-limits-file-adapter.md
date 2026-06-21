# TP-V1-017 Limits File Adapter

Version: V1
ID: TP-V1-017
Status: ready
Type: implementation
Depends on: TP-V1-016
Parallel with: none

## Goal

读取明确配置的结构化 limits 文件。

## Context

limits source 只能读取设计过的 JSON 文件，不读取原始日志目录。

## Scope

- new limits adapter module
- config extension if required
- tests with temp files

## Out of Scope

- 不改 daily usage runner。
- 不接远程真实路径。

## Red Test

- file exists and valid。
- missing file。
- invalid JSON。
- stale observed_at。
- unsupported shape。

## Implementation

- 读取配置路径。
- 返回 structured limit facts or source status error。

## Acceptance Criteria

- 不递归读取目录。
- 缺失 limits 不影响 usage pipeline。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报 adapter 输入和输出。
