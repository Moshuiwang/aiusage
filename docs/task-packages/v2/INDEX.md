# Task Packages V2（已归档）

Version: V2
Status: archived
归档日期: 2026-08-01

## 任务状态真值已迁出本仓库

**当前任务状态的唯一真值是 GitHub：**

- Issues：<https://github.com/Moshuiwang/aiusage/issues>（`gh issue list`）
- Project #1 `AI Usage Delivery`：<https://github.com/users/Moshuiwang/projects/1>
  （`gh project item-list 1 --owner Moshuiwang`）

Project 字段：`Status`（Backlog / Ready / In progress / Review / Waiting external / Done）、
`Work type`（Plan / Epic / Story / Fix）、`证据等级`（0–7）、`执行环境`（Linux 可做 / 必须 Mac /
必须 Ops / 需真机）。

**不要在本仓库内维护第二份进度表。** 新工作直接开 Issue，用产品语言描述用户结果，
不要再新增 `TP-V2-nnn` 编号。

## 为什么归档

2026-08-01 对账发现 V2 任务包体系已被现实超越：

- 13 条标为活跃的任务包中，`TP-V2-090/091/092`（Cloudflare 迁移 M4/M5/M6）的目标早已达成
  ——生产已是 Worker + D1，VPN2 已下线；`TP-V2-081/083/108/109/120` 已完成（文件头、
  已关闭 Issue #25/#27 或已合并 PR #53 为证）；`TP-V2-071/072` 被后续 PR 流程取代。
- `TP-V2-084/097/098` 经产品负责人确认不再执行。
- 任务包状态与索引状态列已经互相矛盾（例如 `TP-V2-081` 文件头为 `done` 但索引为
  `in_progress`），说明双轨维护不可持续。
- `TP-V2-120` 编号被两个任务包复用，违反原编号规则。

## 历史资料

- 已完成 / 已撤销索引：[INDEX-done.md](../../archive/task-packages/v2/INDEX-done.md)
- 任务包正文：`docs/archive/task-packages/v2/completed/`（120 个）、
  `docs/archive/task-packages/v2/cancelled/`（8 个）
- 任务包规则（历史）：[RULES.md](../RULES.md)

架构治理分轮流程同期归档，见 `docs/archive/architecture/governance-state.md`。
