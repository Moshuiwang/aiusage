# 版本与升级架构决策

对应 GitHub Issue #58 阶段一。目标是让用户能回答两个问题：**哪台设备还在跑旧采集器**、
**各端是不是在消费同一版数据合同**；并且在采集端明显不兼容时，服务端有明确、可解释的处理方式。

> **事实源是代码。** 服务端与呈现端的字段清单、四态和阈值以
> `cloudflare/native-worker/src/version-contract.ts` 为准（#67 决策：服务端判定权威在 Worker）；
> 采集端自报的字段清单与上报路径以 `src/ai_usage_widget/version_contract.py` 为准。
> 两半各有一份文档合同测试把本文的表格解析出来、和代码常量与真实判定行为逐项比对，对不上就红：
> 服务端半边在 `cloudflare/native-worker/test/version-contract-doc.test.ts`，
> 采集端半边在 `tests/test_version_contract_doc.py`。文档与代码冲突时以代码为准。

## 权威入口

- 服务端版本字段口径、四态判定、最低支持版本策略：
  `cloudflare/native-worker/src/version-contract.ts`（唯一 owner）。
- 采集端自报版本字段：`src/ai_usage_widget/version_contract.py`（`pusher.py` / `config.py` 在用）。
- 上报 payload 校验与敏感字段边界：`cloudflare/native-worker/src/write-model.ts`。
- 兼容判定与拒绝动作：`cloudflare/native-worker/src/write-model.ts`（判定与 400 的
  `error_type` 都在写库之前定；`index.ts` 只按 `exc.status` 把 `WriteValidationError`
  序列化成响应，不参与判定）。
- 来源健康读模型（`/api/summary` 的 `source_status[].version` 与顶层 `version_health`）：
  `cloudflare/native-worker/src/read-model/summary.ts`（#126 目录化后 `read-model.ts` 只是兼容入口）。
- `/api/health` 的 `versions` 块：`cloudflare/native-worker/src/index.ts`（用
  `buildVersionHealth` 汇总，口径取自上面两条，自己不判版本）。
- 模块 owner 总表与依赖方向：[`architecture.md`](architecture.md)。
- 接口索引：[`interfaces.md`](interfaces.md)。
- 表结构索引：[`database.md`](database.md)。

## 版本字段清单与归属模块

采集端把版本信息放在 ingest payload 的顶层 `collector_release` 对象里（wire 格式，
`last_upgrade` 是嵌套子对象）。服务端校验后**扁平化**成下表的字段名，
存储层、读模型和诊断输出统一用扁平字段名。

`collector_release` 只接受下表列出的 key，**多一个未知 key 直接拒绝**，
避免任意数据借版本块夹带上来。

### 采集端版本字段

| 字段 | 上报路径 | 类型 | Owner | 说明 |
| --- | --- | --- | --- | --- |
| `collector_version` | `collector_release.collector_version` | semver 字符串 | `src/ai_usage_widget/version_contract.py` | 采集端 runtime 的发布版本，四态判定的主输入。 |
| `config_schema_version` | `collector_release.config_schema_version` | 整数 | `src/ai_usage_widget/config.py` | 设备配置 schema 版本，取自 `DeviceConfig.schema_version`。 |
| `parser_schema_version` | `collector_release.parser_schema_version` | 整数 | `src/ai_usage_widget/mswusage_codex.py` | usage 明细 parser 的 schema 版本，决定服务端能否理解上报的事实结构。 |
| `release_channel` | `collector_release.release_channel` | 枚举 `stable` / `beta` / `dev` | `src/ai_usage_widget/config.py` | 发布通道，用于分批发布；不在枚举里直接拒绝。 |
| `build_sha` | `collector_release.build_sha` | 7-64 位十六进制 | `src/ai_usage_widget/version_contract.py` | 构建 SHA，只接受十六进制，不接受路径或任意字符串。 |
| `last_upgrade_status` | `collector_release.last_upgrade.status` | 枚举 `never` / `succeeded` / `failed` / `rolled_back` | `src/ai_usage_widget/version_contract.py` | 最后一次自升级结果。 |
| `last_upgrade_from_version` | `collector_release.last_upgrade.from_version` | semver 字符串 | `src/ai_usage_widget/version_contract.py` | 升级前版本，也是回滚目标。 |
| `last_upgrade_to_version` | `collector_release.last_upgrade.to_version` | semver 字符串 | `src/ai_usage_widget/version_contract.py` | 升级目标版本。 |
| `last_upgrade_finished_at` | `collector_release.last_upgrade.finished_at` | ISO 8601 时间戳 | `src/ai_usage_widget/version_contract.py` | 最后一次升级结束时间。 |

Issue 原文写的是「collector/runtime 版本」。本决策**合并为一个字段** `collector_version`：
采集端只有一个可发布单元，再单独上报解释器版本只会多一个自由文本字段、多一条泄漏路径，
收益不足以抵消风险。需要解释器版本时另开 Story 并按同样的白名单方式加字段。

### 服务端版本字段

| 字段 | 类型 | Owner | 说明 |
| --- | --- | --- | --- |
| `api_version` | semver 字符串 | `cloudflare/native-worker/src/version-contract.ts` | HTTP 接口合同版本，接口本体由 `index.ts` 承载。 |
| `read_model_version` | semver 字符串 | `cloudflare/native-worker/src/version-contract.ts` | `/api/summary` 读模型合同版本，读模型本体由 `read-model.ts` 承载。 |
| `ingest_schema_version` | 整数 | `cloudflare/native-worker/src/version-contract.ts` | 服务端当前接受的 ingest payload schema 版本。 |
| `min_supported_collector_version` | semver 字符串 | `cloudflare/native-worker/src/version-contract.ts` | 最低支持采集端版本，常量 `MIN_SUPPORTED_COLLECTOR_VERSION`，低于它就拒绝。 |
| `target_collector_version` | semver 字符串 | `cloudflare/native-worker/src/version-contract.ts` | 目标采集端版本，常量 `TARGET_COLLECTOR_VERSION`，低于它只提示。 |

阈值本身不写进本文，避免文档和代码两份口径。要看当前值直接读 `version-contract.ts`。

### 呈现端版本字段

| 字段 | 类型 | Owner | 说明 |
| --- | --- | --- | --- |
| `app_version` | semver 字符串 | `clients/` | 各呈现端 App 的用户可见版本：Web、iPhone、Apple Watch、macOS 菜单栏、Android。 |
| `build_number` | 字符串 | `clients/` | 构建号；Web 用部署 build，Apple 平台用 `CFBundleVersion`。 |
| `data_contract_version` | semver 字符串 | `cloudflare/native-worker/src/mobile-summary.ts` | 呈现端消费的数据合同版本，由 DTO owner 定义，客户端不得自行改写。**尚未实现**：mobile DTO 当前输出的是 `schema_version`，本轮只定 owner。 |

呈现端的更新渠道（App Store / TestFlight / Web 部署）和用户可见版本入口**不在本轮范围**，
必须回 Mac 侧另拆 Story 验收。本文只固定字段名和归属，避免各端各写一套。

## 四态判定规则

判定优先级：`unsupported` > `rollback_available` > `update_available` > `current`。
`unknown` 不属于 Issue 要求的四态，是「采集端没报版本」的降级态：**不拒绝，也不当成合规**。

判定条件列写的是 `version-contract.ts` 的 `evaluateCollectorRelease()` 实际返回的 `reason`。
排序权重决定来源健康列表的确定性排序，数字越小越需要人工处理。

| 状态 | 排序权重 | 判定条件 | 服务端动作 | 用户看到什么 |
| --- | --- | --- | --- | --- |
| `unsupported` | 0 | `collector_version_below_minimum`（低于 `MIN_SUPPORTED_COLLECTOR_VERSION`）、`config_schema_version_below_minimum`、`parser_schema_version_below_minimum` | 拒绝本次上报并返回明确错误，不写库 | 该设备标红，提示必须升级采集端 |
| `rollback_available` | 1 | `last_upgrade_failed`（最后一次升级失败且有可回退版本）、`collector_version_ahead_of_target`（跑在比目标更新的版本上） | 正常接收，附带可回滚目标版本 | 提示可回退到已知良好版本 |
| `update_available` | 2 | `collector_version_behind_target`（低于 `TARGET_COLLECTOR_VERSION` 但不低于最低支持版本） | 正常接收，附带升级提示 | 提示有新版本可升级 |
| `unknown` | 3 | `collector_release_missing`（整块没上报）、`collector_version_missing`（上报了但没带版本号） | 正常接收，标记为未核实，不当成合规 | 提示该设备版本未知，需要升级采集端以获得版本可见性 |
| `current` | 4 | `collector_version_current`（等于目标版本） | 正常接收 | 无需处理 |

## 服务端最低支持采集端版本的语义

结论：**`target_collector_version` 是提示线，`min_supported_collector_version` 是拒绝线。**

- 低于 `target_collector_version`、不低于 `min_supported_collector_version`：
  **提示**。数据照常写入，响应里带上 `version.state = update_available`。
  旧版本采集端不会因为落后就丢数据。
- 低于 `min_supported_collector_version`，或 config / parser schema 低于最低支持值：
  **拒绝**。服务端在写库之前判定，返回 HTTP `400` 且 `error_type` 为
  `collector_version_unsupported`，消息里说明当前版本、最低支持版本和「本次上报未写入」。
  采集端能据此明确知道要升级，而不是以为上报成功了。
- 没上报版本（`unknown`）：**提示**，不拒绝。缺字段既不返回 500，也不静默当成合规；
  响应里带 `version.state = unknown`，来源健康列表里同样会列出来。

这条边界的产品要求是：**不得无提示丢弃数据**。三种情况分别是「写入并提示」「明确拒绝」
「写入并标记未核实」，没有任何一条是静默丢弃。

阈值提升属于运维决策，必须先让存量设备升级到位再改常量，否则会一次性拒掉一批生产采集端。

两点必须说清楚，避免被误读：

- **schema 拒绝线只在采集端真的上报了该字段时生效。** 老采集端不报
  `parser_schema_version` / `config_schema_version` 时，服务端只按 `collector_version` 判定，
  不会凭空拒绝。要靠 schema 拒绝线拦住老协议，前提是先把 `collector_version` 的最低支持线提上去。
- **`verified` 只表示「采集端上报了版本号并完成判定」**，不表示「全部版本字段都已核对」。
  没上报的字段在输出里是 `null`，展示层不能把 `verified: true` 当成「这台设备已核对无误」。

## release manifest 的校验方式

自升级机制本身（发现更新、分批升级、写后读、自动回滚演练）需要生产凭据和真实采集端，
**不在本轮范围**，必须另拆 Story 并回 Ops / 真实设备侧执行。本文只固定校验方式的决策：

1. **manifest 内容**：版本号、release channel、构建 SHA、每个产物的 `sha256` 校验和、
   最低可升级来源版本、发布时间。
2. **签名**：manifest 本身必须带非对称签名（Ed25519），采集端内置公钥验签；
   签名不通过直接放弃升级，不做任何文件替换。
3. **校验和**：产物下载后按 manifest 里的 `sha256` 逐个校验，校验和不匹配直接放弃。
4. **预检**：验签和校验和都通过后，先在临时目录做一次预检（可执行、可加载、版本自报一致），
   预检失败不进入切换。
5. **原子切换**：用符号链接或临时目录改名做原子切换，切换过程不修改 token、账号配置、
   原始日志权限或 OS 用户边界。
6. **健康验证与回滚**：切换后跑一次健康验证（能采集、能上报、版本自报与目标一致）；
   失败则**回滚**到切换前版本，并把 `last_upgrade_status` 置为 `rolled_back` 上报。
7. **分批发布**：按 `release_channel` 和分批名单推进，不允许一次性升级全部生产采集端。

## 安全边界

- 版本字段一律用收紧的字面量白名单校验：semver、十六进制 SHA、枚举、ISO 时间戳。
  token 形态和绝对路径形态**通不过校验**，因此不可能出现在任何版本字段或健康输出里。
- 校验失败的异常信息**只报字段名，不回显字段值**，避免把疑似凭据写进日志或错误响应。
- 版本字段不承载账号、路径、主机地址等身份信息；设备身份仍由既有 `source_id` /
  `machine` / `os_user` 承载。

## 已知缺口

> 本节是自由散文。除全文级卫生检查（断链、绝对家目录/凭据形态，
> `tests/test_version_contract_doc.py` 的 Hygiene 组）外，本节不在任何**结构化**
> 文档合同断言的解析范围内（#93 的守卫只覆盖字段表、四态表、
> 最低支持版本与权威入口清单），事实是否过期**只能靠人核**——
> 历史上文档里唯一过期的就是本节（#94）。
> 因此每条都必须写明证据与复核日期。本节最近一次逐条实测复核：2026-08-03（#94）。

### 已闭合（不再是缺口，留档防止重复评估）

| 原缺口 | 闭合证据 |
| --- | --- |
| 读取侧（`/api/summary` 的 `source_status[].version`、顶层 `version_health`、`/api/health` 的 `versions`）在 Worker 上缺席 | #63（commit `95a34d5`）按当初预告的唯一干净路径交付：`0007` 迁移给 `source_report_states` 加 `collector_version` 列，ingest 写入时物化，读取侧产出在 `read-model.ts`（`version_health`、`source_status[].version`）与 `index.ts`（`/api/health` 的 `versions`）。生产 D1 已应用 `0005`–`0007` 并发布 Worker，线上 smoke 回读到 `version_health` 与 10 项 `version` 子对象（#81，证据等级 5+回读） |
| 「两边都没有新字段所以 parity 对得上」的假绿形态 | #74 P1 迁移（PR #89）：四份合同 golden 的生成端与防陈旧守卫都在 Worker 侧（`cloudflare/native-worker/test/golden/` + `golden-freshness.test.ts`，`provider_slots_golden.json` 与 macOS owner fixture 的守卫在 `provider-slots-parity.test.ts`，重新生成走 `npm run cf:golden:gen`），golden 记录 Worker 自己的输出，陈旧会立刻变红 |
| Worker 无条件往 `collection_runs.collector_version` 写死占位值 `"0.1.0"` | 已改为只写采集端真实上报的版本，没上报写 NULL（`write-model.ts` 的 collection_runs 插入路径）；读取侧口径同时改为只看 `source_report_states`，其存量行版本列为 NULL → 判 `unknown`，不会把占位值当真值展示（#81 smoke：`unknown=10` 即此形态） |

### 仍开

- `collection_runs` 审计历史里升级前写入的存量 `"0.1.0"` 行，仍无法与真正在跑 0.1.0 的
  设备区分——但它已不进任何读取侧口径（读取侧只看 `source_report_states`）。
  仍然**不要给 `"0.1.0"` 开特例**（会误伤真的在跑 0.1.0 的设备）；`collection_runs`
  是追加表，这些旧行不会被新上报覆盖，但会随保留期清理（`index.ts` 的
  `DELETE FROM collection_runs WHERE collected_at < ?`）自然过期，不需要治理动作。
- 版本健康口径下服务端只**持久化** `collector_version`（`collection_runs.collector_version`
  与 `source_report_states.collector_version` 两列）。`config_schema_version`、
  `parser_schema_version`、`release_channel`、`build_sha`、`last_upgrade_*` 只在 ingest
  当次参与判定并回写到响应里，**尚未落库**，因此来源健康列表里这些字段为空。
  补齐需要一次 D1 schema 迁移，属于另一个 Story。
  （注意别混淆：`source_accuracy.parser_schema_version` 是准确度追踪线的列，
  不是版本健康口径的落库。）
- 自升级演练、各呈现端更新渠道与用户可见版本入口、诊断页 UI 展示：均未实现，
  需要真实设备 / Mac / Ops 侧执行。
