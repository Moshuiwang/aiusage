# TP-V2-113 Loop Conditional PR Merge

Version: V2
ID: TP-V2-113
Status: done
Type: implementation
Depends on: none
Parallel with: TP-V2-112

## Goal

让 Loop Execution Plan v2 可以显式选择由 Executor 合并 PR，同时保持默认人工合并，并确保
只有最新 head 的验证、独立 Review 和 CI 全部通过且没有未解决 P0/P1 时才允许合并。

## Context

Loop Executor v2.1.0 固定禁止自行合并 PR。用户已明确要求在 Plan #31 的目标内开放条件合并，
但该能力必须是 Plan 逐项选择的安全能力，不能改变其他 Plan 的默认行为。

## Scope

- 为 Plan v2 合同增加机器可读的 `authorization.merge_pr` 枚举。
- 支持 `manual` 与 `when_no_open_p0_p1` 两种模式，缺省按 `manual` 处理。
- 更新 Planner 与 Executor 的版本说明、门禁、合并前置条件和 closeout 流程。
- 用 Plan digest、Issue contract digests 和 approver 权限绑定批准内容与身份。
- 更新 Loop Executor 的界面元数据。
- 新增合同测试，固定默认拒绝和条件合并的安全边界。
- 新增可执行表驱动 merge gate，缺字段或任一安全条件不满足时 fail closed。

## Out of Scope

- 不自动批准 Plan revision。
- 不弱化 TDD、Review、CI、high-risk 人类检查点或外部写入门禁。
- 不允许 force push、直接 push 默认分支、绕过分支规则或在 P0/P1 未关闭时合并。
- 不在本任务中实际合并任何 PR。

## Red Test

先新增 `tests/test_loop_engineering_contract.py` 并运行：

```bash
PYTHONPATH=src python3 -m unittest tests.test_loop_engineering_contract -v
PYTHONPATH=src python3 -m unittest tests.test_loop_merge_gate -v
```

测试必须先因合同和 Executor 尚未提供 `authorization.merge_pr` 及安全合并条件而失败。

## Implementation

1. 在 Plan 合同中增加枚举和缺省行为，并说明版本兼容性。
2. 在 Planner 中要求检查并写入明确的 merge 模式。
3. 在 Executor 中保持 `manual` 默认；仅在 `when_no_open_p0_p1` 且最终证据同 SHA 时合并。
4. 合并前再次回读 PR head、Review findings、CI 和 mergeability；结果不确定时停止。
5. 用 expected head OID 执行获批 merge method；任何 head 变化使 high-risk 放行失效。
6. 合并后核对原 head、merged 状态和 immutable merge commit，再执行既有 closeout。

## Acceptance Criteria

- 未声明或声明 `manual` 的 Plan 仍禁止 Executor 合并。
- `when_no_open_p0_p1` 不会跳过最终验证、独立 Review、CI 或 high-risk 人类检查点。
- 合并前所有最终证据必须指向 PR 最新 head，且不存在未解决 P0/P1。
- 合并冲突、head 变化、检查缺失或结果不确定时停止，不盲目重试。
- 批准评论绑定 Plan digest、全部必做 Issue 正文 digest 和有 admin/maintain/owner 权限的 approver。
- risk、forbidden、验收/验证正文或任何执行门禁变化都会使旧批准失效并要求新 revision。
- Planner 不代替人类批准新 revision。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_loop_engineering_contract -v
PYTHONPATH=src python3 -m unittest tests.test_loop_merge_gate -v
python3 /Users/wangzhipeng/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/loop-executor
python3 /Users/wangzhipeng/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/loop-planner
git diff --check
```

## Handoff

- 汇报新增 merge 模式、默认行为和所有合并门槛。
- 汇报 Red Test 与最终验证结果。
- Plan #31 的具体授权必须通过 Loop Planner 形成新 revision，并由人类明确批准。
