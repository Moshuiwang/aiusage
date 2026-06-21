# Display Options

## 用途

这份文档只描述展示候选和信息架构，不定义采集实现。当前展示层必须服从 `docs/product-brief.md` 和 `docs/architecture.md` 的工程化方向：先展示可信 usage 和 source health，limits/quota 只有在数据契约支持时才展示。

目标 UI 原型归档在：

```text
docs/ui-direction/wight-ai-usage/
```

该原型表达 Apple-style Widget 的视觉方向，但其中 5H/WK quota、reset time、趋势切换和额外 provider 都不是 baseline 能力。

## 展示优先级

### Tier 1: Baseline 必须展示

这些信息来自 daily usage baseline 和 source health：

- 今日 total tokens。
- 最近快照生成时间。
- source health：成功、失败、禁用、过期。
- 今日按 OS account 拆分。
- 今日按 agent 拆分。
- 今日按 machine 拆分。
- 今日 token 类型结构：input / output / cache creation / cache read。

规则：

- 采集失败必须显式显示，不能显示成 0 usage。
- agent 无法识别时显示 `unknown`，不能猜测。
- 快照缺失、损坏、过期时显示空态或错误态。

### Tier 2: Snapshot v1 后展示

这些信息需要 snapshot builder 预聚合：

- 今日 summary。
- source 成功率摘要。
- 7 天 / 30 天趋势小图。
- 今日与昨日对比。
- 本周累计。

规则：

- Widget 不直接读 SQLite。
- 趋势进入 Widget 前，collector 或 snapshot builder 必须写入快照。

### Tier 3: Limits 数据可用后展示

这些信息依赖 limits/quota source：

- 5h quota percentage。
- week quota percentage。
- reset time / reset date。
- observed / estimated / stale 状态。

规则：

- `observed` 可以强展示。
- `estimated` 必须弱化。
- `missing` / `unsupported` / `failed` 降级为 baseline。
- 不能从 daily token history 推断官方 quota。

## Widget 信息密度

### Small

目标：

- 一眼看到今天 usage 和健康状态。

内容：

- 今日 total tokens。
- source health badge。
- 可选：top agent 或 account。
- 如果有 observed limits，可显示一个最关键窗口；没有则不占位。

### Medium

目标：

- 展示今日用量结构。

内容：

- 今日 total tokens。
- token 类型结构。
- account / agent top rows。
- source health。
- 如果有 observed limits，可加入 5h / week 进度条。

### Large

目标：

- 展示 usage、source 和趋势。

内容：

- 今日 summary。
- account / agent / machine 分布。
- source health 明细。
- token 类型结构。
- 可选趋势。
- 有 observed limits 时显示 reset 和 confidence。

## 非 Widget 展示

### CLI Report

用于工程排查：

- 当前快照摘要。
- source health 明细。
- 最近采集错误。
- schema version。
- snapshot path。

### 菜单栏详情页

后续可承载：

- 手动刷新。
- 最近 7 天 / 30 天趋势。
- source 配置检查。
- 失败 source 的排查提示。

## 视觉原则

- 靠近 Apple-style Widget：轻量、可扫读、状态明确。
- 不把 mock provider、mock quota 或 mock reset 放进真实 UI。
- 颜色用于区分 agent 和 source，但不作为唯一状态表达。
- 文案优先表达可信度，避免“官方额度”这类未经证明的暗示。
