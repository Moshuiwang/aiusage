# TP-V2-081 Directory And Document Governance

Version: V2
ID: TP-V2-081
Status: done
Type: documentation
Depends on: architecture governance approval
Parallel with: none

## Goal

收敛目录和文档入口，让 AI Agent 用更少上下文找到当前事实源，并避免把历史设计稿、旧任务包或 legacy Widget 路线当成当前权威。

## Context

本任务是 Architecture Governance Round 8：目录与文档治理。Round 8 只处理文档、入口、索引和归档，不改变用户可见行为。

必须遵守：

- `docs/architecture/architecture.md` 是当前架构治理权威。
- 根 `docs/architecture.md` 不能直接指针化；必须先逐段核对，准确且子目录缺失的内容迁移到权威文档或新的短索引。
- V1 任务包是已弃用路线，不是已完成路线；归档时按 superseded 处理。
- `docs/architecture/client-platforms.md` 归档前，必须先把客户端当前/目标目录映射吸收到 `docs/project-map.md`，再修正 `docs/status.md` 指针。

## Scope

- 更新 `AGENTS.md` 的架构入口、任务包入口和治理轮次指针。
- 明确 `.codex/agents/*.toml` 的项目归属。
- 新增 `docs/project-map.md`。
- 新增或更新 `docs/architecture/database.md` 与 `docs/architecture/interfaces.md`，并以代码为当前权威。
- 核对根 `docs/architecture.md`，迁移仍准确的分层、schema、SQLite 口径、错误模型和部署策略；未实现内容必须标注为目标或归档。
- 归档 V1 任务包、历史 reviews、过期设计稿/proposal，并保留 `docs/archive/INDEX.md`。
- 更新 `docs/architecture/governance-state.md` 的 Round 8 完成记录。

## Out of Scope

- 不改产品代码。
- 不改 API 路径、HTTP method、status code 或 JSON 合约。
- 不改 SQLite schema，不写迁移。
- 不移动 `clients/`、`mobile/`、`widget/` 的真实代码目录。
- 不删除 tracked 文件；删除候选只在报告里列出。
- 不自动 `git add` 或 `git commit`。

## Red Test

文档治理任务不新增产品红测。执行前先用 grep/rg 证明当前存在以下漂移，并在完成后复查已消除：

- `AGENTS.md` 曾把工程架构指向 `docs/architecture.md`，已改为 `docs/architecture/architecture.md`。
- `AGENTS.md` 曾把任务包索引指向 V1，已改为 V2。
- `.gitignore` 曾整体忽略 `.codex/`，已显式允许 `.codex/agents/*.toml`。
- `docs/status.md` 曾引用 `docs/architecture/client-platforms.md`，已改为 `docs/project-map.md`。

## Implementation

1. 修正入口止血项：`AGENTS.md`、`.gitignore`、V2 index。
2. 核对根 `docs/architecture.md`，把仍准确且子目录缺失的内容迁移到权威文档或短索引。
3. 建立 `docs/project-map.md`，吸收客户端当前/目标目录映射。
4. 归档历史材料到 `docs/archive/`，并维护 archive index。
5. 更新治理状态并跑校验。

## Acceptance Criteria

- AI 进场只需从 `AGENTS.md`、`docs/status.md`、`docs/project-map.md` 和任务包入口即可判断当前事实源。
- `docs/architecture.md` 不再作为架构正文权威，但其仍准确的内容已经迁移或明确标注去向。
- 数据库和接口文档明确以代码为唯一当前权威。
- V1 任务包归档为 superseded 路线，并说明由 V2 HTTP push / mobile-first 取代。
- `client-platforms.md` 的内容先进入 `docs/project-map.md`，然后再归档，且 `docs/status.md` 不产生断链。
- 没有删除 tracked 文件，没有物理迁移客户端代码目录。

## Verification

```bash
git diff --check
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest tests.test_mobile_prototype -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
cd mobile/ios && swift test
```

文档验收：

```bash
rg -n 'docs/architecture/client-platforms.md|docs/task-packages/v1/INDEX.md|工程架构：`docs/architecture.md`' AGENTS.md README.md docs
git check-ignore -v .codex/agents/explorer.toml
```

结果：

- `git diff --check` 通过。
- `tests.test_mobile_prototype` 通过。
- `swift test` 通过。
- Python 全量测试仍失败，失败点是既有 macOS 菜单栏 / iOS 高保真 UI 静态断言；Round 8 未改产品 UI 代码。

## Handoff

- 汇报迁移了根 `docs/architecture.md` 的哪些段。
- 汇报哪些段被标为目标/未实现或归档。
- 汇报归档清单和未删除清单。
- 汇报测试结果和未跑测试原因。
