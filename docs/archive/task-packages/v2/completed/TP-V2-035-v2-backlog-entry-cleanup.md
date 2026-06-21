# TP-V2-035 V2 Backlog Entry Cleanup

Version: V2
ID: TP-V2-035
Status: done
Type: documentation
Depends on: TP-V2-034
Parallel with: none

## Goal

收敛 V2 任务入口的当前状态描述：避免 `README.md` 和 V2 索引继续暗示 TP-V2-001 是可执行任务，明确当前没有 `ready` 任务包。

## Context

TP-V2-034 已把 V2 任务列表从 TP-V2-001 到 TP-V2-034 全部对齐为 `done`。但 `docs/task-packages/README.md` 仍写着 first executable package 是 `TP-V2-001`，V2 索引顶部也保留旧的阶段性推荐顺序。

## Scope

- 更新 `docs/task-packages/README.md` 的当前可执行任务提示。
- 更新 `docs/task-packages/v2/INDEX.md` 的版本状态、当前执行状态和下一步候选。
- 更新 `docs/status.md` 的当前阶段描述。

## Out of Scope

- 不修改 V1 任务包。
- 不新增实现代码。
- 不执行真实 provider smoke。

## Red Test

- 修改前 stale 检查应命中 `First executable package` 或旧执行顺序文案。

## Implementation

- 将 V2 入口改为无当前 ready 任务。
- 把旧的线性执行顺序替换为已完成基线和下一步候选。
- 增加本任务包作为文档清理记录。

## Acceptance Criteria

- V2 任务入口不再把已完成任务显示为 first executable package。
- V2 索引明确当前没有 `ready` 任务包。
- 下一步候选只保留真实 smoke、Antigravity spike、提交 / PR 整理等需要新任务包的方向。

## Verification

```bash
rg -n 'First executable package: `TP-V2-001`|TP-V2-022 起|当前执行顺序' docs/task-packages/README.md docs/task-packages/v2/INDEX.md
rg -n "\| TP-V2-0[0-9]{2} .*\| (ready|in_progress|blocked|draft) \|" docs/task-packages/v2/INDEX.md
rg -n 'First executable package: none|当前没有 `ready` 任务包|TP-V2-035' docs/task-packages/README.md docs/task-packages/v2/INDEX.md docs/status.md
```

## Handoff

- 汇报这是任务入口文档清理，不包含实现改动。
