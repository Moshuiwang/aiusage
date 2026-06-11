# Task Packages

## 用途

这里是任务包目录入口。开发、文档、QA 或 subagent 执行任务前，先读本文件，再按版本索引进入具体任务包。

任务包不是长期状态日志，也不是大任务清单。每个任务包都是一个可独立执行、可验证、可交接的原子任务。

## 阅读顺序

1. 本文件。
2. [任务包详细规则](RULES.md)。
3. 当前版本索引：[V2 Index](v2/INDEX.md)。
4. 被分配的具体任务包，例如 `v2/TP-V2-001-http-ingest-contract.md`。

## 当前版本

- Active version: `V2`
- Index: [v2/INDEX.md](v2/INDEX.md)
- First executable package: `TP-V2-060-mswusage-codex-hourly` parser-only contract.

## 目录结构

```text
docs/task-packages/
  README.md
  RULES.md
  v2/
    INDEX.md
    TP-V2-001-*.md
    TP-V2-002-*.md
  v1/
    INDEX.md
    TP-V1-001-*.md
    TP-V1-002-*.md
```

## 编号规则

任务包 ID 格式：

```text
TP-V<major>-<nnn>
```

示例：

```text
TP-V2-001
```

规则：

- `V<major>` 是任务包体系版本。
- `<nnn>` 是三位递增编号。
- 编号一旦发布，不复用。
- 废弃任务标为 `superseded`，不要删除。

## 状态规则

允许状态：

- `draft`
- `ready`
- `in_progress`
- `blocked`
- `done`
- `superseded`

只有 `ready` 任务可以直接执行。

## 执行规则

- 一个任务包只改变一个行为面。
- 开发任务必须 TDD：先写失败测试，再实现。
- 文档任务必须有 grep / diff / 链接一致性等验收。
- subagent 只执行被分配的任务包，不顺手做邻近任务。
- 执行完成后汇报改动文件、验证命令、未跑测试和后续任务建议。

## 任务包内容要求

每个任务包至少包含：

- `Goal`
- `Context`
- `Scope`
- `Out of Scope`
- `Red Test`
- `Implementation`
- `Acceptance Criteria`
- `Verification`
- `Handoff`

详细模板和参考来源见 [RULES.md](RULES.md)。
