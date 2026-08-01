# Task Packages（已归档，2026-08-01）

**任务包体系已整体停用。不要按本目录开展新工作。**

## 现在去哪里

任务状态的唯一真值是 GitHub：

- Issues：`gh issue list` / <https://github.com/Moshuiwang/aiusage/issues>
- Project #1 `AI Usage Delivery`：`gh project item-list 1 --owner Moshuiwang`
  （字段：`Status` / `Work type` / `证据等级` / `执行环境`）

新工作直接开 Issue，用产品语言描述用户结果，**不要再新增 `TP-V2-nnn` 编号**。
硬规则见仓库根 `AGENTS.md`。

## 历史资料

- 归档说明与原因：[v2/INDEX.md](v2/INDEX.md)
- 全部任务包索引（128 条）：[INDEX-done.md](../archive/task-packages/v2/INDEX-done.md)
- 任务包正文：`docs/archive/task-packages/v2/completed/`（120 个）、
  `docs/archive/task-packages/v2/cancelled/`（8 个）
- 原任务包规则与模板：[RULES.md](RULES.md)（历史，不再强制执行）

## 原规则中仍然有效的部分

这些已上收到 `AGENTS.md`，不再依赖本目录：

- 开发任务 TDD：先写失败测试并确认它因目标行为缺失而失败，再实现最小代码。
- 一个变更只改一个行为面；范围变大就停下报告，不擅自扩大。
- 不得为让测试通过而弱化断言、改预期值或缩小验收。
- 文档类改动必须有 grep / diff / 链接一致性等可执行验收。
- 收口必须报告：改了哪些文件、跑了哪些验证、哪些没跑及原因、是否越界。
