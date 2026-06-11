说中文

# Agent Rules

这是每次会话自动读取的最小规则。详细背景按需读取，不要把任务详情塞回本文件。

## 必须遵守

- 开发任务必须先读 `docs/task-packages/README.md`，再读当前版本索引和具体任务包。
- 所有开发任务遵守 TDD：先写失败测试，再实现。
- 先保护 daily token baseline，再改 snapshot 和 Widget；limits/quota 只作为后续可插拔 source。
- 每个 OS 用户只能在自己的账户上下文运行 `ccusage`。
- 本机和远程采集必须显式对齐时区。
- 不要让 `wang` 读取 `/home/ubuntu`。
- 不要从 Mac 直接读取、同步或解析远程 `~/.claude`、`~/.codex` 原始日志目录。
- 不要直接修改生产账户文件。
- 不要提交 SSH key、token、原始 usage 日志、`config/sources.local.json` 或生成数据。
- 不能把 `ccusage daily`、`ccusage blocks` 或本地估算伪装成官方额度状态。

## 按需入口

- 当前状态：`docs/status.md`
- 产品方向：`docs/product-brief.md`
- 工程架构：`docs/architecture.md`
- 任务包入口：`docs/task-packages/README.md`
- 任务包规则：`docs/task-packages/RULES.md`
- 任务包索引：`docs/task-packages/v1/INDEX.md`
- 项目命令：`README.md`

如果当前任务能用本文件和指定任务包完成，不要额外读取其他文档。

## Architecture Governance Workflow

- 当前项目采用分轮架构治理。
- 任何架构治理任务必须先读取：
  - `docs/architecture/architecture.md`
  - `docs/architecture/governance-roadmap.md`
  - `docs/architecture/governance-state.md`
- 每次只执行 `docs/architecture/governance-state.md` 中标记的 `next_round`。
- 每轮必须经过：
  1. baseline
  2. explorer review
  3. implementation
  4. reviewer review
  5. tests
  6. final report
  7. stop gate
- 没有用户确认，不得进入下一轮。
- 没有用户明确要求，不得 `git add` / `git commit`。
- 如果发现实际代码和 roadmap 冲突，以实际代码和测试为准，并在报告里说明。
- 如果发现任务范围会扩大，停止并报告，不要擅自扩大。

当前已完成轮次：

- Round 1: `server.py` / `server_services.py` / architecture boundary / legacy SSH marking
- Round 2: snapshot period/filter/trend helper extraction
- Round 3: iOS runtime server settings and Keychain token storage
