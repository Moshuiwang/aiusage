# MSWusage Codex Hourly Plan

本计划定义 Codex 小时用量换源这件事怎样才算做成功，以及按什么步骤实现。

这里的“看到”不是指生产用户已经在真实手机上看到最终 UI，而是指 AI Agent / Codex 在模拟器、本地 API、snapshot 或测试数据里能观察到正确结果，并能按同一套标准判断任务是否完成。

注意：“看到了新口径数据”只能算初步成功。功能真正完成，还必须证明这份数据是真实、准确、可追溯的。

详细执行以这两个任务包为准：

- `docs/task-packages/v2/TP-V2-060-mswusage-codex-hourly.md`
- `docs/task-packages/v2/TP-V2-061-mswusage-codex-hourly-integration.md`

## 成功定义

这件事在当前阶段的成功分两层：

- 初步成功：AI Agent / Codex 能在模拟器或本地验证环境里看到 Codex 小时趋势已经切到新链路。
- 最终完成：这份可观察数据不仅来自真实生产形态链路，而且经过准确性验证，能证明它真实反映 Codex token 的实际发生时间。

最终完成标准是：

> AI Agent / Codex 在模拟器或本地验证环境里看到的 Codex 小时趋势，能可信地反映 token 实际发生时间；数据来自真实生产链路的数据路径，而不是本机 mock、手工塞数或本机直接绕过服务端提供；数据准确性经过独立核对；失败时有可观察的降级信号；不会泄露本机日志；不会破坏 daily 总账和 Claude 现有口径。

具体表现：

- Codex 小时趋势不再来自 `ccusage session.lastActivity`。
- Codex 小时趋势来自本机 Codex `token_count.timestamp + last_token_usage`。
- AI Agent / Codex 验收时使用的数据必须经过真实链路：本机 pusher 采集 -> HTTP ingest server -> SQLite canonical store -> snapshot / mobile summary API -> 模拟器或本地可观察面。
- 不允许用本机 mock、fixture、手工写 SQLite、直接读本机 parser 输出、直接把本机数据塞给模拟器来证明 061 已成功。
- 可观察到新链路数据只是初步成功；最终完成必须补充数据准确性验证。
- 数据准确性验证必须能核对：同一时间范围内，raw `token_count.timestamp + last_token_usage` 汇总、MSWusage report、server `usage_hourly`、snapshot / API 返回值之间的小时桶和 token 总量一致，允许差异必须被 drift 明确说明。
- AI Agent / Codex 不会再观察到整段 Codex 用量被堆到 session 最后活动时间那一小时。
- `ccusage daily` 仍然是 daily 总账基线，不被本地小时估算替代。
- Claude 小时逻辑不变，仍优先使用去重后的 `ccusage blocks`。
- token 分类加总和模拟器 / snapshot 中的 headline 总数一致，不出现 Input / Output / Cache 加起来对不上 headline 的问题。
- MSWusage 失败时，daily 仍可继续上报，Codex hourly 在 metadata 中标记不可用，不回退到旧 session 口径。
- MSWusage 与 daily 总量有明显偏差时，系统报告 drift，不偷偷把差额塞进当前小时制造假尖峰。
- 输出和 payload 不包含 prompt、response、tool output、命令输出、原始 JSONL、本机路径、`.codex` 路径或文件名。

## 分阶段定义

### 060 成功

`TP-V2-060` 成功只代表新数据源准备好了，还不代表模拟器、App 或 Web 已经切到新口径。

完成标准：

- 有一个本机 parser，可以从当前 OS 用户的 Codex `token_count` 事件生成稳定报告。
- 报告包含固定的 `daily`、`hourly`、`sessions` 行级 JSON contract。
- 小时桶按 `token_count.timestamp` 和指定 IANA timezone 计算。
- token 增量来自 `last_token_usage`。
- `cached_input_tokens` 被正确拆成 cache，避免分类重复计数。
- `reasoning_output_tokens` 保留为显式字段，但不重复计入总量。
- fixture 测试覆盖跨小时、跨天、坏数据、非 usage 行和安全输出。
- parser 测试走纯函数边界，不读真实 `~/.codex`。
- CLI 可以作为人工验证入口，但不得输出路径或原始日志内容。

### 061 成功

`TP-V2-061` 成功才代表模拟器 / API / snapshot 可观察的产品链路真正换源。

完成标准：

- device push 带上 `mswusage_codex_hourly_report`。
- ingest 接受新 report，并继续拦截敏感路径和原始日志内容。
- Codex hourly 写入 `usage_hourly` 时带 `provenance: "mswusage_codex_token_count"`。
- 写入新 Codex 小时行前，清理同 source/day 旧的 session-derived Codex 小时行，避免旧尖峰残留。
- Codex-like session 行，包括 `codex`、`gpt`、`openai`，不再通过 `session.lastActivity` 生成 Codex hourly。
- snapshot 读取已经换源后的 hourly rows，不在 snapshot 层做 provenance 读时择优。
- drift 状态进入 payload / snapshot metadata，UI 改动另开后续任务。
- drift 超阈值时，不通过 residual fill 把差额塞进当前小时。
- MSWusage 失败不会覆盖 daily 的 source health。
- AI Agent / Codex 可以通过测试、snapshot、API 返回值或模拟器数据面确认上述行为。
- 用于最终验收的可观察数据必须来自生产形态的数据路径，至少经过 ingest server 和 canonical SQLite store；测试 fixture、本机 parser JSON、本机临时 DB 或模拟器内置数据只能用于开发阶段测试，不能作为 061 成功证据。
- 用于最终完成的验收还必须包含准确性核对：从真实生产形态链路的 MSWusage report、server `usage_hourly` 聚合、snapshot / mobile summary API 中抽取同一时间窗口，确认小时桶、daily 汇总、token 分类和 provenance 一致。
- 默认验证不跑 launchd、不 SSH 生产、不读取生产或远程原始日志。

## 实现方法

1. 先执行 `TP-V2-060`。
   目标是做出安全、稳定、可测试的 parser contract。

2. 为 parser 先写失败测试。
   测试使用 sanitized JSONL fixture，覆盖 session_meta、多个 token_count、跨小时、跨日、坏行和非 usage 行。

3. 实现 `mswusage_codex.py`。
   核心逻辑放在类似 `build_report(jsonl_lines, timezone, now=...)` 的纯函数里，CLI 只负责读取当前用户本机 Codex 日志并调用它。

4. 固定输出 contract。
   `hourly`、`daily`、`sessions` 每行字段必须与 060 文档一致，后续 061 不再猜字段。

5. 验证 060。
   跑 `tests.test_mswusage_codex` 和 CLI 本机验证。此阶段不改 pusher、server、snapshot、App，也不碰生产。

6. 再执行 `TP-V2-061`。
   目标是把 060 的报告接入 push / ingest / storage / snapshot。

7. 为集成链路先写失败测试。
   覆盖 parser 成功、parser 失败、daily 继续成功、旧 session hourly 清理、Codex-like agent 跳过、drift、source health 不污染 daily。

8. 实现写入阶段换源。
   不改 `usage_hourly` 主键，不增加 provenance 维度；通过写入前清理旧 Codex 小时行来保证同一天不会新旧口径混在一起。

9. 实现 failure 和 drift 表达。
   MSWusage 失败写入 Codex-hourly-specific metadata；drift 写入 payload / snapshot metadata；UI 是否展示另开任务。

10. 验证 061。
    跑 pusher、ingest、storage、snapshot 和 mswusage parser 测试。只有用户明确要求时，才做 launchd 或生产 smoke。

11. 让 AI Agent / Codex 做可观察验收。
    通过真实链路产生的 SQLite 聚合行、snapshot JSON、mobile summary API 或模拟器数据面确认 Codex today hourly 已经是新口径。若模拟器 UI 尚未展示 drift / unavailable 状态，则以 API 或 snapshot metadata 作为本阶段验收依据，UI 展示另开任务。

12. 区分开发测试和成功验收。
    fixture、mock、本机 parser JSON 和本机临时 DB 只能证明代码逻辑局部正确；最终成功必须证明数据从真实采集路径进入 ingest server，再从 canonical store 被 snapshot / API / 模拟器读取。

13. 做数据准确性核对。
    选定一个明确的时间窗口，例如今天的最近数小时。对同一窗口核对四层数据：
    - MSWusage report 的 hourly / daily 汇总；
    - server `usage_hourly` 中 `provenance = "mswusage_codex_token_count"` 的 Codex 行；
    - snapshot / mobile summary API 返回的 Codex hourly；
    - daily baseline 与 drift metadata。

    核对目标是：小时桶一致、token 总量一致、Input / Output / Cache 分类一致、provenance 正确、drift 状态能解释 MSWusage 与 `ccusage daily` 的差异。只有这一步通过，才算最终完成。

## 最终验收口径

最终验收时，让 AI Agent / Codex 在模拟器或本地验证环境中回答这几个问题：

- 模拟器、API 或 snapshot 中的 Codex today 小时趋势，是否已经来自 token 实际发生时间？
- 这份可观察数据是否来自真实生产形态链路，而不是 mock、fixture、本机直连或手工塞数？
- 这份数据是否经过准确性核对，能证明它和真实 MSWusage report、server hourly 聚合、snapshot / API 返回值一致？
- 旧的 session.lastActivity 尖峰是否消失？
- daily 总数是否仍然以 `ccusage daily` 为准？
- Claude 小时是否没有被破坏？
- MSWusage 失败时，daily 是否还能正常，Codex hourly 是否明确降级？
- drift 是否被报告，而不是被当前小时假尖峰掩盖？
- 输出和上报链路是否没有泄露本机日志、路径或原始内容？

这些都满足，才算这条 Codex hourly 换源路线在当前 AI Agent / Codex 可验证层面真正完成。只看到新链路数据但没有准确性核对，最多算初步成功。生产用户 UI 是否需要额外提示、文案或可视化，另开后续任务处理。
