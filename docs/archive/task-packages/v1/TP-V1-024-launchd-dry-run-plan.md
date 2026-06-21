# TP-V1-024 Launchd Dry-run Plan

Version: V1
ID: TP-V1-024
Status: ready
Type: implementation
Depends on: TP-V1-011
Parallel with: TP-V1-025

## Goal

设计定时采集安装流程，并提供 dry-run。

## Context

定时任务不能默认修改用户系统状态。

## Scope

- launchd plist generator or docs
- tests using temp path

## Out of Scope

- 不自动安装 launchd。
- 不修改生产账户文件。

## Red Test

- plist render。
- dry-run path。
- invalid config path。
- no write outside temp dir。

## Implementation

- 生成 plist。
- 提供 dry-run 输出。

## Acceptance Criteria

- 用户明确执行前不加载 launchd。
- plist command 可审查。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报 dry-run 示例。
