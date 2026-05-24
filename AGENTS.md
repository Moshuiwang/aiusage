说中文

# Agent Rules

这是 Codex 每次会话会自动读取的最小规则。不要把项目说明、架构细节、任务拆解都塞进这里；需要时再按下面规则读取对应文档。

## 必须遵守

- 工作顺序：先保护已落地的 daily token baseline，再扩展 quota/reset 数据源和 Widget UI。
- 每个 OS 用户只能在自己的账户上下文运行 `ccusage`。
- 本机汇报默认使用本机当前日期和时区；远程采集和汇总要显式对齐到同一时区，避免服务端本地时区导致日期错位。
- 不要让 `wang` 读取 `/home/ubuntu`。
- 不要从 Mac 直接读取、同步或解析远程 `~/.claude`、`~/.codex` 原始日志目录；只允许读取明确设计过的结构化导出文件。
- 不要直接修改生产账户文件。
- 不要提交 SSH key、token、原始 usage 日志、`config/sources.local.json` 或生成数据。
- quota/reset 是当前研发方向，但不能把 `ccusage daily` 或本地估算伪装成官方额度状态。

## 固定数据源

- Mac 本机：`ccusage daily --json`
- Linux `wang`：`ssh wang@ai.chunbai.com 'ccusage daily --json'`
- Linux `ubuntu`：`ssh ubuntu@ai.chunbai.com 'ccusage daily --json'`
- quota/reset 扩展源：按 [docs/subscription-usage-source.md](/Users/wangzhipeng/Documents/ai-usage-widget/docs/subscription-usage-source.md) 设计，未落地前 UI 必须降级显示。

## 按需读取

- 当前阶段、决策、下一步：读 [docs/status.md](/Users/wangzhipeng/Documents/ai-usage-widget/docs/status.md)
- 项目入口、安装状态、常用命令：读 [README.md](/Users/wangzhipeng/Documents/ai-usage-widget/README.md)
- 采集链路、模块边界、JSON/SQLite schema：读 [docs/architecture.md](/Users/wangzhipeng/Documents/ai-usage-widget/docs/architecture.md)
- 产品范围、MVP/non-goals：读 [docs/product-brief.md](/Users/wangzhipeng/Documents/ai-usage-widget/docs/product-brief.md)
- 下一步实现、验收标准、任务拆分：读 [docs/task-plan.md](/Users/wangzhipeng/Documents/ai-usage-widget/docs/task-plan.md)
- 展示方案和 UI 方向：读 [docs/display-options.md](/Users/wangzhipeng/Documents/ai-usage-widget/docs/display-options.md)
- quota/reset 数据源方向：读 [docs/subscription-usage-source.md](/Users/wangzhipeng/Documents/ai-usage-widget/docs/subscription-usage-source.md)
- harness 文档规则：读 [docs/agent-harness-rules.md](/Users/wangzhipeng/Documents/ai-usage-widget/docs/agent-harness-rules.md)

如果当前任务能用本文件和代码上下文完成，不要额外读取 `README.md` 或 `docs/*.md`。
