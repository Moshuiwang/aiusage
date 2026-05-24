# Status

## 当前阶段

项目已进入任务包化执行准备阶段。

有效决策：

- 产品方向：本机 AI usage 观测数据产品，Widget 是只读展示面。
- 工程顺序：先稳 baseline pipeline，再做 snapshot API，再改 Widget，再接 limits。
- 任务入口：`docs/task-packages/README.md` + `docs/task-packages/v1/INDEX.md`。
- 执行规则：所有开发任务必须 TDD。

## 下一步

从 `TP-V1-001` 开始执行，除非用户指定其他任务包。

## 注意

- `docs/agent-harness-rules.md` 有既有未提交改动，本文件不覆盖它。
- 不要把任务细节重新写回本文件。
