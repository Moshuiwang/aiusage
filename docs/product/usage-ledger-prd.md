# Usage Ledger PRD

Date: 2026-06-28
Status: draft for implementation planning

## 配套文档

- 架构设计：[`../architecture/usage-ledger-architecture.md`](../architecture/usage-ledger-architecture.md)
- 数据库设计：[`../architecture/usage-ledger-database.md`](../architecture/usage-ledger-database.md)
- 接口设计：[`../architecture/usage-ledger-interfaces.md`](../architecture/usage-ledger-interfaces.md)

## 一句话目标

把 AI Usage 的用量统计从“反复扫描本地当前快照”升级为“服务端不可变入账账本”：Codex 和 Claude 的每笔用量按本地日志记录时间入账，服务端去重后生成小时、日、周、月和全部用量。历史数字一旦落库，不再因为本地 session 归档、移动或清理而回落。

## 背景

本轮核查发现两个直接影响用户信任的问题：

- Codex session 被归档后，`ccusage daily` 只读取 `~/.codex/sessions`，不会读取 `~/.codex/archived_sessions`，导致历史日总和月总可能变小。
- 当前 `usage_daily` 是按 `source_id + date + agent` 覆盖写入的日汇总快照，不是稳定账本。新的较小快照会覆盖旧的较大历史值。
- 本轮识别出一个需要产品侧锁定的边界：本机 pusher 不能把 `ccusage daily` 作为 Usage Ledger 明细采集的前置条件。如果用户卸载或禁用 `ccusage`，目标体验应该是 Codex / Claude 明细继续上报，后台只提示“日级对账不可用”。

进一步核查后确认：

- Codex 的可用事实源是 `~/.codex/sessions` 与 `~/.codex/archived_sessions` 中的 `token_count.timestamp + last_token_usage`。
- Claude 的可用事实源是 `~/.claude/projects/**/*.jsonl` 中的 `assistant.timestamp + message.usage`。
- Claude 同一个 `message.id` 会重复落日志，不能按行累加；需要按 `message.id + requestId` 去重，优先保留非零且最终有效的 usage。

## 当前调查结论

本节作为实施方和审查方的事实基线。后续 parser、doctor、review 都应先检查是否符合这些结论。

### Codex 记录方法

- 日志来源必须同时覆盖 `~/.codex/sessions` 和 `~/.codex/archived_sessions`。
- 可入账记录是 `token_count` 事件。
- 入账时间使用 `token_count.timestamp`。
- token 数使用 `last_token_usage` 中的 input、output、cache、reasoning 等字段。
- `token_count.timestamp` 应理解为“这笔 usage 被写入本地日志的记录时间”，不是 session 启动时间、停止时间，也不是严格的模型实际计算时间。
- 小时数据可以按这个记录时间入账；产品口径必须叫“按记录时间入账”。

已验证的风险：

- `ccusage codex daily` 默认只读取 active sessions，不读取 `archived_sessions`。
- 用户归档 Codex session 后，依赖 `ccusage daily` 或当前 active 快照的历史统计会变小。
- 因此历史回填、总量重新统计、增量窗口扫描都不能只扫 `~/.codex/sessions`，必须同时扫 `~/.codex/archived_sessions`。

### Claude 记录方法

- 日志来源是 `~/.claude/projects/**/*.jsonl`。
- 可入账记录是 `type=assistant` 且存在 `message.usage` 的记录。
- 入账时间使用 assistant 记录的 `timestamp`。
- token 数使用 `message.usage` 中的 input、output、cache 等字段。
- 同一个 `message.id` 可能多次出现在日志中，不能按行累加。
- 重复记录优先按 `message.id + requestId` 去重；如果没有 `requestId`，退化到 `message.id`。

当前采用的重复记录选择规则：

- 全 0 usage 不参与入账，除非该 key 只有 0 usage。
- 非 0 usage 完全相同时，只保留一条。
- 非 0 usage 不同时，暂按“总 token 更大优先；总 token 相同则 timestamp 更晚优先”选取最终有效 usage。
- 该规则需要通过 `ccusage claude daily` 做日级对账；未稳定验证前，对应日期应保持 `待确认`。

## 用户问题

| 场景 | 当前风险 | 目标体验 |
| --- | --- | --- |
| 用户归档 Codex session | 昨天/本月用量突然变小 | 归档只影响本地文件位置，不影响已入账历史 |
| 用户看小时图 | 可能误以为是严格实时消耗 | 明确这是“按记录时间入账”的小时用量 |
| 用户看今天/本周/本月 | 由 daily 快照覆盖，口径会漂移 | 全部从服务端小时账本聚合 |
| 用户刷新 Mac/iPhone/Web | 不同端可能因缓存和覆盖显示不同数字 | 同一服务端账本派生同一口径摘要 |
| 用户查历史 | 本地文件清理后历史会丢 | 历史一旦补齐并落库，不再变动 |

## 产品口径

### 入账时间

用量按本地日志的记录时间入账：

- Codex：`token_count.timestamp`
- Claude：`assistant.timestamp`

这个时间不是严格的模型开始时间，也不是 session 停止时间。它表示这笔 token 用量被工具写入本地日志的时间。产品文案应表达为“按记录时间入账的用量”。

### 聚合口径

- 小时：按入账时间所在小时聚合。
- 今天：正常日期按当天所有小时入账合计；上线切换日可以由“切换前今日总量 + 切换后小时账本增量”组成。
- 本周：沿用现有呈现口径，即近 7 天窗口；本次不改 UI 名称。
- 本月：沿用现有呈现口径，即近 30 天窗口；本次不改 UI 名称。
- 全部：服务端已入账历史合计。

所有聚合都必须基于同一个产品时区。客户端采集、服务端入库、UI 展示不能各自使用本机默认时区。

### 数据可信状态

每个日期必须有一个可被 doctor/AI agent 解释的状态：

- `已确认`：完整明细回填或增量账本已完成，对账在阈值内，可以进入确定汇总。
- `待确认`：明细回填与对账存在差异，或发现晚到事件尚未处理。
- `兜底估算`：只有 `ccusage` 日汇总或其他日级兜底，没有明细账本。

近 7 天、近 30 天、全部汇总默认只使用已确认数据，但今天是 live 日期例外：今天必须纳入当前汇总，并通过 doctor 标记为 live / open。待确认过滤只默认作用于今天之前的历史日期。

同一天如果跨来源状态不一致，整天的有效状态按最差状态计算：任一参与来源为 `待确认`，该日期整体视为包含待确认；任一参与来源为 `兜底估算`，该日期整体视为包含估算。doctor 诊断必须明确输出“包含待确认数据”或“包含估算数据”，不能把它们静默当成确定数字。

## 数据源规则

### Codex

纳入目录：

- `~/.codex/sessions`
- `~/.codex/archived_sessions`

事件规则：

- 只读取 `token_count` 事件。
- 使用事件自身的 `timestamp` 作为入账时间。
- 使用 `last_token_usage` 里的 token 字段作为本次记录用量。
- 生成稳定事件 ID，用于服务端去重。

建议去重 ID 组成：

- provider: `codex`
- source_id
- session_id
- timestamp
- session 内 `token_count` 确定性序号

去重 ID 不应包含原始文件路径、归档目录、glob 顺序、usage 数字或不稳定行 hash。usage 数字可以作为审计 metadata 的安全 fingerprint，但不能决定事件身份。

### Claude

纳入目录：

- `~/.claude/projects/**/*.jsonl`

事件规则：

- 只读取 `type=assistant` 且存在 `message.usage` 的记录。
- 使用 `assistant.timestamp` 作为入账时间。
- 使用 `message.usage` 的 token 字段。
- 按 `message.id + requestId` 去重；如果没有 `requestId`，退化到 `message.id`。

同一 key 多条记录的选择规则：

1. 过滤掉全 0 usage，除非该 key 只有 0 usage。
2. 如果非 0 usage 完全相同，只保留一条。
3. 如果非 0 usage 不同，选择最终有效 usage：优先选择总 token 更大的记录；如总 token 相同，选择 timestamp 更晚的记录。
4. 入账时间使用被选中记录的 timestamp。

在“最大 usage”规则完成足够样本验证之前，Claude 历史回填日期应先标记为 `待确认`；与日级对账稳定后再转为 `已确认`。

Claude 稳定事件 ID 只能来自 `message.id + requestId` 等去重身份，不能把 usage 数字编入事件 ID。后续扫描如果发现同一 key 的最终 usage 变大，必须更新同一事件并留下修正审计，不能新增另一条事件。

### 隐私与归因

客户端只上传统计所需的结构化 usage 信息。允许上传的身份字段必须限定为：

- source_id
- 机器别名或脱敏机器 ID
- OS 用户别名或脱敏用户 ID
- agent
- 可被本地证据支持的账号归因状态

账号归因不能靠猜测补齐。Codex 或 Claude 本地日志无法确认具体账号时，展示和诊断必须标记为“本机来源 / 未确认账号”。身份字段的展示范围和保留周期需要在实现任务中单独确认。

如果历史导入或旧 payload 连本机来源都无法确认，状态记为 `unknown`，doctor 仍按“未确认账号”处理，并提示需要补来源配置或重新上报。

## 无头运维命令

可信状态、确认、修复和忽略不要求通过 UI 或 Web 页面完成。本阶段默认由 AI agent 调用无头 CLI 完成。

建议命令口径：

- `ai-usage-widget doctor usage-ledger`：总览判断，输出最近上报时间、异常日期、待确认日期、晚到数据、账号归因状态、切换日状态和当前汇总是否包含估算数据。
- `ai-usage-widget usage-ledger collect --mode full_rescan --since <date> --until <date>`：按日期范围重新统计，用于历史回填、异常修复或人工核查。
- `ai-usage-widget usage-ledger collect --mode incremental_report`：日常每 N 分钟增量汇报，用于更新当前小时和冻结上一个小时。
- `ai-usage-widget usage-ledger confirm --date <date>`：在对账可接受后，将日期从 `待确认` 标记为 `已确认`。
- `ai-usage-widget usage-ledger repair --date <date>`：应用重新统计或人工回填结果，并留下修正审计记录。
- `ai-usage-widget usage-ledger ignore --date <date> --reason <reason>`：确认某个差异不进入展示汇总，并记录原因。

这些命令需要输出机器可读结果，便于 AI agent 判断下一步动作；普通用户不需要在产品 UI 里操作这些状态。

## 采集模式

用量采集程序必须区分两个口径，避免日常后台任务误触发总量重算。

### 总量重新统计

建议命令口径：`--mode full_rescan`。

用途：

- 首次上线历史回填。
- 用户明确要求重新核查历史总量。
- 处理异常日期、晚到数据或归档迁移后的人工修正。

产品规则：

- 不作为日常定时任务运行。
- 可以扫描完整本地 Codex/Claude 历史日志，也可以按日期范围扫描；Codex 必须同时扫描 active 与 archived sessions。
- 可以生成今天之前的完整明细账本。
- 可以为上线当天生成“切换前今日总量”，但不要求重建切换前每个小时的精确分布。
- 对已确认历史日期产生变化时，不能静默覆盖；必须生成修正记录，并让该日期重新进入 `待确认`，通过对账后再变回 `已确认`。

### 当前增量汇报

建议命令口径：`--mode incremental_report`。

用途：

- 日常每 N 分钟后台上报。
- 更新当前小时。
- 在满足保护条件后冻结上一个小时。

产品规则：

- 默认只扫描最近窗口内的日志；当前生产口径为最近 48 小时。Codex 最近窗口也必须同时扫描 active 与 archived sessions，避免刚归档的近期事件漏报。
- 增量扫描的候选集合不能只按事件入账时间过滤；必须覆盖最近发生变化的本地日志文件，避免“刚写入但 entry_at 早于窗口”的晚到事件永远不可见。
- 只能按事件 ID 去重后追加新入账，不能重新计算历史总量。
- 不能覆盖今天之前的已确认历史日期。
- 每次上报必须带上采集模式、扫描窗口、事件数量和去重结果，便于诊断“这是增量上报，不是总量重算”。

## 历史数据处理

上线前历史分两段处理。

### 今天之前

今天之前的历史数据先做一次完整明细回填，再固化：

1. 对本机所有 Codex 历史日志做完整扫描，覆盖 `~/.codex/sessions` 与 `~/.codex/archived_sessions`。
2. 对本机所有 Claude 历史日志做完整扫描，覆盖 `~/.claude/projects/**/*.jsonl`。
3. 客户端只生成结构化 usage 明细，不上传 prompt、response、工具输出或原始日志路径。
4. 每条明细生成稳定 ID，服务端按 ID 去重入库。
5. 服务端用这批历史明细聚合今天之前的小时、日、周、月和全部数据。
6. `ccusage` 只作为回填后的日级对账工具，不作为主导入数据源。
7. 对账通过后，今天之前的历史小时和历史日数据标记为 `已确认`，不再被日常增量上报覆盖。

用户体验要求：

- 历史数字可以被补齐一次，但补齐后不能再因为本地文件变化而回落。
- 如果历史来源是完整日志回填，后台诊断需标记为 `historical_full_backfill`。
- 如果某段历史只能用 `ccusage` 日汇总兜底，后台诊断需标记为 `historical_ccusage_fallback`，并在核查报告中说明缺少明细。
- `historical_ccusage_fallback` 只能参与日、周、月和全部汇总，不能生成小时分布。
- 同一个 `date + provider + source_id + agent` 上，明细事件和日级兜底必须互斥参与汇总：有明细时用明细，没有明细时才允许用兜底，不能相加。

历史回填对账：

- Codex 回填后，按天与 `ccusage codex daily` 做对账；对账时必须让 `ccusage` 同时看到 active 与 archived sessions。
- Claude 回填后，按天与 `ccusage claude daily` 做对账。
- 差异超过阈值时，该日期标记为 `待确认`，进入异常清单，不进入默认确定汇总。
- 差异在阈值内时，该日期标记为 `已确认`，以服务端明细账本为准，`ccusage` 不再参与后续展示。

### 今天

上线当天的老小时数据无需重算或修改。

从新逻辑上线时刻开始：

- 服务端记录 `cutover_at`。
- 新产生的 Codex/Claude 用量进入小时入账账本。
- 今日总数可以由“切换前今日总量 + 切换后小时账本增量”组成，边界必须是半开区间：切换前 `< cutover_at`，切换后 `>= cutover_at`，不能重叠。
- 切换前今日总量必须作为单独的切换日总量记录保存，并标记 `cutover_pre_total`，只参与今日总数，不生成切换前小时分布。
- 如果后续完整回填补齐了切换前 `< cutover_at` 的明细事件，`cutover_pre_total` 必须退出汇总并留下修正审计，不能与切换前明细事件相加。
- 今日小时图只承诺切换后的小时准确；切换前小时不要求拆准，也不回写旧小时图。
- 诊断必须能说明当天是否处于切换日口径。

## 实时上报逻辑

客户端每 N 分钟执行一次增量采集。当前 macOS 生产口径：

- N = 5 分钟。
- 每次默认 look back 最近 48 小时的相关本机日志。
- 客户端先在本机归并成小时桶，再上报给服务端；如果 Codex 和 Claude 都有用量，最多可以理解为约 `48 * 2 = 96` 条小时事实。
- 服务端按小时事实的稳定唯一键 upsert 去重。

每次上报内容：

- 最近窗口内 Codex / Claude 已归并的小时用量事实。
- source_id、机器、OS 用户、agent、账号归因信息。
- 采集时间、扫描窗口起止、小时桶数量、事件来源摘要和采集模式。

产品解释：

- 本机不会把每个 session 的原始明细、prompt、response、tool output 或原始日志路径上传到服务端。
- 本机也不会把“每日数据”作为 Usage Ledger 主事实上传；每日、近 7 天、近 30 天和全部用量应由服务端基于小时事实派生。
- 48 小时 lookback 是为了覆盖日志延迟、机器休眠、网络失败和近期归档，不代表每 5 分钟重新增加 48 小时用量。
- 同一个小时事实如果数值变了，服务端更新该小时的最新事实；如果该小时已经进入冻结或确认状态，后续应通过 doctor/repair 流程解释和修正，不能静默造成历史总量跳变。

### `ccusage` 缺失时的体验

Usage Ledger 采集不能依赖 `ccusage daily` 成功才能继续。`ccusage` 只允许作为日级对账和历史兜底来源：

- 如果 `ccusage` 不存在、执行失败或返回不可解析，客户端仍应继续扫描 Codex / Claude 本机日志并上报 ledger 明细。
- 服务端和诊断可以把该来源标记为 `daily_reconciliation_unavailable`，但不能把整台机器标记为 usage 采集失败。
- 用户可见结果应是新增用量继续更新；后台诊断提示“日级对账不可用”，而不是 Mac / iPhone / Watch 上这台机器的数据停更。
- 只有当 Codex / Claude ledger scanner 自身也失败时，才应显示这台来源的 usage 采集失败。

服务端行为：

- 已见过的小时事实不重复计数。
- 新小时事实按窗口开始时间写入对应小时。
- 同一小时事实再次上报时按唯一键 upsert，更新该小时的最新 token 分项、total tokens、事件数量、observed_at 和 metadata。
- 当前小时数据会随着新上报不断变化。
- 上一个小时在满足冻结条件后不再被普通增量上报修改。

## 小时冻结规则

认可“上一个小时在本小时第一次有效上报后落盘不动”的方向，但需要加一个保护条件，避免日志延迟写入造成漏账。

建议规则：

1. 当前小时始终可变。
2. 上一个小时在“本小时第一次成功上报且扫描窗口覆盖上一个小时尾部”后冻结。
3. 如果上报失败，不冻结。
4. 如果发现日志事件晚到超过保护窗口，记录为异常，不通过普通增量上报静默改已冻结小时。
5. 如果任一小时进入待修正、已修正或已忽略状态，所属日期必须同步降级或标记 `includes_pending`，doctor 必须解释影响范围。

示例：

- 10:00-10:59 是上一个小时。
- 11:05 第一次成功上报，扫描范围为 09:00-11:05。
- 服务端写入并去重 10:00-10:59 的所有可见事件。
- 10 点小时桶冻结，之后不再被普通增量采集修改。

冻结后的修正只能走无头 CLI 的 `full_rescan`、`repair`、`confirm` 或 `ignore` 流程，并留下审计记录。修正状态分为：

- `待修正`：发现晚到数据或对账差异，但尚未决定是否改数。
- `已修正`：通过回填或人工流程修正，并重新对账确认。
- `已忽略`：确认差异不进入展示汇总，需要留下原因。

## UI 与文案

用户可见文案建议：

- 小时图：`按记录时间入账`
- 今日：`今日入账`
- 本周/本月：沿用现有呈现，本次不做 UI 名称变更
- 数据说明：`用量按 Codex/Claude 本地日志记录时间入账，历史入账后不受本地归档影响。`

不建议使用：

- `实时每小时消耗`
- `真实计算时间`
- `session 实际运行时间`

## 非目标

- 不做 billing-grade 财务对账。
- 不采集 prompt、response、工具输出或原始日志路径。
- 不让服务端直接读取终端的 `~/.claude` 或 `~/.codex`。
- 不再把 `ccusage daily` 作为上线后 Codex/Claude 主事实源。
- 不要求用 `ccusage daily` 作为历史主数据源；历史优先使用完整明细回填。
- 不要求重建上线前当天每个小时的精确分布。

## 验收标准

| 验收项 | 通过标准 |
| --- | --- |
| Codex 归档 | 归档 session 后，已入账历史日/月总不下降、不重复增加 |
| Claude 去重 | 同一 `message.id + requestId` 重复日志不会重复计数 |
| 采集模式 | 总量重新统计与当前增量汇报是两个明确命令口径，日常任务只能运行增量汇报 |
| 小时入账 | 当前小时随 N 分钟上报更新 |
| 小时冻结 | 上一个小时在首个成功覆盖上报后冻结，冻结后普通增量上报不再改数 |
| 晚到修正 | 晚到数据不会静默改数，必须通过无头 CLI 进入待修正、已修正或已忽略状态 |
| 晚到发现 | 刚写入但 entry_at 早于扫描窗口的事件，增量上报仍能通过变更文件扫描发现并进入待修正或入账流程 |
| 日/近7天/近30天聚合 | 今日、本周、本月、全部均由服务端账本聚合；doctor 能说明是否包含待确认或估算数据 |
| 历史导入 | 今天之前历史通过完整明细回填一次性补齐，导入后不再被覆盖 |
| 历史对账 | 回填结果与 `ccusage` 日级对账通过；差异日期标记为待确认 |
| `ccusage` 缺失 | 卸载或禁用 `ccusage` 后，Codex / Claude ledger 明细仍继续上报；用户可见数据不因日级对账工具缺失而停更 |
| 切换日 | 上线当天今日总数和小时图口径可解释，不把切换前小时伪装成精确小时分布 |
| 隐私归因 | 不上传 prompt/response/工具输出/原始路径，账号不确定时显示未确认账号 |
| 诊断 | doctor 或核查工具能说明数据来自历史导入还是新账本，输出账号归因状态、今天 live 状态、切换日状态，并给出下一步 CLI 动作 |

## 待工程验证

- Codex `token_count` 事件 ID 的最小稳定字段组合。
- Claude 非 0 usage 不同的重复 message 中，“最大 usage”与 `ccusage` 的长期一致性。
- 日志晚到的真实分布，用于确认 48 小时 lookback 是否足够，以及是否需要更明确的文件变更游标。
- Cloudflare D1 的唯一键、冻结标记和修正审计表设计。
- `ai-usage-widget doctor usage-ledger`、`ai-usage-widget usage-ledger collect --mode full_rescan`、`ai-usage-widget usage-ledger collect --mode incremental_report`、`confirm`、`repair`、`ignore` 的命令参数、权限和默认运行频率。

## 建议拆分任务

1. 历史回填任务：完整扫描 today 之前的 Codex/Claude 明细，入库、对账并固化。
2. 采集模式任务：把总量重新统计和当前增量汇报拆成两个明确命令口径。
3. Codex parser 任务：从 active + archived sessions 生成事件级入账事实。
4. Claude parser 任务：从 assistant message usage 生成去重后的事件级入账事实。
5. 服务端账本任务：D1/SQLite 支持事件去重、小时桶、冻结、修正审计和日期状态。
6. Summary 聚合任务：today/week/month/all 从账本派生，并带上可信状态。
7. Doctor/CLI 任务：支持总览判断、确认、修复、忽略和机器可读输出。
8. UI 文案任务：只保留必要的“按记录时间入账”说明，本次不修改本周/本月呈现名称。
