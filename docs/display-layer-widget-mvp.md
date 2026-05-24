# Baseline Widget 展示层说明

## 定位

P0 baseline 展示层选择 macOS Widget 形态。

Widget 是 `data/latest.json` 的只读消费者，只负责把已经标准化的 token 统计结果展示出来。采集、SSH、ccusage 原始 JSON 解析、SQLite upsert、历史归档都不属于展示层。

当前 UI 方向参考已归档在：

```text
docs/ui-direction/wight-ai-usage/
```

该方向是当前后续 SwiftUI / WidgetKit 视觉和布局目标。其中 quota、reset time、usage percentage、趋势切换等能力由 `docs/subscription-usage-source.md` 定义数据来源；没有数据时，本文件描述的 baseline 视图仍然成立。

## 输入

唯一输入：

```text
data/latest.json
```

Widget 读取字段：

- `generated_at`：最近一次快照生成时间。
- `items[*].machine`：展示用机器名。
- `items[*].account`：OS 用户。
- `items[*].agent`：AI coding agent。
- `items[*].date`：usage 日期。
- `items[*].total_tokens`：该行总 token。
- `items[*].input_tokens`、`output_tokens`、`cache_creation_tokens`、`cache_read_tokens`：可选明细展示。

- `source_status[*].source_id`、`status`、`error_type`、`message`：source 采集状态。

如果后续要展示 quota/reset，collector 需要在 `latest.json` 增加稳定字段，例如 `quota_windows`。展示层不自行推断官方额度或 reset time。

## 展示内容

Baseline Widget 至少展示：

- 今日总 tokens。
- 按机器拆分的今日 tokens。
- 按 OS 用户拆分的今日 tokens。
- 按 agent 拆分的今日 tokens。
- 最近采集时间。
- 失败 source 状态。

今日总量计算规则：

- 使用 Mac 本机当前日期和时区作为“今天”。
- 筛选 `items[*].date` 等于今天的记录。
- 对筛选结果的 `total_tokens` 求和。

拆分计算规则：

- 机器拆分：按 `machine` 分组后求和。
- OS 用户拆分：按 `account` 分组后求和。
- agent 拆分：按 `agent` 分组后求和。
- 所有拆分都只基于今日记录。

## 状态处理

Widget 必须处理这些状态：

- 正常：`latest.json` 存在且 JSON 可解析，展示今日统计和更新时间。
- 尚未采集：`data/latest.json` 不存在，显示无可用快照。
- 快照损坏：JSON 无法解析，显示数据不可读。
- 今日无数据：快照存在但今日 `items` 为空，显示今日 0 或暂无今日数据。
- 部分 source 失败：展示成功 source 的统计，同时展示失败 source 状态。
- `generated_at` 缺失：仍展示 token 统计，但提示最近采集时间未知。

## 边界

Baseline Widget 不做：

- 不执行 `ccusage`。
- 不执行 SSH。
- 不读取远程 home 目录。
- 不读取或同步 `.claude`、`.codex` 原始日志目录。
- 不解析 ccusage 原始 JSON。
- 不写入 `latest.json`、SQLite 或归档目录。
- 不做 billing-grade precision。
- 不把估算当作官方 quota。
- 不依赖 reset time；缺失时降级展示 daily usage。
- 不做历史趋势图。
- 不做复杂 dashboard。

## 数据契约要求

为了让 Widget 实现简单稳定，collector 输出需要满足：

- `latest.json` 原子写入，Widget 不应读到半截 JSON。
- `items` 始终是数组；没有数据时为空数组。
- 每个 item 至少包含 `machine`、`account`、`agent`、`date`、`total_tokens`。
- `date` 使用 `YYYY-MM-DD`。
- `generated_at` 使用带时区的 ISO 8601 时间。
- `total_tokens` 是数字；缺失时由 normalizer 在写入前补齐，不留给 Widget 计算。
- 单个 source 失败不能导致整个 `latest.json` 缺失。
- 失败 source 需要有结构化状态字段，避免 Widget 从空数据反推。

## 最小交互

Baseline Widget 只需要被动展示，不要求复杂交互。

可选交互：

- 点击 Widget 打开 `data/latest.json` 所在目录或项目目录。
- 显示最近采集时间，方便判断数据是否过旧。

不在 MVP 内实现：

- 手动触发 collector。
- 配置 source。
- 切换时区。
- 查询历史日期。
- 展开 session、block、model 级别明细。

## 验收标准

- Widget 只读取 `data/latest.json`。
- Widget 不执行 collector、SSH 或 ccusage。
- Widget 能展示今日总 tokens。
- Widget 能展示按机器、OS 用户、agent 的今日拆分。
- Widget 能展示最近采集时间。
- Widget 能展示失败 source 状态。
- `latest.json` 不存在、损坏、今日无数据时，Widget 有明确空态或错误态。
- reset time 不存在时，不影响 Widget 展示。
