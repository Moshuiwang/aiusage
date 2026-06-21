# TP-V1-002 Runner Fake Executor Boundary

Version: V1
ID: TP-V1-002
Status: ready
Type: implementation
Depends on: TP-V1-001
Parallel with: none

## Goal

让 runner 支持 fake executor，测试不再调用真实 shell 或 SSH。

## Context

runner 是采集边界，必须能在测试中模拟成功、失败、timeout 和 stderr。

## Scope

- `src/ai_usage_widget/runners.py`
- runner tests

## Out of Scope

- 不改 normalizer。
- 不改 collector orchestration。
- 不执行真实 SSH。

## Red Test

- fake local command ok。
- fake local exit code failed。
- fake timeout。
- stderr/message 截断。
- ssh command 组装但不连接远端。

## Implementation

- 抽象 command executor。
- runner 接受 executor 注入。
- `CommandResult` 保持结构化字段。

## Acceptance Criteria

- runner 单测全部使用 fake executor。
- command failure 有稳定 `error_type`。
- timeout 有稳定 `error_type`。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报 fake executor API。
- 汇报没有访问网络的证据。
