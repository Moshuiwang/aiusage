# Display Options

## 用途

这份文档列出当前可以呈现的数据和图表选项，供选择和补充。它不代表全部都要做；baseline 先保证 collector、`latest.json`、Widget 稳定，quota/reset 作为 P1 扩展进入。

## UI 方向归档

当前 UI 研发方向参考：

```text
docs/ui-direction/wight-ai-usage/
```

该目录归档了 `Wight for AI Usage` 设计原型。它代表后续希望靠近的 Apple-style Widget 方向，包括 light/dark、foreground/background、small/medium/large、多 agent、source 分布和趋势图。

需要注意：设计稿中的 5H quota、week quota、reset time、usage percentage 和多时间窗口趋势已经超出 daily usage baseline。它们不是废弃方向，而是 P1/P2 目标，需要补充数据源并扩展 `latest.json` 契约后才能实现。

选择建议：

- MVP 先选 3-5 个信息块。
- Widget 只放最关键的即时信息。
- 趋势、历史、模型细分可以先放在后续页面或命令行报表，不一定塞进 Widget。

## 当前数据能力

### 已经能从 `latest.json` 直接呈现

字段来源：

- `generated_at`
- `timezone`
- `items[].machine`
- `items[].account`
- `items[].agent`
- `items[].date`
- `items[].input_tokens`
- `items[].output_tokens`
- `items[].cache_creation_tokens`
- `items[].cache_read_tokens`
- `items[].total_tokens`
- `source_status[].source_id`
- `source_status[].status`
- `source_status[].error_type`
- `source_status[].message`

可直接做：

- 今日总 tokens。
- 今日按机器拆分。
- 今日按 OS 账户拆分。
- 今日按 agent 拆分。
- 今日 token 类型拆分：input / output / cache creation / cache read。
- 最近采集时间。
- 成功 source 数量和失败 source 列表。
- 今日是否有数据。
- 快照是否缺失或损坏。

### 已经能从 SQLite 查询，但 Widget 当前不直接读取

SQLite 已保存：

- collection runs。
- source reports。
- daily usage。
- daily model breakdowns。

可后续做：

- 最近 7 天 / 30 天总 tokens 趋势。
- 每个 source 的历史成功率。
- 每个 agent 的历史趋势。
- 每个 model 的历史用量。
- 今日和昨日对比。
- 本周累计。

需要注意：

- Widget 当前规则是只读 `latest.json`，不读 SQLite。
- 如果要在 Widget 展示历史趋势，建议 collector 先把小型聚合结果写进 `latest.json`，而不是让 Widget 直接查 SQLite。

### Baseline 暂时没有稳定数据支撑

这些不建议仅靠 daily usage baseline 展示：

- 官方 quota 剩余额度。
- billing-grade cost。
- reset time 精确预测。
- session 级明细。
- 项目级明细。
- 每次对话级消耗。

原因：

- 当前 MVP 只基于 `ccusage daily --json`。
- 不保存 raw archive、session、blocks。
- 不能把估算展示成官方结论。

## MVP Widget 信息块候选

### W01 今日总量

形式：

- 大数字：`今日 123.4K tokens`
- 辅助信息：最近采集时间。

数据来源：

- `items` 中 `date == today` 的 `total_tokens` 求和。

价值：

- 最核心，一眼知道今天用了多少。

建议：

- 必选。

### W02 采集健康状态

形式：

- `3/3 sources ok`
- 失败时显示：`linux-ubuntu ssh_failed`

数据来源：

- `source_status`

价值：

- 避免把“采集失败”误看成“今日没用量”。

建议：

- 必选。

### W03 按机器拆分

形式：

- 横向条形列表。
- 示例：`macbook 42K`、`dev-server 31K`、`prod-server 2K`

数据来源：

- 今日 `items` 按 `machine` 分组。

价值：

- 看主要 usage 来自哪台机器。

建议：

- MVP 可选，适合中号或大号 Widget。

### W04 按账户拆分

形式：

- 横向条形列表。
- 示例：`local 42K`、`wang 31K`、`ubuntu 2K`

数据来源：

- 今日 `items` 按 `account` 分组。

价值：

- 这个项目关注 OS 用户隔离，账户拆分比机器拆分更重要。

建议：

- MVP 推荐。

### W05 按 agent 拆分

形式：

- 小型列表或两段进度条。
- 示例：`codex 60K`、`claude-code 15K`、`unknown 1K`

数据来源：

- 今日 `items` 按 `agent` 分组。

价值：

- 看 Claude Code / Codex 使用占比。

限制：

- 如果 ccusage 的 agent 字段不稳定，可能出现 `unknown`。

建议：

- MVP 推荐，但需要接受 `unknown` 状态。

### W06 Token 类型拆分

形式：

- 四段堆叠条或小列表。
- input / output / cache creation / cache read。

数据来源：

- 今日 items 的四类 token 字段求和。

价值：

- 看 cache 是否占大头，判断 usage 结构。

建议：

- P1。对 MVP 有价值，但可能让 Widget 变拥挤。

### W07 今日 source 明细矩阵

形式：

```text
source         account   agent        tokens   status
mac-local      local     codex        42K      ok
linux-wang     wang      claude-code  31K      ok
linux-ubuntu   ubuntu    unknown      0        ssh_failed
```

数据来源：

- `items`
- `source_status`

价值：

- 排查很清楚。

限制：

- 小号 Widget 放不下。

建议：

- 更适合菜单栏弹窗或详情页，不适合最小 Widget。

## 历史图表候选

这些建议作为后续 Dashboard、菜单栏详情页或生成报表，不急着塞进 Widget。

### H01 最近 7 天总量折线图

数据来源：

- SQLite `usage_daily`

价值：

- 看近期使用趋势。

需要新增：

- 查询最近 N 天聚合的 CLI/helper。
- 如果要给 Widget 用，需要把聚合结果写入 `latest.json`。

建议：

- P1。

### H02 最近 7 天按 agent 堆叠柱状图

数据来源：

- SQLite `usage_daily`

价值：

- 看 Codex / Claude Code 的使用变化。

限制：

- agent 字段必须足够稳定。

建议：

- P1。

### H03 最近 7 天按账户堆叠柱状图

数据来源：

- SQLite `usage_daily`

价值：

- 对这个项目很有用，可以看 `wang` / `ubuntu` 是否有异常使用。

建议：

- P1 推荐。

### H04 模型使用排行

数据来源：

- SQLite `usage_daily_models`

价值：

- 看哪些 model 消耗最多。

限制：

- 需要确认 ccusage 的 `modelBreakdowns` 在真实三路 source 中都稳定。

建议：

- P2。

### H05 采集成功率

数据来源：

- SQLite `source_reports`

价值：

- 看 SSH 或 ccusage 环境是否稳定。

建议：

- P1/P2，适合排障，不适合主 Widget。

## 呈现形态候选

### S01 小号 Widget

适合放：

- 今日总 tokens。
- 采集状态。
- 最近采集时间。

不适合放：

- 多维拆分。
- 历史图表。
- 明细表格。

### S02 中号 Widget

适合放：

- 今日总 tokens。
- 采集状态。
- 按账户或按 agent 的 2-3 行拆分。

建议组合：

- W01 + W02 + W04。
- 或 W01 + W02 + W05。

### S03 大号 Widget

适合放：

- 今日总 tokens。
- 采集状态。
- 账户拆分。
- agent 拆分。
- token 类型拆分。

建议组合：

- W01 + W02 + W04 + W05。
- 如果空间足够，再加 W06。

### S04 菜单栏弹窗

适合放：

- 今日总览。
- source 明细矩阵。
- 失败详情。
- 手动刷新按钮。
- 最近 7 天轻量趋势。

说明：

- 菜单栏弹窗比 Widget 更适合交互。
- 如果要做手动刷新，不建议让 Widget 直接触发 collector；更适合菜单栏 app 或宿主 App 触发。

### S05 本地 HTML / CLI 报表

适合放：

- 历史趋势。
- 模型排行。
- 账户对比。
- 调试明细。

说明：

- 成本低，适合先验证数据价值。
- 不需要立刻处理 WidgetKit 布局和沙盒限制。

## 推荐的 MVP 展示组合

### 方案 A：最小可靠

内容：

- W01 今日总量。
- W02 采集健康状态。
- 最近采集时间。

适合：

- 先验证 Widget 可靠性。
- UI 最简单。

代价：

- 看不到具体是谁用了。

### 方案 B：账户优先

内容：

- W01 今日总量。
- W02 采集健康状态。
- W04 按账户拆分。

适合：

- 当前项目最关心多 OS 用户，尤其 `wang` / `ubuntu`。

代价：

- 不直接展示 Claude Code / Codex 拆分。

### 方案 C：Agent 优先

内容：

- W01 今日总量。
- W02 采集健康状态。
- W05 按 agent 拆分。

适合：

- 重点观察 Codex 和 Claude Code 使用占比。

代价：

- 如果 agent 字段是 `unknown`，信息价值会下降。

### 方案 D：大号总览

内容：

- W01 今日总量。
- W02 采集健康状态。
- W04 按账户拆分。
- W05 按 agent 拆分。
- W06 token 类型拆分。

适合：

- 大号 Widget 或菜单栏详情。

代价：

- MVP UI 会更复杂。

## Quota/Reset 方向

quota/reset-aware Widget 是当前研发方向，但数据源和可信度不放在本文件展开。详见：

```text
docs/subscription-usage-source.md
```

展示侧原则：

- 有可信 quota/reset 数据时，按 agent 展示 5h / week 百分比和 reset time。
- 没有可信 quota/reset 数据时，降级展示今日 token、token 类型结构和 source 状态。
- 本文件只保留 UI 候选和展示组合；数据采集、字段可信度、fallback 规则放到 quota/reset 数据源文档。
