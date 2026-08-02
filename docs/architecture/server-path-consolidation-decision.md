# 架构决策：服务端路径收敛为 Cloudflare Worker + D1 单实现

- **状态**：已决策，实施中（2026-08-02）
- **决策来源**：Issue [#67](https://github.com/Moshuiwang/aiusage/issues/67)，三方共识（PM 提案 → Claude ADR 草案 → Codex 复核 → 最终方案评论 `issuecomment-5155126344`）
- **本文性质**：决策记录。它解释**当时为什么这么决定**，不是实施手册；实施拆在 #63 / #64 / #71 / #72 / #73 / #74。
- **本文写作时的证据等级**：1（已分析）+ 3（本文引用的代码事实与测试统计已在 Linux 开发机上实测复现）。生产环境未回源核实。

---

## 一、决策句

> **服务端收敛为 Cloudflare Worker + D1 单实现（路线 B，终态）；#63 / #64 的门禁与合同修复为迁移前置（路线 C）；采集端建立最小化可靠投递本地库（路线 D 第一阶段，outbox）；本地 facts 档案与预计算下放不在本轮承诺，evidence-gated。不选路线 A（重写）；不做 D 与 B 的单次大改绑定；D 不先于 B 的定权，但作为独立 Issue 串行推进。**

用户视角的一句话：**同一个数字以后只有一个地方算，加一个新字段只用付一遍代价，漏掉一边不会再悄悄发生。**

---

## 二、为什么要做这个决策

同一套业务行为此前有两份独立实现：Python（`snapshot_builder.py` / `mobile_summary.py` /
`ingest.py` + `server_services.py` / `version_contract.py`）与 Cloudflare Worker（`read-model.ts` /
`mobile-summary.ts` / `write-model.ts` / `version-contract.ts`）。生产权威是 Worker + D1，
Python 侧同时承担本地开发服务器与 golden 生成基准。

**两边必须行为一致，但没有任何结构性机制保证这一点。** 2026-08-01 一天之内撞了四次（#67 正文）：

1. `safeKeyName` 长度上限只在 Python 侧生效，Worker 声明了常量却从未使用 → 33 字符以上的未知 key 在两侧脱敏行为不一致（已修，PR #65）。
2. Worker 读取侧整块缺少版本合同 → 「哪台设备还在跑旧采集器」看不见（#63）。
3. `collection_runs.collector_version` 写入语义在两侧分叉（并入 #63）。
4. `value_golden.json` 由 Python 生成、只被 Worker 消费；Python 加字段但没重新生成 golden → **两边都没有新字段，所以「对得上」**，门禁静默失效（#63）。
5. `ingest_value_golden.json` 连消费者都没有，且已漂移约 93 处（#64）。

其中 4 和 5 最危险：它们**看起来正是防护到位的样子**。

必须同时看清的两个限制（决策前提）：

- **重复的只是「服务端路径」，采集端搬不走。** `pusher`、四个额度 provider、`deploy_*`、
  `mswusage_*`、CLI、`config`、`runners` 约 6568 行跑在用户的 Mac 和 Linux 机器上，要读 `ccusage`、
  调 `systemd` / `launchd`、读本机时区与 OS 用户上下文。Cloudflare Worker 是沙箱，结构上碰不到这些。
- **单实现只能消掉 2026-08-01 那六类问题中的两类。** 另外四类（守恒测试断言了恒成立的等式、
  测试卡在超时边缘、golden 记录的是失败那次、「无凭据泄露」验证没执行到那条代码路径）根因是
  「写实现和写测试的是同一个人」，与几套实现无关，已由 `AGENTS.md`「测试自身也会骗人」三条规则覆盖。
  **本决策不能替代那三条规则，也不宣称能替代。**

---

## 三、被否决的选项，以及为什么否决

这是本文最重要的部分。将来的人如果只记住「选了 B」，很容易在成本压力下退回被否决的选项。

### 路线 A：把 Python 侧的服务端路径重写成 TS —— **否决：不必要**

TS 侧**已经是生产权威且服务面完整**，唯一缺口是 #63 已点名的读取侧版本块（现已补齐，
`cloudflare/native-worker/src/read-model.ts`）。A 的工作量大半会花在「重写本来就要废弃的东西」上：
把 Python 的 3989 行逐行翻译成 TS，而这些行的行为 TS 侧早已有等价实现。
A 换来的终态与 B 完全相同，成本高一个数量级。

### 路线 C 作为终态（维持双实现 + 把 golden 门禁做成不可能静默失效）—— **否决：成本无限**

守卫只能**事后抓漂移**，抓到之后仍要在两边各改一遍。每个新产品字段永远付两遍实现成本 +
一遍 parity 维护成本，而这个成本不随时间下降。2026-08-01 一天撞四次证明它是现实且持续的支出。

**但 C 的内容本身没有被否决**——它被降级为**迁移期安全网**（Phase 0，#63 / #64），
因为迁移中期正是双实现并存最危险的时候。C 是前置，不是终态。

### D 不绑 B（只做算力下放，服务端仍留两份）—— **否决：不解决双实现**

算力下放让「需要重复实现的东西变少」，**没有解决「剩下的那部分还是两份」**。
面积变小不等于危险变小：`safeKeyName` 只是**一行未被使用的常量**，后果就是两侧 400 响应体的
脱敏行为不一致（PR #65）。分叉的危险性不随面积线性下降。

### D 先于 B / D 与 B 捆成一次大改 —— **否决：迁移风险**

Codex 复核指出 Phase 1（采集端本地库）与 Phase 2/3（服务端收敛）**文件面并不天然不相交**：
`cli.py`、`config.py`、`limits_runtime.py`、`version_contract.py` 及其测试会同时受影响。
最终裁决：**撤回「可并行」，全计划严格串行**；D 作为独立 Issue（#73）排在 B 的定权之后。

### 「只推预计算结果」（采集端算完只推结论）—— **否决：违反可重算性红线**

今天口径改了，服务端重算一次即可覆盖全部历史（`usage_hourly_facts` 完整保留，
`read-model.ts:473-489` 读路径会回落它重算）。如果 D1 里只剩采集端算好的派生结果，
**所有历史口径就被冻结在「当时那台设备、那个采集器版本的理解」上**，修正只能等每台设备
升级并重新上报才自愈。#63 的存量 `collector_version = "0.1.0"` 是这个风险的缩小版先例，
结论已经是「只能等自愈、不得在读模型里开特例」——那还只是一个字段。

### 「D1 永久保留全部小时事实」—— **不采纳为承诺（Codex 修正②）**

方向对，但「永久」同时是存储成本、隐私保留期和历史产品范围决策，不应在本 ADR 顺手定案。
改为第四节的红线 2 表述。

---

## 四、三条配套不变量

这三条是决策的**执行边界**。违反其中任何一条，收敛带来的收益都会被抵消。

### 不变量 1：职责判据

> **这个值是否只依赖本机可见输入？是 → 采集端；否（需要跨设备或跨来源的全局视图）→ Worker。展示层零口径计算。**

- **采集端**（只有本机能做）：`ccusage` / `mswusage` 输出解析、时区归一、小时与日 fact 生成、
  本机去重与增量、OS 用户上下文归属、额度 provider 本机探测。
- **Worker**（结构上需要全局视图，下放会产生 N 份不一致的局部结论）：多设备汇聚去重、
  周期截断（week / month / all 的边界）、provider 归属守恒、多台设备之间选哪个额度窗口当权威
  （今天就在 `read-model.ts:478` `bestLimitWindows`）、source health 判定。
- **展示层**（Web / iPhone / Watch / Mac 菜单栏）：零口径计算，只读。

### 不变量 2：事实层红线（Codex 修订版）

> D1 必须保存**满足已声明历史范围与重算精度所需的 canonical facts**；rollup 与任何采集端预计算
> **只是加速层**；任何对事实层的裁剪，必须先有明确保留期决策、归档/压缩方案与**会变红的守卫**，
> 不得因成本优化静默改变 `all` 口径。在此之前维持当前「不裁事实」行为。

当前状态是**巧合不是契约**：`cloudflare/native-worker/src/index.ts:188` `pruneAuditTables`
只裁 `source_reports` / `collection_runs`（审计保留期）与 `usage_hourly_rollups`（加速层），
不裁 `usage_hourly_facts`。`usage_hourly_facts` 上只有按 coverage 窗口的对账删除
（`write-model.ts` 的 ledger coverage 对账），不是时间保留策略。**这需要一条会红的测试固化。**

### 不变量 3：采集端产出事实，不产出跨设备结论

推送体只能是「事实 + 可选预计算」，**不得只推预计算结果**。这条是不变量 2 在 wire 上的投影，
也是防止「算力下放」在实施中滑向「结论也下放」的闸门。

---

## 五、「服务端路径」边界：逐模块点名

#67 验收标准要求不留模糊地带。

### 5.1 迁移到 Worker（Python 侧冻结 → #74 删除）

| 模块 | 行数 | 接替者 |
| --- | --- | --- |
| `src/ai_usage_widget/server.py` | 436 | Worker `index.ts`（生产早已如此）；本地开发入口改 `wrangler dev`（#71） |
| `src/ai_usage_widget/server_services.py` | 414 | `write-model.ts` / `read-model.ts` |
| `src/ai_usage_widget/ingest.py` | 224 | `write-model.ts` |
| `src/ai_usage_widget/snapshot_builder.py` | 1555 | `read-model.ts` |
| `snapshot_filters.py` / `snapshot_periods.py` / `snapshot_source_health.py` / `snapshot_trends.py` | 47 / 58 / 170 / 314 | `read-model.ts` |
| `src/ai_usage_widget/mobile_summary.py` | 771 | `mobile-summary.ts` |
| **合计** | **3989** | |

> **口径更正**：#67 正文与最终方案评论写的是「约 3442 行」。实测重算后是 **3989 行**。
> 差异来源：3442 = `snapshot_builder`(1555) + `mobile_summary`(771) + `version_contract`(478) +
> `ingest`(224) + `server_services`(414)，即 #67 正文那张对照表的小计——它**含**整个
> `version_contract.py`（实际是拆分不是删除），**不含** `server.py`(436) 与四个 `snapshot_*` helper(589)。
> #74 开工时以本表为准。

### 5.2 拆分

| 模块 | 处理 |
| --- | --- |
| `version_contract.py`（478 行） | **拆分**：采集端自报部分留 Python（`pusher.py` 与 `config.py` 在用）；**服务端判定权威归 `version-contract.ts`**，Python 侧判定部分随 #74 退役 |
| `storage_sqlite.py`（1132 行） | canonical store 权威已是 `cloudflare/migrations/`；它当前额外承担「D1 schema 镜像基准」职责（见 6.3）。#74 时**收缩或删除**；**不整体复用为采集端本地库** |

### 5.3 留在 Python（采集端，本决策不动）

`pusher.py`、`runners.py`、`mswusage_claude.py` / `mswusage_codex.py`、四个 `*_limits_provider.py`、
`limits_push.py` / `limits_doctor.py` / `limits_scheduler.py` / `limits_runtime.py` / `limits_config.py`、
`deploy_doctor.py` / `deploy_units.py` / `deploy_release.py`、`config.py`、`cli.py`（采集子命令）、
`normalize.py`、`models.py`、`timeutil.py` / `timezones.py`、`lock.py`、`backup.py`、`auth.py`。

`verify_cloud.py`（#60）**留**——它只读打生产 API，正是新架构的验收工具。
`d1_legacy_backfill.py` 留，标 legacy ops 工具。

### 5.4 判死 / 待建

| 对象 | 处理 |
| --- | --- |
| `widget_sync.py` / `sync-widget` / `latest.json` 本地快照线 | **判死**，随 #72 处置。发现真实消费者时降级为标 legacy，需贴证据 |
| `collector.py` / SSH 线 | 已是 legacy，随 #74 清理 |
| `cloudflare/native-worker/src/supabase-sync.ts` | **默认随 #74 删除**。仓库内无任何读取该镜像的代码；PM 在 #74 开工前指认消费者即豁免，并写进架构文档 |
| `collector_store.py` | **待建**（#73）：采集端本地 outbox。每 OS 用户一库，落 config 指定的自有数据目录。**本地库是缓冲不是档案**——acked 且过保留期即清，历史权威永远在 D1（设备会丢、会换） |

---

## 六、路线 B 的前置问题已回答：Python 本地服务器除开发便利外还承担什么

#67 验收标准点名要求回答。逐模块核查后的结论：**HTTP 外壳可以废弃，但「Python 服务端路径」上
缠着三个隐藏职责，必须显式接替，不能一删了之。**

### 6.1 外壳本身：可废弃

**生产设备从不运行 `server`。** `src/ai_usage_widget/deploy_units.py:24-25` 只定义
`ai-usage-pusher` timer/service（launchd label `com.chunbai.aiusage.pusher`），
全文件不出现 `server` 一次；生产入口是 Worker + D1。`server.py` 全部 436 行只做
路由 / 认证 / cookie / 静态文件，业务在 `server_services.py`；直接依赖这个外壳的测试只有
2 个文件（`tests/test_api_contract.py` 2 个、`tests/test_web_server.py` 18 个）。
→ 外壳只服务本地开发与合同测试，**可废弃**，由 #71 的 `wrangler dev` + 本地 D1 接替。

### 6.2 隐藏职责一：golden 生成基准

`scripts/gen_value_golden.py` 依赖 `snapshot_builder.build_snapshot` + `mobile_summary`。
废 Python 读模型 = 跨实现 parity golden 机制同时退役。**接替方案见第八节。**

### 6.3 隐藏职责二：D1 schema 镜像基准

`tests/test_d1_schema_migration.py` 拿 `storage_sqlite.py` 的 schema 与 `cloudflare/migrations/`
逐列比对。单实现后镜像守卫失去比对对象，**D1 migrations 需要自立的 schema 测试**（#74 交付项）。

### 6.4 隐藏职责三：采集端 limits 线 import 着读模型

`src/ai_usage_widget/limits_runtime.py:10-11` 同时 import `snapshot_builder.build_snapshot` 与
`storage_sqlite.write_limit_windows`，并在 `limits_runtime.py:122-129` 调 `build_snapshot`
重建本地 `latest.json` → `widget_sync.py` 同步进 macOS Widget 容器。macOS Widget 已非产品目标，
但**依赖边还在**：直接删 `snapshot_builder` 会连带弄断采集端 CLI。
→ **迁移前必须先剪断这条边**（#72，排在 #74 之前，这是串行顺序的硬理由之一）。

---

## 七、迁移测试覆盖统计（本文重新核实）

### 7.1 严格口径：188 个 / 9 文件 —— **复现通过**

统计口径：**测试文件的主要被测对象（primary owner）是服务端路径模块或版本合同**。
方法：`unittest.TestLoader().loadTestsFromName(...).countTestCases()` 逐文件计数
（Python 全量 662 个，与当前仓库一致）。

| 测试文件 | 测试数 | 主要被测对象 |
| --- | --- | --- |
| `tests/test_api_contract.py` | 2 | `server.py` |
| `tests/test_web_server.py` | 18 | `server.py` |
| `tests/test_server_services.py` | 15 | `server_services.py` |
| `tests/test_ingest_contract.py` | 24 | `ingest.py` |
| `tests/test_snapshot_builder.py` | 42 | `snapshot_builder.py` |
| `tests/test_snapshot_source_health.py` | 7 | `snapshot_source_health.py` |
| `tests/test_mobile_summary.py` | 25 | `mobile_summary.py` |
| `tests/test_version_contract.py` | 40 | `version_contract.py` |
| `tests/test_version_contract_doc.py` | 15 | `version_contract.py` + 文档一致性 |
| **合计** | **188** | |

**与最终方案评论的 188 一致，且在 #63 / #64 交付前后都是 188。** 复现方式：
在 `19d4239`（#63 之前）与 `2f07c45`（当前 HEAD）两个点各数一遍，这 9 个文件的和均为 188，
且 `git log 19d4239..HEAD -- tests/<file>` 对 9 个文件全部为 0（一个都没被改动）。

Python 测试总数在同期从 **641 涨到 662（+21）**，增量全部来自 #63 / #64 新增或扩充的守卫测试
（`tests/test_value_golden_freshness.py` 3 个、`tests/test_collector_payload_contract.py` 15 个、
`tests/test_d1_schema_migration.py` 扩充 3 个），**都不在这 9 个文件里**——
所以「总数变了」并没有让 188 过期。

### 7.2 旁及口径：另有 61 个测试会被波及 —— **188 不是删除面的全部**

188 只覆盖「主 owner 是服务端路径」的文件。另有 9 个文件的 **61 个测试** import 了待删模块，
`#74` 的「旧测试 → 新归属」映射表**必须一并覆盖**，否则会在删除时被无声打断：

| 测试文件 | 波及测试数 | 关系 |
| --- | --- | --- |
| `tests/test_normalize_ingest.py` | 7 | import `ingest` |
| `tests/test_provider_slots_parity.py` | 9 | import `snapshot_builder` + `mobile_summary` |
| `tests/test_value_golden_freshness.py` | 3 | import `snapshot_builder` + `mobile_summary`（#63 新增的防陈旧守卫） |
| `tests/test_storage_sqlite.py` | 10 | import `storage_sqlite` + `snapshot_builder` |
| `tests/test_d1_schema_migration.py` | 5 | 以 `storage_sqlite` 作镜像基准（见 6.3） |
| `tests/test_limit_windows_store.py` | 9 | import `storage_sqlite` |
| `tests/test_dashboard_static.py` | 8 | 断言 `src/ai_usage_widget/static/` 内容（`server.py` 的静态文件面） |
| `tests/test_limits_runtime.py` | 7 | 经 `limits_runtime` 间接依赖 `snapshot_builder`（#72 剪断后解除） |
| `tests/test_cli_verify_cloud.py` | 3 / 54 | 3 个测试用 `build_mobile_summary` / `build_version_health` 作 fixture owner 校验 |
| **合计** | **61** | |

**最大受影响面 = 188 + 61 = 249 个测试 / 18 个文件**（占 Python 全量 662 的 37.6%）。

### 7.3 结论

- 188 / 9 文件 **准确且今天仍可复现**，作为 #74 硬开工条件的映射表基数成立。
- 但**它是下界不是上界**。#74 的映射表口径应写成「188 主体 + 61 旁及」，
  否则会出现「映射表做完了、删除时仍打断 61 个测试」的情况。
- 与 Codex 复核估的「约 146 个」的差异：Codex 未计入 `test_version_contract_doc.py`(15)
  与 `test_web_server.py`/`test_api_contract.py`(20)，且当时口径更窄。最终方案已采纳 188。

---

## 八、golden / parity 机制换代

这是本决策**最容易被漏掉的部分**：

> **服务端收敛消灭的是「服务端内部」的双实现 parity；而「采集端（Python）↔ 服务端（TS）」的
> 合同边界是本质存在的、永远消不掉**，只能治理。

| 合同 | 现状 | 目标态 |
| --- | --- | --- |
| 服务端读模型 parity（`value_golden.json`） | Python 生成、Worker 消费，曾静默过期（#63 实测） | 迁移期靠 #63 的防陈旧守卫（`tests/test_value_golden_freshness.py`）；#74 后随 Python 读模型整体退役，**生成与防陈旧守卫移到 Worker 侧**，转为 Worker 自身的 API 回归合同。**API 合同（path / method / status / JSON）零变化** |
| ingest parity（`ingest_value_golden.json`，#64） | 零消费者、已漂移约 93 处 | **删除**（#64 已执行，commit `2f07c45`）。它比对的两个对象之一（Python ingest）已定向废弃，接上等于给死刑犯上保险 |
| 采集端 payload 合同 | 曾是隐式的，只靠 Worker ingest 运行时校验 | **显式化**：fixture 由 `pusher.py`（owner 模块）产出——`AGENTS.md`「fixture 必须由 owner 产出」规则——Worker ingest 测试消费，配同款防陈旧守卫。#64 已交付（`scripts/gen_collector_payload_fixture.py` → `cloudflare/native-worker/test/collector_payload_fixture.json`，守卫在 `tests/test_collector_payload_contract.py`）。运行时由版本合同执法 |

---

## 九、中期风险控制：「Python / TS / 半迁移三种状态并存」怎么避免

#67 正文点名的最大风险就是这个：迁移中期比现在的两套**更糟**。控制手段三条，缺一不可。

### 9.1 严格串行

**撤回**「Phase 1 与 Phase 2/3 可并行」的早期表述。全计划严格串行：
**#63 → #64 → #67(本文) → #71 → #72 → #73 → #74**。
理由：`cli.py` / `config.py` / `limits_runtime.py` / `version_contract.py` 是跨 Phase 共享文件，
没有文件 ownership 与合并顺序之前，并行只会制造第三种状态。
`AGENTS.md` 的「同一变更只能有一个主实施代理」在这里是硬约束，不是建议。

### 9.2 冻结声明（本决策的核心防线）

**Python 服务端路径冻结：只修迁移阻断问题，不承接新产品字段。**

- **允许**：修复迁移阻断问题、安全问题、让现有测试重新变绿的最小修复。
- **禁止**：承接任何新产品字段、新 API、新口径、新展示逻辑。**即使「Worker 那边也要加，
  顺手在 Python 这边同步一份」也禁止**——那正是让第三种状态长期存在的机制。
- 新字段的唯一去处是 `cloudflare/native-worker/src/*.ts` + `cloudflare/migrations/`。

冻结的作用是让「半迁移状态」**面积单调收缩**：冻结之日起，Python 服务端路径与 Worker 的
行为差距只会因为 Worker 前进而扩大，不会因为两边同时前进而互相追赶。这样每一步删除都是
「删掉一段已知落后的代码」，而不是「在两个都在动的目标之间做 diff」。

**执法位置**：`.claude/rules/architecture.md`（按 `src/**/*.py` / `tests/**/*.py` 路径自动加载，
改 Python 时必然被读到），不是只写在本文里。

### 9.3 Phase 0 守卫先行

在动任何刀之前，先让**会真的变红的**门禁到位（#63 / #64，已完成）：

- `value_golden.json` 重新生成 + 防陈旧守卫（重新生成并比对，golden 陈旧会红）。
- 死 golden 删除 + 由 owner 产出的 payload 合同 fixture + 防陈旧守卫 + 双向变异证据。
- Worker 读取侧版本合同补齐 + D1 加列。

迁移期一旦发生行为漂移，这些是唯一「会红」的东西。**不许在守卫缺位的窗口期执行删除。**

### 9.4 每一期独立可回退

| 期 | 回滚方式 |
| --- | --- |
| #63 / #64 | 均为可逆改动 |
| #71（本地开发切 `wrangler dev`） | Python server 还在，随时切回 |
| #72（剪断依赖边 + 判死 widget 线） | 依赖边剪断是纯收敛，可 revert |
| #73（采集端 outbox） | 关掉本地库直推即回现状；**但回退前必须先排空未 ACK 数据** |
| #74（删除 Python 服务端路径） | 以 PR 粒度可 revert；**开工前不动刀** |

---

## 十、实施计划与当前进度

| 序 | Issue | 内容 | 状态 |
| --- | --- | --- | --- |
| 0a | #63 | Worker 读取侧版本块 + D1 加列 + `value_golden` 重生成 + 防陈旧守卫；「最后成功上报版本」语义 | **已交付**（commit `95a34d5`，PR #79 draft），证据等级 3 |
| 0b | #64 | 删死 golden + 建立 `pusher.py` owner 产出的 payload 合同 fixture + 防陈旧守卫 + 双向变异证据 | **已交付**（commit `2f07c45`，PR #79 draft），证据等级 3 |
| 1a | **#67（本文）** | ADR 落地 + `.claude/rules/architecture.md` owner 边界更新 + 冻结声明 | **本文即交付物** |
| 1b | #71 | 本地开发旅程：`wrangler dev` + 本地 D1 成为唯一开发入口；`verify.sh` 按改动面裁剪；离线能力验证 | 待开工 |
| 1c | #72 | 剪断 `limits_runtime → snapshot_builder` 依赖边；`widget_sync` / `latest.json` 线判死；治理断言 + 变异证据 | 待开工 |
| 2 | #73 | 采集端 outbox 最小可靠投递（`collector_store.py`）；payload 零变化；分数据类型策略；原子 ACK；回退需排空 | 待开工 |
| 3 | #74 | 删除 Python 服务端路径；**开工硬门禁：1a-1c 完成 + 测试映射表（188 主体 + 61 旁及）+ #63 守卫在位** | 待开工 |
| 4 | 不立项 | 预计算下放、本地 facts 档案 | **evidence-gated**，待 #73 稳定运行且有成本/价值证据后另行决策 |

**#63 / #64 的生产迁移（证据等级 5+）需回 Mac / Ops 侧执行，Linux 侧证据不得顶替。**

### 关于采集端 outbox 的目标场景（收窄后）

采集端**不是**「失败即丢」——当前已有两层自愈：进程内重试 3 次
（`pusher.py:211` `retry_attempts: int = 3`）+ 下一轮回扫最近 48 小时
（`pusher.py:215` `ledger_lookback_hours: float = 48.0`，incremental 模式每轮传 `--lookback-hours`），
服务端按事实幂等键与 coverage window 对账。

所以 outbox 的目标场景收窄为：**断网超过 48 小时回扫窗口、本地来源日志在恢复前被回收、
设备长期离线或进程永远不再启动**。并且按数据类型分策略：

- **usage facts**：持久补推，直到明确 ACK 或不可恢复的终态合同错误。
- **limit observations**：带 TTL，只补最新有效观测；长时间离线后补推旧额度窗口没有用户价值。
- 400 / `unsupported` 等终态错误**不重试**；网络错误与 5xx 才进入退避补推。
- 磁盘上限行为**显式定义并测试**。

---

## 十一、一次性裁决清单（实施中不再讨论）

原样收录自最终方案评论第四节。

1. 采集端本地库模块名：**`collector_store.py`**；每 OS 用户一库，落 config 指定的自有数据目录（`data/` 已 gitignore）。本地库是**缓冲不是档案**：acked 且过保留期即清，历史权威永远在 D1。
2. `widget_sync.py` / `sync-widget` / `latest.json` 本地快照线：**判死**，随 #72 处置（发现真实消费者时降级为标 legacy，需贴证据）。
3. `supabase-sync.ts`：**默认随 #74 删除**；PM 在 #74 开工前指认消费者即豁免并写进架构文档。
4. `version_contract.py`：**拆分**——采集端自报部分留 Python（`pusher.py`、`config.py` 在用），服务端判定权威归 `version-contract.ts`（#74 落地）。
5. `value_golden.json`：#63 先重生成恢复真实 parity；#74 后跨实现 parity 机制退役，转为 Worker 自身 API 回归合同（生成与防陈旧守卫移到 Worker 侧），API 合同（path / method / status / JSON）零变化。
6. `storage_sqlite.py`：**不整体复用为采集端本地库**（避免在设备端复刻 D1 镜像、把双实现换个地方重演）；#74 时收缩或删除。
7. outbox 策略（#73）：usage facts 持久补推至 ACK 或终态合同错误；limit observations 带 TTL 只补最新；400 / unsupported 不重试；网络 / 5xx 退避重试；磁盘上限行为显式定义并测试；回退前必须排空未 ACK 数据。
8. #63 的存量 `"0.1.0"`：**不回填、不开特例，等自愈**。
9. #56 / #70（Mac Popover）不受本决策影响，按各自验收独立执行；#68 优化项 2 并入 #71。

### 附：#63 的用户承诺边界

`source_report_states.collector_version` 表示的是**最后一次被服务端成功接收的版本**，
不是设备当前运行版本——不兼容 payload 在
`cloudflare/native-worker/src/write-model.ts:116-123` 于**任何写库动作之前**被拒绝。
因此 UI / 合同措辞用「最后成功上报版本 / 最后验证时间」，
且它不能列出所有正在撞拒绝线的设备。

---

## 十二、本决策**不**承诺的事，以及仍然未知的事

诚实列出，避免将来被当成已决事项引用。

**不承诺**：

- 不承诺 D1 永久保留全部小时事实（见第四节红线 2 的措辞）。
- 不承诺本地 facts 档案与预计算下放（Phase 4，evidence-gated，尚未立项）。
- 不承诺单实现能消除 2026-08-01 那六类问题中的另外四类（它们由 `AGENTS.md` 三条规则覆盖）。
- 不承诺版本号能抓住行为漂移——版本号管的是**声明的兼容性**，不是**实际的行为一致性**。
  两套实现完全可以都声明 schema v2 然后对同一输入给出不同答案。能抓住行为漂移的只有
  「只有一套实现」或「一个真的会红的行为比对」。

**未知**：

- `wrangler dev` / miniflare 的**离线开发能力与体验**：未验证（#71 前置；Node 22 门槛不是新增，
  Worker 测试本来就要求）。
- 采集端本地库在低配设备上的**磁盘 / 并发写约束**：未评估（#73 需评估）。
- `supabase-sync.ts` 的**实际消费者**：未知（#74 开工前需 PM 确认）。
- 本文所有生产相关描述**未回源核实**（证据等级未达 5）。

---

## 十三、对既有文档的影响

- `.claude/rules/architecture.md`：owner 边界表已按本决策逐行更新，并加入 Python 服务端冻结声明。
  它按 `src/**/*.py` / `tests/**/*.py` 路径自动加载，是冻结声明的执法点。
- `docs/architecture/architecture.md`：「模块 Owner」与「新功能放置规则」两节已加冻结标注并指向本文。
  该文其余内容记录的仍是当前真实架构，在 #74 完成前保持有效。
- `docs/architecture/interfaces.md` / `database.md`：索引性质，随 #74 更新权威指向。
- **代码和测试是唯一事实源**；本文与代码冲突时以代码为准，并回来修本文。
