# Status

## 当前阶段

项目已完成个人 HTTP push 架构的基础部署，并完成 official limits provider MVP 的离线可测基线、runtime wiring、Codex WHAM 显式 auth adapter、Claude OAuth 显式 auth adapter、Codex app-server RPC adapter、Claude CLI `/usage` adapter、limits 本地配置契约、limits dry-run、config-only check、scheduler 模板、真实 smoke handoff、V2 索引状态对齐和 V2 backlog 入口清理。

有效决策：

- 产品方向：个人使用的多设备 AI usage 观测数据产品。
- 采集方向：各终端在自己的 OS 用户上下文运行 `ccusage`，主动 push 结构化 usage payload 到个人 HTTP server。
- 展示方向：Web dashboard 是主要查看入口；Widget 是可选只读展示面。
- 工程顺序：HTTP ingest、终端 pusher、canonical store / snapshot、Web dashboard 已形成 baseline；official limits contract、Codex / Claude offline provider parser、limits store、snapshot/API、Web 展示、`collect-limits` fixture runtime、Codex WHAM 显式 auth adapter、Claude OAuth 显式 auth adapter、Codex app-server RPC adapter、Claude CLI `/usage` adapter、limits 本地配置契约、dry-run、config-only check、scheduler 模板、真实 smoke handoff、V2 索引状态对齐和 V2 backlog 入口清理已形成 baseline。
- 任务入口：`docs/task-packages/README.md` + `docs/task-packages/v2/INDEX.md`。
- 执行规则：所有开发任务必须 TDD。
- limits 原则：历史 token / session logs 只做统计，不参与官方 reset time 计算。
- Codex provider 决策：参考 CodexBar 源码，后台采集采用 OAuth/WHAM usage 优先，`codex app-server` RPC `account/rateLimits/read` fallback。
- Claude provider 决策：OAuth Usage API 优先，Claude CLI `/usage` fallback。

## 下一步

下一步需要新增任务包后再继续：真实命令 smoke、Antigravity spike、或提交/PR 整理。

## 注意

- `docs/agent-harness-rules.md` 有既有未提交改动，本文件不覆盖它。
- 不要把任务细节重新写回本文件。
- V1 任务包代表旧的 SSH pull / Widget-first 方向；新开发默认不要从 V1 继续执行。
