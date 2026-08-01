---
name: tdd-task
description: ai-usage 的任务包与 TDD 执行规则。接到实现、修复、重构类开发任务时使用；也用于判断一个任务是否需要拆分、该写哪些红测、完成后要交付什么证据。
---

# 任务执行规则

完整规则见 `docs/task-packages/RULES.md`（Mac 侧 Codex 的真值，不要改它）。
本技能是 Claude Code 侧的操作要点。

## 开工前

1. 确认任务状态真值：`gh issue list`。**不要**以 `INDEX.md` 的状态列为准，它只是快照。
2. 活跃任务索引：`docs/task-packages/v2/INDEX.md`（13 条以内）。
   历史已完成项在 `docs/archive/task-packages/v2/INDEX-done.md`，**不要读它**，除非在查历史。
3. 只读自己这个任务包 + 它显式列出的参考文件。不要顺手读全部 `docs/*.md`，不要顺手做邻近任务。

## 原子性

**一个任务包只能改变一个行为面。** 需要同时改两个以上行为面就必须拆分。

- ✅ 合格：config schema 校验 / runner fake executor 边界 / snapshot summary 聚合 / Swift snapshot decode
- ❌ 不合格：「重构 collector 并改 Widget」/「把 UI 做完整」/「实现所有 limits 功能」

任务范围在执行中变大时**停下并报告**，不要擅自扩大。需要后续工作就新开编号，不在原任务包里膨胀。

## TDD：先红后绿

1. 先写失败测试或 contract fixture。
2. **实际运行确认它失败，且失败原因是目标行为缺失**（不是导入错误、路径写错）。
3. 写最小实现。
4. 跑任务包要求的最小测试。
5. 跨层影响时跑 `scripts/verify.sh` 全量。

**不允许**为了让测试通过而弱化断言、改预期值或缩小验收。
文档类任务可以不写代码测试，但必须有 grep / diff / 链接检查等可执行的文档验收。

新测试必须可离线 fixture 重放：纯标准库 `unittest`，无网络、无真实 `ccusage`/SSH/provider。

## 编号与状态

`TP-V<major>-<nnn>`，三位递增，**编号发布后不复用**。
废弃标 `superseded`，不删除。
允许状态：`draft` / `ready` / `in_progress` / `blocked` / `done` / `superseded`
（`completed` 不是合法值）。

## 收口交付

必须回报：

- 改了哪些文件
- 跑了哪些测试、结果如何（用 `scripts/verify.sh` 的输出）
- **哪些测试没跑，以及原因**（尤其是本机不可验证、需回 Mac 侧的项）
- 是否触碰了任务包之外的范围
- 是否需要新增后续任务包
- 当前证据等级（调用 `/verify` 对齐）

实现完成后收口前，用 `reviewer` subagent 在干净上下文审一遍 diff。

**没有用户明确要求，不得 `git add` / `git commit` / `git push`。**
