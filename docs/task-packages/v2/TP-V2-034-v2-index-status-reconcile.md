# TP-V2-034 V2 Index Status Reconcile

Version: V2
ID: TP-V2-034
Status: done
Type: documentation
Depends on: none
Parallel with: none

## Goal

对齐 V2 任务包状态：把已经由代码、测试和状态页证明完成的 TP-V2-001 到 TP-V2-015 从 `ready` 修正为 `done`，避免后续 agent 误从早期 baseline 重新执行。

## Context

`docs/status.md` 已说明 HTTP ingest、终端 pusher、canonical store / snapshot、Web dashboard、operations 和 optional Widget baseline 已形成；测试集中也覆盖 ingest、pusher、SQLite、snapshot、Web dashboard、backup、scheduler 文档和 Widget sync。V2 索引和任务包头仍保留旧的 `ready` 状态。

## Scope

- 更新 `docs/task-packages/v2/INDEX.md`。
- 更新 `docs/task-packages/v2/TP-V2-001` 到 `TP-V2-015` 文件头状态。
- 保留历史任务内容，不改实现。

## Out of Scope

- 不修改 V1 任务包。
- 不改代码。
- 不执行真实 provider smoke。

## Red Test

- `rg -n "Status: ready" docs/task-packages/v2/TP-V2-0{01..15}-*.md` 不应再返回早期 baseline 任务。
- V2 索引中 TP-V2-001 到 TP-V2-034 均应为 `done`。

## Implementation

- 机械更新早期任务状态。
- 补充本任务包作为状态清理记录。

## Acceptance Criteria

- V2 索引不再暗示 early baseline 仍可执行。
- 状态页和索引保持一致：下一步只剩真实 smoke、Antigravity spike 或新增任务。

## Verification

```bash
rg -n "Status: ready" docs/task-packages/v2/TP-V2-0{01..15}-*.md
rg -n "\| TP-V2-0(0[1-9]|1[0-5]) .*\| ready \|" docs/task-packages/v2/INDEX.md
rg -n "\| TP-V2-0[0-9]{2} .*\| (ready|in_progress|blocked|draft) \|" docs/task-packages/v2/INDEX.md
```

## Handoff

- 汇报这是文档状态对齐，不包含实现改动。
