# Status

## 当前阶段

项目已进入个人 HTTP push 架构重设阶段。

有效决策：

- 产品方向：个人使用的多设备 AI usage 观测数据产品。
- 采集方向：各终端在自己的 OS 用户上下文运行 `ccusage`，主动 push 结构化 usage payload 到个人 HTTP server。
- 展示方向：Web dashboard 是主要查看入口；Widget 是可选只读展示面。
- 工程顺序：先固化 HTTP ingest contract，再做终端 pusher，再接 canonical store / snapshot，再做 Web dashboard，最后补 Widget 和 limits。
- 任务入口：`docs/task-packages/README.md` + `docs/task-packages/v2/INDEX.md`。
- 执行规则：所有开发任务必须 TDD。

## 下一步

从 `TP-V2-001` 开始执行，除非用户指定其他任务包。

## 注意

- `docs/agent-harness-rules.md` 有既有未提交改动，本文件不覆盖它。
- 不要把任务细节重新写回本文件。
- V1 任务包代表旧的 SSH pull / Widget-first 方向；新开发默认不要从 V1 继续执行。
