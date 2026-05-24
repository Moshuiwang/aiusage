# Task Plan

## 用途

这份文档只保留当前可执行任务、验收标准和依赖关系。已完成的 scaffold 细节不在这里铺开，避免 agent 重复做旧任务。

## 当前优先级

1. 收敛 harness 和目标文档，消除旧 MVP 与 quota/reset 方向的冲突。
2. 验证 quota/reset 结构化 source 是否可行。
3. 扩展 `latest.json` 契约，加入 `quota_windows` 或等价字段。
4. 实现 collector 的 quota/reset 只读 source。
5. 按 `docs/ui-direction/wight-ai-usage/` 改造 SwiftUI/WidgetKit UI。

## Done Baseline

这些任务已完成到可继续迭代的程度，后续不要重新脚手架：

- T00：Mac、Linux `wang`、Linux `ubuntu` 的 `ccusage daily --json` 已验证。
- T01：Python 包结构、`config/`、`data/`、测试目录已建立。
- T02：local / SSH / file import runner 初版已实现。
- T03：daily normalizer 初版已实现。
- T04：collector 已写 `data/latest.json` 和 `data/usage.sqlite`。
- T05：SwiftUI 预览层、WidgetKit extension、`sync-widget` CLI 初版已实现。
- T06：`Wight for AI Usage` UI 设计方向已归档到 `docs/ui-direction/wight-ai-usage/`。

## Active Tasks

### A01 Harness 文档收敛

目标：

- `AGENTS.md`、`docs/status.md`、`docs/product-brief.md`、`docs/task-plan.md`、`docs/display-options.md` 对当前方向口径一致。

验收：

- `status.md` 不再要求重复做已完成 scaffold。
- `product-brief.md` 明确 baseline 与 quota/reset-aware Widget 的阶段关系。
- `display-options.md` 只保留展示候选，不展开数据源实现细节。
- quota/reset 数据源方案有独立文档入口。

### A02 Quota/Reset Source 可行性验证

目标：

- 确认 Claude Code / Codex 是否存在可读取的结构化 quota/reset 字段。
- 明确哪些字段是 observed，哪些只能 estimated。

验收：

- 有最小 fixture，例如 `tests/fixtures/active_limits_sample.json`。
- 能说明 `used_percentage`、`resets_at`、`window` 的来源。
- 如果只能通过 `ccusage blocks --json` 推断，必须标为 `confidence: "estimated"`。
- 不读取或同步 `.claude`、`.codex` 原始日志目录。

### A03 `latest.json` 契约扩展

目标：

- 在不破坏 daily usage baseline 的前提下，加入 quota/reset 输出。

建议字段：

```text
quota_windows[]
```

验收：

- `items` 和 `source_status` 继续兼容现有 Widget。
- quota/reset 缺失时，snapshot 仍合法。
- 每个 quota window 标明 `source_type`、`confidence`、`status`。
- `docs/architecture.md` 和测试 fixture 同步更新。

### A04 Collector Source 实现

目标：

- 新增只读 quota/reset source，优先读取结构化导出文件。

验收：

- 本机 source 可读 fixture 或真实结构化文件。
- 缺失、过期、shape 不支持、JSON 损坏都有结构化错误状态。
- SSH 版本只读取明确配置的结构化文件路径。
- 不修改远程用户配置。

### A05 Target Widget UI 改造

目标：

- 将 `docs/ui-direction/wight-ai-usage/` 的方向翻译为 SwiftUI/WidgetKit 视图。

验收：

- 有 quota window 时显示 5h / week 进度和 reset time。
- 无 quota window 时降级显示今日 total tokens、token 类型结构、source 状态。
- small / medium / large 有不同信息密度。
- Widget 不执行 collector、SSH 或 ccusage。

## Backlog

- 从 SQLite 生成 7 天 / 30 天聚合，并由 collector 写入 `latest.json` 供 Widget 使用。
- 菜单栏 app 手动刷新。
- raw ccusage 报表归档。
- model 排行和 source 成功率报表。
- 正式签名、bundle id 和 App Group container 收敛。

## 暂缓

- billing-grade precision。
- 聊天内容 token 自研估算。
- 把 `ccusage blocks` 当成官方 subscription quota。
- 未授权修改生产账户配置。
- 在 Linux server 部署 daemon，除非确认没有更轻的采集方式。

