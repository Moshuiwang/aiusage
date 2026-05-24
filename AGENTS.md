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
