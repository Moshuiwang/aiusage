# Task Package Rules

## 目的

任务包用于让 Codex 主线程或 subagent 独立执行一个原子任务。每个任务包必须自包含：读者只需要读取本规则、当前版本索引和指定任务包，就能知道该做什么、不能做什么、先跑什么测试、完成后交付什么。

## 参考来源

本规则吸收了这些公开实践：

- Basecamp Shape Up：[Write the Pitch](https://basecamp.com/shapeup/1.5-chapter-06) 和 [Set Boundaries](https://basecamp.com/shapeup/1.2-chapter-03) 强调先定边界、appetite、rabbit holes 和 no-gos，避免实现中失控。
- Atlassian：[acceptance criteria](https://www.atlassian.com/work-management/project-management/acceptance-criteria) 和 [Definition of Done](https://www.atlassian.com/agile/project-management/definition-of-done) 用于定义任务完成条件和团队通用完成标准。
- GitHub：[tasklists](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/about-tasklists) / sub-issues / [issue forms](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/configuring-issue-templates-for-your-repository) 适合把大任务拆成可追踪的小任务，并用结构化字段降低沟通成本。

## 编号规则

任务包 ID 格式：

```text
TP-V<major>-<nnn>
```

示例：

```text
TP-V1-001
```

规则：

- `V<major>` 是任务包体系版本，不等于产品版本。
- `<nnn>` 是三位递增编号。
- 编号一旦发布，不复用。
- 废弃任务标为 `superseded`，不要删除。
- 如果任务目标变大，新增后续编号，不在原文件里继续膨胀。

## 状态

允许状态：

- `draft`：还不能执行。
- `ready`：可由 subagent 执行。
- `in_progress`：正在执行。
- `blocked`：有外部依赖。
- `done`：已完成并验证。
- `superseded`：被新任务替代。

## 原子性

一个任务包只能改变一个行为面。

合格任务：

- config schema 校验。
- runner fake executor 边界。
- snapshot builder summary 聚合。
- Swift snapshot decode。

不合格任务：

- “重构 collector 并改 Widget”。
- “把 UI 做完整”。
- “实现所有 limits 功能”。

如果任务需要同时改两个以上行为面，必须拆分。

## TDD 规则

开发任务必须先红后绿：

1. 先写失败测试或 contract fixture。
2. 确认测试失败原因是目标行为缺失。
3. 实现最小代码。
4. 跑任务包要求的最小测试。
5. 跨层影响时跑完整测试。

任务包中必须写明：

- Red test。
- Implementation scope。
- Acceptance criteria。
- Verification commands。

文档任务可以不写代码测试，但必须有 grep / diff / link check 等文档验收。

## subagent 执行规则

subagent 只读取：

1. `AGENTS.md`
2. `docs/status.md`
3. `docs/task-packages/README.md`
4. `docs/task-packages/RULES.md`
5. 当前版本 `INDEX.md`
6. 自己的任务包文件
7. 任务包显式列出的参考文档或代码文件

subagent 不主动读取全部 `docs/*.md`，不顺手做邻近任务。

执行完成后，subagent 必须回报：

- 改了哪些文件。
- 跑了哪些测试。
- 哪些测试没有跑以及原因。
- 是否触碰了任务包之外的范围。
- 是否需要新增后续任务包。

## 任务包模板

```markdown
# TP-V1-000 Short Name

Version: V1
ID: TP-V1-000
Status: ready
Type: implementation
Depends on: none
Parallel with: TP-V1-001

## Goal

一句话目标。

## Context

执行者必须知道的最少背景。

## Scope

- 允许修改的行为。
- 允许修改的文件。

## Out of Scope

- 明确不做的事情。

## Red Test

- 先写哪些失败测试。

## Implementation

- 最小实现步骤。

## Acceptance Criteria

- 可验收条件。

## Verification

```bash
command
```

## Handoff

- 完成后要汇报的证据。
```
