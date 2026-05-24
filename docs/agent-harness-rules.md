# Agent Harness Rules

## 用途

这份文档定义本项目的 harness 文档规则，也就是用来驾驭 AI agent 的 Markdown 文档体系。它不描述程序架构，不替代 `docs/architecture.md`，也不承载完整任务拆解。

当用户提到“harness 文档”“驾驭文档”“AI 协作文档架构”“下次怎么让 agent 读懂项目”时，优先读这份文档。

## 术语边界

- 程序架构：collector、runner、normalizer、SQLite、Widget、schema、模块边界，写在 `docs/architecture.md`。
- 产品范围：这个项目解决什么问题、MVP 做什么和不做什么，写在 `docs/product-brief.md`。
- 当前状态：现在做到哪一步、当前决策、下一步，写在 `docs/status.md`。
- 任务拆解：下一批任务、验收标准、执行顺序，写在 `docs/task-plan.md`。
- 展示选项：Widget 信息块、展示组合、UI 候选，写在 `docs/display-options.md`。
- quota/reset 数据源：5h / week、reset time、usage percentage 的来源和可信度，写在 `docs/subscription-usage-source.md`。
- WidgetKit 操作：SwiftUI 预览、WidgetKit 构建、snapshot 同步，写在 `docs/widget-macos.md`。
- harness 规则：AI agent 每次进来应该如何读文档、如何判断范围、如何更新文档，写在本文件。

## 文档职责

### `AGENTS.md`

职责：

- 保存每次会话都必须遵守的最小硬规则。
- 保存固定数据源和禁止项。
- 保存按需读取入口。

不要放：

- 长篇项目背景。
- 完整程序架构。
- 详细任务拆解。
- 本轮临时状态。
- 已完成任务流水账。

判断标准：

- 如果这条规则每次 agent 进来都必须知道，才能避免越权、泄密或走错 MVP 顺序，可以放。
- 如果只是帮助理解项目，应该放到 `README.md` 或 `docs/*.md`。

### `README.md`

职责：

- 作为人类和 agent 的项目入口。
- 说明项目目标、数据源、常用命令、安装和运行方式。
- 保留足够上下文，让第一次打开仓库的人能跑起来。

不要放：

- 过细的任务列表。
- 每轮执行状态。
- 长期争议和已过期决策。

判断标准：

- 如果是“怎么使用这个项目”，放 README。
- 如果是“现在下一步做什么”，放 `docs/status.md` 或 `docs/task-plan.md`。

### `docs/status.md`

职责：

- 记录当前阶段、当前决策、当前待收敛点和下一步。
- 作为下一次 agent 接手时的第一份状态文档。
- 只保留当前有效状态，不做完整历史归档。

不要放：

- 完整架构说明。
- 详细产品背景。
- 大段任务拆解。
- 长期规则。

更新规则：

- 每轮完成实质变更后，更新“当前阶段”“当前待收敛点”“下一步”中已经变化的部分。
- 不要把所有历史都追加到末尾。
- 已过期的待办要删除或改写，不要保留冲突状态。

### `docs/architecture.md`

职责：

- 描述程序架构和数据链路。
- 记录模块职责、进程边界、JSON schema、SQLite schema、错误模型。

不要放：

- AI agent 读取规则。
- 本轮进度。
- 详细任务计划。

判断标准：

- 如果问题是“系统怎么运行”，放这里。
- 如果问题是“agent 下次怎么读文档”，放本文件。

### `docs/product-brief.md`

职责：

- 定义产品目标、用户场景、MVP 范围和 non-goals。
- 解释为什么要做这个项目，而不是怎么实现每个模块。

不要放：

- 具体代码模块职责。
- 当前实现状态。
- 测试命令流水账。

### `docs/task-plan.md`

职责：

- 保存可执行任务、验收标准、优先级和依赖关系。
- 任务应该能被 agent 直接拿来实现或验证。

不要放：

- 大段背景说明。
- 已经完成且不再需要追踪的历史细节。
- 和当前 MVP 无关的扩展想法。

更新规则：

- 完成任务后标注当前结果或移到状态摘要。
- 新增任务必须说明验收标准。
- 不要因为想到未来能力就扩展 MVP 范围。

## Agent 读取顺序

默认顺序：

1. 先读 `AGENTS.md`，确认硬规则和禁止项。
2. 再读 `docs/status.md`，确认当前阶段、决策和下一步。
3. 如果要改代码或 schema，再读 `docs/architecture.md`。
4. 如果要判断产品范围，再读 `docs/product-brief.md`。
5. 如果要继续实现任务，再读 `docs/task-plan.md`。
6. 如果要改展示层，读 `docs/display-options.md` 和 `docs/widget-macos.md`。
7. 如果要做 quota/reset，读 `docs/subscription-usage-source.md`。
8. 如果用户问文档体系、agent 协作方式、harness 规则，再读本文件。

不要默认全量读取所有 Markdown。当前任务能用 `AGENTS.md` 和代码上下文完成时，不额外读文档。

## 更新规则

### 只更新相关文档

- 改程序架构：更新 `docs/architecture.md`。
- 改产品范围：更新 `docs/product-brief.md`。
- 改当前进度：更新 `docs/status.md`。
- 改任务拆解：更新 `docs/task-plan.md`。
- 改展示方案：更新 `docs/display-options.md`。
- 改 quota/reset 数据源：更新 `docs/subscription-usage-source.md`。
- 改 WidgetKit 操作：更新 `docs/widget-macos.md`。
- 改 agent 文档规则：更新本文件，并在必要时同步 `AGENTS.md` 的入口。

### 保持入口轻量

`AGENTS.md` 只放会话启动必须知道的规则。不要因为某条信息重要，就默认塞进 `AGENTS.md`；先判断它是否“每次都必须立即读取”。

### 状态不能互相冲突

如果 `docs/status.md` 写“下一步做 A”，而 `docs/task-plan.md` 写“A 已完成”，必须同步修正。当前状态文档优先保持最新。

### 已过期内容要删除或降级

过期内容不要继续留在当前状态里。需要保留历史时，写成简短“当前结果”，不要做长流水账。

### 文档不要替代代码验证

harness 文档只帮助 agent 判断读什么和怎么协作。涉及真实实现状态、测试结果、Git 状态、文件存在性时，必须检查仓库实际内容。

## 命名建议

以后描述这类需求时，优先使用：

- harness 文档
- 驾驭文档
- AI agent 文档架构
- AI 协作规则
- agent 读取和维护规则

避免单独说“架构规则”，因为这容易被理解成程序架构。

更明确的说法：

```text
整理这个项目的 harness 文档规则，不是程序架构。
重点是 AGENTS.md、README.md、docs/status.md、docs/architecture.md、docs/task-plan.md 这些文档怎么分工，以及下次 agent 应该怎么读取和更新。
```

## 当前值得做

1. 保持 `AGENTS.md` 轻量，只承载硬规则和文档入口。
2. 用 `docs/status.md` 做接手入口，及时删除过期待办。
3. 把程序架构和 harness 规则分开，避免 `architecture.md` 被文档治理内容污染。
4. 每次文档改动后检查入口链接是否仍然准确。
5. 新增任务时同步验收标准，避免只写想法不写完成条件。

## 当前不值得做

- 不建复杂知识库目录。
- 不把每轮聊天完整归档进仓库。
- 不把所有规则都搬进 `AGENTS.md`。
- 不为未来扩展提前拆很多空文档。
