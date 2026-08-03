# #74 开工门禁：Python 服务端路径「旧测试 → 新归属」映射表

- **性质**：Issue [#74](https://github.com/Moshuiwang/aiusage/issues/74) 的硬开工门禁交付物。
  逐个测试函数标注归属，**不许无映射删除**。
- **产出方式**：只读分析。本文交付过程中未修改任何代码或测试。
- **证据等级**：1（已分析）。文中所有「Worker 侧有/没有覆盖」的判断都来自本机实测的
  grep / 文件读取，但**没有运行过任何测试**；标 ⚠️ 的覆盖缺口未经运行时验证。
- **基准 commit**：`1d7a856`（分支 `feat/server-consolidation`），Python 全量 **678** 个测试。
- **上位文档**：`docs/architecture/server-path-consolidation-decision.md`（#67 ADR）。
  与 ADR 冲突处以本文实测为准，并已在第 8 节列出差异。

---

## 1. 先读这一节：三个会让删除立刻降低覆盖的阻断项

映射表本身可以填满，但下面三件事没解决就动刀，**删除会造成真实的覆盖率下降**，
而这正是门禁要防的事。

### ~~阻断 P0：`ccusage_daily_status` 在 Worker 上根本不存在~~（#78 已收口，2026-08-02）

> **本节是历史快照，阻断已解除。** #78 的 PM 决策是**从采集端摘掉该字段，不补进 Worker**：
> 它在生产（Worker + D1）上从来没被解析过，留着只是让 Python 侧独有一条产不出结论的诊断路径。
>
> 收口后的事实：`pusher.py` 不再发（三条产出路径全部清理），`ingest.py` 不再声明也不再校验，
> `server_services.py` 不再据它回填来源健康。向后兼容由**一对跨实现测试**守住——
> Python 半边 `tests/test_collector_payload_contract.py::TestDroppedLegacyFieldIsIgnoredByBothImplementations`、
> Worker 半边 `ingest.test.ts`「老版本采集端仍在发的 ccusage_daily_status 被当未知字段忽略」，
> 读同一份探针 `cloudflare/native-worker/test/legacy_collector_payload_ccusage_daily_status.json`，
> 断言同一组可观测结果：不报错、不解析、不落库。
>
> **已知代价（PM 已知悉，不新增替代字段）**：ccusage 挂了但账本仍可用时，payload 是
> `collection_status: "ok"` 且不带 `error_type` / `error_message`，所以「ccusage 在这台设备上
> 装挂了」不再被上报。该代价由 `test_pusher.py`、合同 fixture 的
> `partial-ccusage-missing-tool-ledger-ok` 场景和 Worker 侧对应用例三处钉死。
>
> 顺带补齐的盲区：合同 fixture 原先只有「全成功」「全失败」两个场景，碰不到这个字段，
> 所以 `ingest.test.ts` 那条「顶层字段必须被 Worker 声明并解析」的断言对它有盲区。
> #78 补上了部分失败场景。

原始记录（收口前）：采集端 `pusher.py` 会发这个字段（5 处构造），Python 服务端
`ingest.py:134-137` 校验它，**Worker 侧全文零命中**。受影响的 4 条测试
（`test_ingest_contract.py` 3 条 + `test_server_services.py` 1 条）曾是这个行为唯一的守卫。

### ~~阻断 P1：三份「合同 fixture」的生产者全部是即将被删的 Python 读模型~~（2026-08-02 已解除）

> **本节是历史快照，阻断已解除。** 生成端与防陈旧守卫已迁到 Worker 侧：
>
> - 收集器（生成与校验共用的唯一实现）：`cloudflare/native-worker/test/golden/`
> - 重新生成：`npm run cf:golden:gen`
> - 防陈旧守卫：`cloudflare/native-worker/test/golden-freshness.test.ts`（value + api 合同，
>   含确定性重放与结构下限）、`provider-slots-parity.test.ts`（13 场景逐条重放 + macOS fixture 派生）
>
> 迁移后实测（逐份复算，不是估算）：
>
> - `provider_slots_golden.json`：与 Python 产出**逐字节相同**（零 diff）。
> - macOS owner fixture：**语义等价**，386 行改动全部是 key 重排——生成器统一改为
>   排序键名输出（不排序时读模型调一下字段顺序就会让整份文件变成一个巨大的 diff）。
> - `value_golden.json`：语义差异只有三类——`backend_mode` / `canonical_store`
>   两个存储身份字段（原本就被 parity 的 `normalizeStoreMetadata` 掩掉）、
>   `source_status` / `sources` 的数组顺序（原本被 `sortedSourceRows` 掩掉），
>   以及 **14 处 `used_percent` / `remaining_percent` 由 `0.0` 变成 `0`**
>   （Python float 与 JS number 的 JSON 表示差异，值相等、下游解码无影响；
>   `test/golden/shape.ts` 的 `floatFields` 就是为它存在的）。两处掩码现在都不再需要。
> - `api_contract_golden.json`：差异正好等于原 `knownGoldenGaps` 清单——该清单已按预告删除。
>
> Python 侧已删除：`scripts/gen_value_golden.py`、`scripts/gen_provider_slots_golden.py`、
> `tests/test_value_golden_freshness.py`、`tests/test_provider_slots_parity.py`、
> `tests/test_api_contract.py`（含 #85 登记的那条 health counts 测试——
> Worker 侧 `web_surface.test.ts` 已有同口径的真实数值断言）。
>
> **注意**：`tests/fixtures/contract/api_contract_golden.json` 的 owner 现在是 Worker 测试，
> 但路径不在 `cloudflare/` 下，`scripts/verify.sh` 的 Worker 触发判据已相应加上该前缀。

原始记录（解除前）：

| fixture | 生成器 | 防陈旧守卫 | 删除后 |
| --- | --- | --- | --- |
| `cloudflare/native-worker/test/value_golden.json` | `scripts/gen_value_golden.py` → `tests/test_value_golden_freshness.py::_collect_records`（用 `build_snapshot` + `build_mobile_summary`） | `tests/test_value_golden_freshness.py` 3 条 | 变成**冻结快照**，无人能重新生成，陈旧不再会红 |
| `cloudflare/native-worker/test/provider_slots_golden.json` | `scripts/gen_provider_slots_golden.py` → `tests/test_provider_slots_parity.py::_collect_records` | `tests/test_provider_slots_parity.py::test_python_read_model_matches_provider_slots_golden` | 同上 |
| `tests/fixtures/contract/api_contract_golden.json` | `tests/test_api_contract.py`（起 Python server 实录） | 同一个文件 | 同上 |

所以本表里任何一条标「**由合同 fixture 接替**」的映射，**在生成器与防陈旧守卫迁到
Worker 侧之前都不成立**。否则 #74 做的事情正好是 #63 抓到的那个失效模式的放大版：
把活的守卫换成死的快照，测试继续全绿。

→ **#74 必须先交付 Worker 侧的 golden 生成器 + 防陈旧守卫，再删除 Python 生成端。**
（ADR 第八节已写明这一点，本表把它升级为逐条映射的前置条件。）

### 阻断 P2：`api_contract_golden.json` 在 Worker 侧只被弱比对

`parity.test.ts:71` 读了这份 golden，但**只对前 2 条（未认证的两条）做 `toEqual` 全字段比对**，
其余 14 条只校 `status` / `content_type` / `body.kind`。
Python 侧 `test_api_contract.py::test_current_api_contract_matches_golden` 是全量逐字段比对。

→ 直接把 `test_web_server.py` / `test_api_contract.py` 标成「由 API 合同接替」会高估接替强度。
本表对受影响条目已逐条标 ⚠️。

---

## 1.5 总控复核：两处事实需要更正

本表由分析代理产出后，总控逐条核实了其中影响决策的关键事实，发现两处需要更正。
**这两处都属于 grep 关键词选择导致的假阴性**——查不到不等于不存在，而假阴性看起来
正好像「发现了缺口」，会让 PM 为不存在的问题做决策。

### 更正 1：PM-3「Worker 无 payload 大小检查」——**不成立**

原文称 Worker 的 `index.ts` / `write-model.ts` 无任何大小检查（`MAX_` / `content-length` /
`byteLength` 零命中）。实测**两侧都有，且完全一致**：

```
cloudflare/native-worker/src/write-model.ts:620:  if (jsonBytes > 50 * 1024 * 1024) {
src/ai_usage_widget/ingest.py:95:        if len(payload_str.encode("utf-8")) > 50 * 1024 * 1024:
```

原 grep 词表匹配不到 `jsonBytes > 50 * 1024 * 1024` 这种写法。**PM-3 撤销，无需 PM 决策**；
`test_payload_too_large` 的归属改为「由 Worker 侧同等检查接替」，不是缺口。

### 更正 2：覆盖缺口第 1 条「认证 10 条」——**部分成立**

原文称 `ingest.test.ts` 里 `toBe(401)` 零命中，据此判定认证守卫整体缺失。
实测 Worker **读端点的认证有覆盖**，只是在另一个文件里：

```
web_surface.test.ts:65   toBe(401)
web_surface.test.ts:99   toBe(401)
web_surface.test.ts:113  /api/health        toBe(401)
web_surface.test.ts:332  /api/summary       toBe(401)
web_surface.test.ts:378  /api/mobile/summary toBe(401)
```

`ingest.test.ts` 里那个 401 只出现在注释里，不是断言。所以**成立的是窄版**：
`/ingest` **写端点**未带 token 时的行为在 Worker 侧无用例；读端点认证不缺。
缺口条数应按此重估，不是整组 10 条。

> 这两处更正不影响本表的**主结论**（阻断 P1 与「废弃仅 5 条」），但说明一件事：
> 本表第 9 节自陈的局限（未运行测试、未逐条打开 Worker 用例函数体）是实质性的，
> 表里所有 ⚠️ 判定在据以决策前都应当被同样地复核一遍。

---

## 2. 待 PM 决定的项清单

按需要 PM 拍板的顺序排列。实施代理不得自行替 PM 决定这些。

| # | 决策点 | 选项与后果 | 涉及测试 |
| --- | --- | --- | --- |
| **PM-1** | **`src/ai_usage_widget/static/` 静态资源目录去留与位置** | **实测事实**：该目录不是 `server.py` 的私产。`cloudflare/native-worker/src/static-assets.ts` 第 1 行写明「Generated from src/ai_usage_widget/static」，`cloudflare/native-worker/test/web_surface.test.ts:94` **直接从该目录读文件做逐字节比对**，`package.json:6` 的 `cf:pages:deploy` 也部署该目录。→ **目录不能随 `server.py` 删除。**<br>**走法 A（留在原地）**：8 条测试零改动保留（它们不 import 任何待删模块）。代价：Python 包里留一个与 Python 无关的资源目录，命名会误导。<br>**走法 B（搬到 `cloudflare/native-worker/static/`）**：8 条改 `STATIC` 路径常量后保留，**仍然不是废弃**；同时要改 `static-assets.ts` 的生成说明、`web_surface.test.ts:13` 的路径、`package.json` 的部署路径。<br>**两种走法都不产生「废弃」**，只影响改动量。 | `test_dashboard_static.py` 全部 8 条 + `test_web_server.py:705` |
| **PM-2** | **`collect-limits` 的本地 SQLite 落库要不要保留** | **实测事实**：`limits_runtime.py` 调 `write_limit_windows` 写本地库，但 `cli.py:633` 的 `push-limits` 用 `dry_run=True` 收集、直接推 `result.windows`，**不读本地库**；#72 剪断快照重建后，仓库内**没有任何本地读取方**。该表现在是只写不读。<br>**走法 A（保留）**：9 条 `test_limit_windows_store.py` 原样留 Python。<br>**走法 B（删除本地落库）**：9 条废弃，理由是「守护一个无消费者的本地表」。<br>**走法 C（并入 #73 `collector_store.py`）**：9 条迁移到 `collector_store` 的测试，行为需求不变、owner 换模块。 | `test_limit_windows_store.py` 9 条 + `test_limits_runtime.py` 中 2 条落库断言 |
| **PM-3** | **`ingest` payload 大小上限** | **实测事实**：Worker 的 `index.ts` / `write-model.ts` **没有任何 payload 大小检查**（`MAX_` / `content-length` / `byteLength` 全部零命中）。Python 侧 `test_payload_too_large` 是当前唯一守卫。<br>**走法 A**：Worker 补限额并迁移该测试。<br>**走法 B**：显式记为「由 Cloudflare 平台请求体上限兜底」，该条废弃并把理由写进架构文档。**不允许默认沉默删除。** | `test_ingest_contract.py:98` |
| **PM-4** | **`normalize.py` 的去留** | **实测事实**：`normalize.py` 的消费者只有 `server_services.py`（本轮删除）与 `collector.py`（ADR 5.4 判 legacy、随 #74 清理）。`pusher.py` **不 import 它**。→ #74 之后 `normalize.py` 会变成零消费者模块。ADR 5.3 把它列在「留在 Python（采集端）」，与实测不符。<br>**走法 A**：连同 `test_normalize.py` 一起删。<br>**走法 B**：确认还有未被发现的消费者后保留（需贴证据）。 | `test_normalize_ingest.py` 7 条 + （范围外）`test_normalize.py` |
| **PM-5** | **`supabase-sync.ts` 消费者** | ADR 裁决清单第 3 条：#74 开工前 PM 未指认消费者即默认删除。本表未覆盖 `supabase-sync.test.ts`（它不在 249 条 Python 测试里），但删除时它一并消失，需要 PM 明确签字。 | （TS 侧 2 条，不计入 249） |
| **PM-6** | **`test_version_contract_doc.py` 的文档合同去向** | Worker 侧**没有任何文档合同测试**。拆分后「服务端版本字段 / 呈现端版本字段 / 四态判定规则 / 严重度顺序 / 最低支持版本语义」的 owner 变成 `version-contract.ts`，这 8 条要么新建 `cloudflare/native-worker/test/version-contract-doc.test.ts`，要么整体废弃（等于放弃「文档与代码不一致会红」这条守卫）。 | `test_version_contract_doc.py` 8 条（见第 6.9 节逐条） |

---

## 3. 数量核对结果：249 对得上

逐文件 `grep -c "def test_"` 实测（本机，`1d7a856`）：

### 3.1 主体 188 / 9 文件

| 文件 | ADR 声称 | 实测 `grep -c` | 本表标注条数 | 一致 |
| --- | --- | --- | --- | --- |
| `tests/test_api_contract.py` | 2 | 2 | 2 | ✅ |
| `tests/test_web_server.py` | 18 | 18 | 18 | ✅ |
| `tests/test_server_services.py` | 15 | 15 | 15 | ✅ |
| `tests/test_ingest_contract.py` | 24 | 24 | 24 | ✅ |
| `tests/test_snapshot_builder.py` | 42 | 42 | 42 | ✅ |
| `tests/test_mobile_summary.py` | 25 | 25 | 25 | ✅ |
| `tests/test_snapshot_source_health.py` | 7 | 7 | 7 | ✅ |
| `tests/test_version_contract.py` | 40 | 40 | 40 | ✅ |
| `tests/test_version_contract_doc.py` | 15 | 15 | 15 | ✅ |
| **小计** | **188** | **188** | **188** | ✅ |

### 3.2 旁及 61 / 9 文件

| 文件 | ADR 声称 | 实测 `grep -c` | 本表标注条数 | 一致 |
| --- | --- | --- | --- | --- |
| `tests/test_normalize_ingest.py` | 7 | 7 | 7 | ✅ |
| `tests/test_provider_slots_parity.py` | 9 | 9 | 9 | ✅ |
| `tests/test_value_golden_freshness.py` | 3 | 3 | 3 | ✅ |
| `tests/test_storage_sqlite.py` | 10 | 10 | 10 | ✅ |
| `tests/test_d1_schema_migration.py` | 5 | 5 | 5 | ✅ |
| `tests/test_limit_windows_store.py` | 9 | 9 | 9 | ✅ |
| `tests/test_dashboard_static.py` | 8 | 8 | 8 | ✅ |
| `tests/test_limits_runtime.py` | 7 | 7 | 7 | ✅ |
| `tests/test_cli_verify_cloud.py` | 3（共 54） | 54，其中耦合 3 | 3 | ✅ |
| **小计** | **61** | **61** | **61** | ✅ |

**合计 188 + 61 = 249**，与 #74 门禁基数一致，本表逐条标注 249 条，不多不少。

### 3.3 但「61 旁及」这个口径已经过期 15 条

ADR 第 7.2 节的 61 是在 #71 / #72 落地**之前**统计的。实测当前 18 个文件的
`from ai_usage_widget...` import：

- `tests/test_dashboard_static.py`：**零 import**，只读 `src/ai_usage_widget/static/`。删除待删模块不会打断它。
- `tests/test_limits_runtime.py`：只 import `limits` / `limits_runtime`。`limits_runtime.py:10`
  **今天只 import `write_limit_windows`**，`snapshot_builder` 那条边已被 commit `1d7a856` 剪断
  （测试文件 91-93 行有注释记录）。删除待删模块不会打断它。

→ **真正会被删除打断的是 249 - 15 = 234 条**；另外 15 条属于「归属需要确认、但删除不会打断」。
本表仍然逐条标注全部 249 条（门禁要求如此），但把这 15 条标为 `留 P`，并在第 8 节记为 ADR 口径差异。

---

## 4. 归属词表与分布统计

### 4.1 归属词表

| 代码 | 含义 |
| --- | --- |
| **迁 W** | 迁移到 Worker 测试。括号内是目标文件；`🆕` 表示该文件存在但**需要新增用例**，`🆕文件` 表示需新建文件 |
| **合同** | 由跨实现合同 fixture 接替。括号内是 fixture 与具体记录/场景 |
| **废弃** | 随 Python 服务端一起消失，**理由必写** |
| **留 P** | 保留在 Python。要么是采集端 owner，要么与待删模块无关（可能需要删掉失效的 module 级 import） |
| **待定** | 拿不准或需 PM 决策，**卡点必写** |
| ⚠️ | **覆盖缺口**：本表声称迁移/接替，但 Worker 侧当前**没有**对应覆盖。删除即降覆盖 |

> 说明：任务书列了三个合同 fixture，实测仓库里跨实现合同 fixture 有**四份**——遗漏的是
> `cloudflare/native-worker/test/provider_slots_golden.json`（13 场景 × 2 端点 = 26 条记录，
> 由 `provider-slots-parity.test.ts` 逐场景消费）。它是 `test_snapshot_builder.py` 后 18 条与
> `test_mobile_summary.py` 槽位段落的主要接替者，本表把它算作合同 fixture。

### 4.2 分布统计（249 条）

下表由脚本从本文第 5–6 节的逐条表格中直接统计（不是估算），核对方式见第 9 节：

| 归属 | 条数 | 占比 |
| --- | --- | --- |
| 迁 W（迁移到 Worker 测试） | 146 | 58.6% |
| 合同（由合同 fixture 接替） | 44 | 17.7% |
| 留 P（保留在 Python） | 37 | 14.9% |
| 待定 | 17 | 6.8% |
| 废弃 | 5 | 2.0% |
| **合计** | **249** | 100% |

**废弃只有 5 条**，都在第 5.2 / 5.3 / 6.4 / 6.5 节，每条都写了理由。
「废弃」占比这么低是本表的主要结论之一：#74 删掉的 3989 行里，绝大多数行为**不是消失，
而是换 owner**——所以删除的真正代价不是「少了几个测试」，而是「146 条要在 Worker 侧有等价守卫」。

其中标 ⚠️（Worker 侧当前无对应覆盖）的共 **67 条**，加上阻断 P0 的 4 条待定，
共 **71 条**在删除时会造成真实覆盖下降。逐类见第 7 节。

逐文件 ⚠️ 分布：

| 文件 | 条数 | ⚠️ |
| --- | --- | --- |
| `test_api_contract.py` | 2 | 1 |
| `test_web_server.py` | 18 | 6 |
| `test_server_services.py` | 15 | 1 |
| `test_ingest_contract.py` | 24 | 7 |
| `test_snapshot_builder.py` | 42 | 15 |
| `test_mobile_summary.py` | 25 | 8 |
| `test_snapshot_source_health.py` | 7 | 2 |
| `test_version_contract.py` | 40 | 14 |
| `test_version_contract_doc.py` | 15 | 7 |
| `test_normalize_ingest.py` | 7 | 1 |
| `test_provider_slots_parity.py` | 9 | 1 |
| `test_value_golden_freshness.py` | 3 | 0 |
| `test_storage_sqlite.py` | 10 | 0 |
| `test_d1_schema_migration.py` | 5 | 0 |
| `test_limit_windows_store.py` | 9 | 1 |
| `test_dashboard_static.py` | 8 | 0 |
| `test_limits_runtime.py` | 7 | 0 |
| `test_cli_verify_cloud.py`（3/54） | 3 | 3 |
| **合计** | **249** | **67** |

---

## 5. 主体 188 条逐条映射

### 5.1 `tests/test_api_contract.py`（2 条，owner `server.py`）

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 90 | `test_current_api_contract_matches_golden` | Python server 实录全部合同请求，与 `api_contract_golden.json` 逐字段比对；同时是该 golden 的**生成器与防陈旧守卫** | **迁 W** ⚠️（`🆕文件 api-contract-golden.test.ts`） | 现有 `parity.test.ts:71` 只对 2 条未认证记录做全字段 `toEqual`，其余 14 条只校 status/content-type/kind（阻断 P2）。必须在 Worker 侧建等强度的实录 + 比对，否则合同强度下降 |
| 103 | `test_contract_golden_contains_no_sensitive_runtime_data` | golden 文件正文不得含 token / `/Users/` / `.claude` / `.codex` / SSH 私钥字样 | **留 P** | 本用例只读文件、不碰任何待删模块；只需删掉模块级 `from ai_usage_widget.server import start_test_server`。若 golden 随 P1 迁到 Worker 侧生成，则随之改成 TS 断言 |

### 5.2 `tests/test_web_server.py`（18 条，owner `server.py`）

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 82 | `test_get_summary_empty_state` | 空库时 `/api/summary` 返回合法空快照而不是 500 | **迁 W** ⚠️（`web_surface.test.ts` 🆕） | Worker 全部读路径用例都跑在已 seed 的库上，未见空库用例 |
| 92 | `test_summary_requires_auth` | 未登录读 `/api/summary` 被拒 | **合同**（`api_contract_golden.json` → `summary-requires-auth`） | `parity.test.ts:71` 对该记录做全字段 `toEqual`，是接替强度最强的两条之一 |
| 99 | `test_health_requires_auth_and_returns_low_cost_status` | `/api/health` 需认证，且返回低成本状态而非重算 | **迁 W**（`web_surface.test.ts:111`「protects health with the same session cookie and keeps the M0 response shape」） | 已覆盖 |
| 116 | `test_ingest_auth_failure` | `/ingest` 缺 token / 错 token → 401 | **迁 W** ⚠️（`ingest.test.ts` 🆕） | `index.ts:90` 已实现 401，但 `ingest.test.ts` 里 `toBe(401)` **零命中**；写路径认证在 Worker 侧无断言 |
| 137 | `test_ingest_accepts_rotated_token_specs` | 轮换期多 token（`AIUSAGE_TOKEN_SPECS`）在 **写路径**同样有效 | **迁 W** ⚠️（`ingest.test.ts` 🆕） | Worker 侧只有 `web_surface.test.ts:369` 用第二个 token 走**读**路径，写路径未覆盖 |
| 162 | `test_ingest_success_and_query_summary` | 推送成功后 summary 能读到累加 token 与设备状态 | **迁 W**（`ingest.test.ts:85` / `:692`） | 已覆盖，且 `:692` 是采集端真实 payload 回放 |
| 194 | `test_summary_returns_limits_from_canonical_store` | summary 的额度来自 canonical 存储而非临时值 | **合同**（`value_golden.json` → `summary-week-observed-limits`） | golden 有 observed-limits 记录 |
| 226 | `test_ingest_limits_requires_auth` | `/ingest-limits` 需认证 | **迁 W** ⚠️（`ingest.test.ts` 🆕） | 同 116，路由共用同一段认证代码但无断言 |
| 257 | `test_ingest_limits_accepts_authorized_payload_and_updates_summary` | 授权额度推送落库并反映到 summary | **迁 W**（`ingest.test.ts:206` / `:469` / `:508`） | 已覆盖 |
| 315 | `test_summary_period_query_uses_period_parameter` | `?period=` 真的改变聚合窗口而不只换 label | **合同**（`value_golden.json` → `summary-today/week/month/all`） | golden 四周期各一条记录 |
| 356 | `test_mobile_summary_requires_auth_and_returns_app_contract` | 移动端只读 API 的稳定 DTO 合同 | **合同**（`api_contract_golden.json` → `mobile-summary-requires-auth` 全字段 + `value_golden.json` → `mobile-summary-*`） | 认证面全字段比对，DTO 面 value golden 比对 |
| 498 | `test_mobile_summary_periods_return_distinct_live_windows` | 四周期返回**真实不同**的聚合窗口，不是换 label | **迁 W** ⚠️（`parity.test.ts` 🆕） | value golden 只保证「等于当时的值」，**不保证四条互不相同**；`parity.test.ts:319` 只测查询被周期截断。「四周期必须互不相同」这条不变量在 Worker 侧无对应断言 |
| 600 | `test_mobile_summary_does_not_overwrite_canonical_latest_snapshot` | 请求移动端摘要不得覆写 `latest.json` | **废弃** | 断言的是 Python 服务端的 `latest.json` 文件副作用。Worker 无 `latest.json` 这个产物，D1 是唯一存储，读路径结构上不写库——该副作用在新架构里不存在 |
| 621 | `test_summary_groups_machine_users_and_filters_user_report` | 同机多 OS 用户在 by-machine 下作为 users 展示，用户报表复用 summary schema | **合同** ⚠️（`value_golden.json` → `by_machine` + `summary-week-account-filter`） | golden 有 `by_machine`（21 处）与 account 过滤记录，但 `seed.sql` **只有一条 `os_identities`**，`os_users` 在 golden 里零命中 → 「同机多 OS 用户」这一半没有被真正回放 |
| 676 | `test_get_dashboard_html` | `/` 与 `/dashboard` 返回 index.html | **迁 W**（`web_surface.test.ts:70`） | 已覆盖 |
| 690 | `test_dashboard_static_assets` | dashboard 的 CSS/JS 静态资源可加载 | **迁 W**（`web_surface.test.ts:94`，逐字节比对 4 个资源） | 已覆盖，且强度高于 Python 侧 |
| 705 | `test_dashboard_limits_static_hooks` | 静态页面里存在额度区块所需的 DOM 钩子 | **留 P**（合并进 `test_dashboard_static.py`） | 本质是对 `static/index.html` 内容的断言，不需要 HTTP；投递正确性已由 `web_surface.test.ts:94` 逐字节保证。受 **PM-1** 影响的只是路径常量 |
| 719 | `test_login_sets_cookie_for_dashboard` | 浏览器登录后 cookie 可访问 dashboard | **迁 W**（`web_surface.test.ts:42` / `:58` / `:70`） | 已覆盖，含「Python 兼容的 session cookie」与错误页 |

### 5.3 `tests/test_server_services.py`（15 条，owner `server_services.py`）

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 57 | `test_ingest_service_preserves_summary_contract` | ingest 服务落库后 summary 合同不变 | **迁 W**（`ingest.test.ts:85` / `:100`） | 已覆盖 |
| 84 | `test_ingest_ignores_the_dropped_ccusage_daily_status_field`（#78 前名为 `..._with_optional_..._keeps_source_health_ok`） | 老版本采集端发来该字段时被忽略、不写进来源健康 | **迁 W**（`ingest.test.ts`「老版本采集端仍在发的 ccusage_daily_status 被当未知字段忽略」） | 阻断已解除（#78 摘除该字段）。断言方向已反转：从「错误信息被回填」改成「错误信息为空」 |
| 144 | `test_ingest_retry_does_not_count_as_a_second_full_scan` | 重试不被当成第二次完整扫描（影响权威删除判定） | **迁 W**（`ingest.test.ts:519`「requires two complete matching scans before verification and authoritative deletion」+ `:652`） | 已覆盖 |
| 214 | `test_mobile_summary_service_reuses_summary_snapshot` | 移动端服务复用同一份 summary 快照，不重算 | **废弃** | 断言的是 Python 服务层内部的对象复用，不是对外行为。Worker 的 `buildMobile` 结构上就建立在 `buildSummary` 之上（`read-model.ts:419`），两端口径一致性由 `value_golden.json` 的 summary/mobile **成对**记录守护 |
| 238 | `test_health_service_reads_existing_snapshot_without_rebuilding` | health 读现成快照，不触发重算 | **废弃** | 「读 `latest.json` 而不重建」是 Python 的快照文件模型特有的性能契约。Worker 的 `/api/health` 直接查 D1，没有快照文件；health 的形状与「不读归档表」由 `web_surface.test.ts:111` / `:150` 守 |
| 281 | `test_ingest_reports_current_version_state_for_an_up_to_date_collector` | 最新采集端上报 → `current` | **迁 W**（`version-contract.test.ts:82`） | 已覆盖 |
| 300 | `test_ingest_without_collector_release_is_accepted_but_marked_unknown` | 缺版本块降级为 unknown，不拒收 | **迁 W**（`version-contract.test.ts:122`） | 已覆盖 |
| 309 | `test_ingest_reports_update_available_without_rejecting_the_data` | 落后但可用 → `update_available` 且数据照收 | **迁 W** ⚠️（`version-contract.test.ts` 🆕） | Worker 有 unsupported 拒收用例（`:168`）与四态读取面用例（`version_read_surface.test.ts:292`），但**没有**「ingest 返回 update_available 且不拒收」的写路径用例 |
| 325 | `test_unsupported_collector_is_rejected_with_an_explicit_error_not_a_silent_200` | 不兼容采集端显式报错，不是静默 200 | **迁 W**（`version-contract.test.ts:168`） | 已覆盖 |
| 344 | `test_rejected_unsupported_upload_is_not_silently_dropped_into_the_store` | 被拒的上传不得留下任何库写入 | **迁 W**（`version-contract.test.ts:181`） | 已覆盖 |
| 359 | `test_health_service_exposes_server_versions_and_devices_needing_attention` | `/api/health` 暴露服务端版本与需关注设备 | **迁 W**（`version_read_surface.test.ts:411`） | 已覆盖 |
| 405 | `test_version_fields_never_leak_a_token_or_absolute_path_into_any_output` | 任何输出里不得泄露 token / 绝对路径 | **迁 W**（`version-contract.test.ts:293`） | 已覆盖 |
| 451 | `test_summary_snapshot_lists_outdated_devices_with_deterministic_ordering` | 过期设备清单顺序确定 | **迁 W**（`version-contract.test.ts:254` + `version_read_surface.test.ts:356`） | 已覆盖 |
| 492 | `test_source_without_reported_version_shows_up_as_unknown_in_the_snapshot` | 没报版本的来源是 unknown，不假定合规 | **迁 W**（`version_read_surface.test.ts:308`） | 已覆盖 |
| 513 | `test_limits_ingest_service_preserves_response_shape` | `/ingest-limits` 响应结构稳定 | **迁 W**（`ingest.test.ts:206` 系列） | 已覆盖 |

### 5.4 `tests/test_ingest_contract.py`（24 条，owner `ingest.py`）

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 22 | `test_valid_payload_parsing` | 合法 payload 能解析成 `IngestRequest` | **合同**（`collector_payload_fixture.json` → `ok-full-collection`，由 `ingest.test.ts:692` / `:868` 消费） | fixture 由 owner 模块 `pusher.py` 产出，接替强度高于原测试 |
| 37 | `test_missing_schema_version` | 缺 `schema_version` 校验失败 | **迁 W** ⚠️（`ingest.test.ts` 🆕） | `write-model.ts:623/626` 已实现，但 Worker 测试无对应断言 |
| 45 | `test_missing_required_fields` | 缺任一必填字段校验失败 | **迁 W** ⚠️（`ingest.test.ts` 🆕） | 同上，`write-model.ts:623` 已实现无断言 |
| 56 | `test_prevent_sensitive_logs_path_or_content` | payload 含 `.claude` / `.codex` 原始日志路径或内容时拦截 | **迁 W**（`ingest.test.ts:457`「rejects sensitive ingest and limits fields」） | 已覆盖 |
| 72 | `test_prevent_ssh_parameters` | payload 含 SSH 私钥 / 配置关键字时拒收 | **迁 W** ⚠️（`ingest.test.ts:457` 需确认含 SSH 关键字用例） | 同一条 Worker 用例，但是否覆盖 SSH 关键字这一支未逐条核实 |
| 80 | `test_auth_success` | 正确 token 通过 | **迁 W**（`web_surface.test.ts:330` + 全部 Worker 用例隐式） | 已覆盖 |
| 85 | `test_auth_failed_missing_token` | 缺 token 拒绝 | **迁 W** ⚠️（`ingest.test.ts` 🆕） | 同 `test_web_server.py:116`，写路径 401 零断言 |
| 91 | `test_auth_failed_wrong_token` | 错 token 拒绝 | **迁 W** ⚠️（`ingest.test.ts` 🆕） | 同上 |
| 98 | `test_payload_too_large` | payload 超限报错 | **待定 → PM-3** | Worker 无任何大小上限实现。删除即失去该守卫 |
| 108 | `test_accepts_valid_mswusage_codex_hourly_report` | 合法 mswusage codex 小时报告被接受 | **迁 W**（`ingest.test.ts:85` / `:692`） | 已覆盖 |
| 126 | `test_accepts_usage_ledger_accuracy_evidence` | ledger 准确性证据被接受 | **迁 W**（`ingest.test.ts:519`） | 已覆盖 |
| 147 | `test_rejects_invalid_mswusage_codex_hourly_report_shape` | 非法 mswusage 形状被拒 | **迁 W** ⚠️（`ingest.test.ts` 🆕） | Worker 有 `WriteValidationError` 路径，但无该形状的拒绝断言 |
| 156 | `test_accepts_usage_hourly_facts` | `usage_hourly_facts` 被接受并落库 | **迁 W**（`ingest.test.ts:85`） | 已覆盖 |
| 190 | `test_ignores_the_dropped_ccusage_daily_status_field`（#78 把原先 3 条合并成这 1 条） | 该字段的四种形态一律既不报错也不解析 | **迁 W**（`ingest.test.ts`「老版本采集端仍在发的 ccusage_daily_status 被当未知字段忽略」） | 阻断已解除（#78 摘除该字段）。原「非 object 被拒」「缺键被拒」两条**故意废弃**：Worker 对未知顶层字段本来就不拒，Python 侧再拒就是两个实现不一致 |
| 224 | `test_rejects_usage_hourly_facts_missing_required_field` | hourly fact 缺必填字段被拒 | **迁 W** ⚠️（`ingest.test.ts` 🆕） | Worker 实现存在，断言缺失 |
| 233 | `test_accepts_collector_release_and_flattens_it` | 版本块被接受并扁平化 | **迁 W**（`version-contract.test.ts:82`） | 已覆盖 |
| 256 | `test_missing_collector_release_degrades_instead_of_failing` | 缺整块只降级不 500 | **迁 W**（`version-contract.test.ts:122`） | 已覆盖 |
| 265 | `test_partial_collector_release_keeps_known_fields_and_nulls_the_rest` | 部分块保留已知字段、其余置 null | **迁 W**（`version-contract.test.ts:133`） | 已覆盖 |
| 275 | `test_rejects_non_object_collector_release` | 非 object 版本块是显式合同错误 | **迁 W**（`version-contract.test.ts:148`） | 已覆盖（同一条「rejects an illegal collector_release value」） |
| 285 | `test_rejects_unknown_key_inside_collector_release` | 未知 key 不得搭车 | **迁 W**（`version-contract.test.ts:45` / `:148`） | 已覆盖 |
| 294 | `test_rejects_credential_or_path_shaped_version_values_without_echoing_them` | 凭据/路径形状的版本值被拒且不回显 | **迁 W**（`version-contract.test.ts:293`） | 已覆盖 |
| 317 | `test_rejects_sensitive_strings_inside_mswusage_report` | mswusage 报告体内的敏感串被拒 | **迁 W**（`ingest.test.ts:457`） | 已覆盖 |

### 5.5 `tests/test_snapshot_builder.py`（42 条，owner `snapshot_builder.py`）

**前 24 条：快照 / 台账 / 额度 / 周期 / 趋势**

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 85 | `test_build_snapshot_success` | 从库生成快照的基础结构 | **合同**（`value_golden.json` → 全部 `summary-*`） | 结构与值逐字段比对 |
| 146 | `test_build_snapshot_uses_account_hourly_ledger_for_user_visible_total` | 用户可见总量以账户小时台账为准 | **迁 W**（`parity.test.ts:382`「uses usage_hourly_facts as the mobile summary period total when stale daily rows disagree」） | 已覆盖 |
| 231 | `test_ledger_partial_agent_keeps_all_daily_residual` | 台账只覆盖部分 agent 时保留 all-daily 残差 | **迁 W** ⚠️（`parity.test.ts:466` 语义相近但不同） | `:466` 守的是「不把归档 all-agent 日残差混进 canonical facts」；本条守的是「**保留**残差」。方向相反的两条不变量，不能互相顶替 |
| 302 | `test_build_snapshot_includes_known_ai_accounts_without_hourly_facts` | 已知 AI 账户即使没有小时事实也要出现 | **合同** ⚠️（`provider_slots_golden.json` → `03-quota-without-usage`） | 场景 03 覆盖「有额度无用量」，但「`ai_accounts` 表里有行、事实表为空」这条具体路径未单独回放 |
| 355 | `test_account_hourly_mixed_confidence_is_visible_per_account` | 同账户混合 confidence 逐账户可见 | **迁 W** ⚠️（`parity.test.ts` 🆕） | Worker 侧无对应用例 |
| 422 | `test_account_hourly_period_filter_uses_configured_timezone` | 周期过滤用配置时区而非 UTC | **迁 W**（`parity.test.ts:319`「bounds the hourly-fact query to the requested display period」） | 已覆盖 |
| 483 | `test_build_snapshot_includes_observed_limits` | observed 额度进入快照 | **合同**（`value_golden.json` → `summary-week-observed-limits`） | 已覆盖 |
| 545 | `test_build_snapshot_keeps_multi_account_limits` | 同 provider 多账户额度都保留 | **迁 W** ⚠️（`ingest.test.ts` / `parity.test.ts` 🆕） | `seed.sql` 只有 **1 条** `limit_windows`，value golden 无法回放多账户；Worker 测试 `multi_account` 零命中 |
| 606 | `test_build_snapshot_keeps_best_limit_window_per_source_provider_and_window` | 每 source×provider×window 只留最优窗口（读侧择优） | **迁 W** ⚠️（`parity.test.ts` 🆕） | `read-model.ts:1341 bestLimitWindows` 已实现；Worker 侧只测了**写侧**对账（`ingest.test.ts:206/228/258`），读侧择优无用例 |
| 680 | `test_build_snapshot_filters_old_active_limits_cache_from_effective_windows` | 陈旧 active 缓存不得进入有效窗口 | **迁 W**（`ingest.test.ts:487`「rejects cached or expired limits pretending to be current」） | 已覆盖 |
| 738 | `test_build_snapshot_excludes_expired_limit_windows` | 过期窗口被排除 | **合同**（`provider_slots_golden.json` → `06-expired-official-quota`） | 已覆盖 |
| 803 | `test_failed_limits_do_not_break_usage_summary` | 额度失败不影响用量摘要 | **合同**（`provider_slots_golden.json` → `07-provider-failed-after-success`） | 已覆盖 |
| 845 | `test_latest_provider_failure_immediately_marks_previous_success_unavailable` | 最新失败立刻让此前成功失效 | **迁 W**（`parity.test.ts:346`「fails closed immediately when a provider failure follows a successful quota read」） | 已覆盖 |
| 880 | `test_source_health_staleness_and_never_seen` | stale / never-seen / 今日零用量但在线 三态区分 | **迁 W**（`web_surface.test.ts:251` / `:263`） | 已覆盖（含 ok / failed / stale） |
| 956 | `test_build_snapshot_week_period_aggregates_date_range` | week 按真实日期范围聚合并输出趋势序列 | **合同**（`value_golden.json` → `summary-week`） | 已覆盖 |
| 1071 | `test_today_period_uses_calendar_day_hourly_trend` | today 用所选日 00:00–23:00 小时事实 | **合同**（`value_golden.json` → `summary-today`，`granularity` 14 处） | 已覆盖 |
| 1141 | `test_today_period_spreads_ccusage_blocks_across_overlapping_hours` | 5 小时 block 分摊到覆盖的小时，上午用量不消失 | **废弃**（#90 判定）| ~~`read-model.ts:902 addBlockToHourBuckets`~~ **已于 #90 删除**：`blockRows` 恒为空数组、`usage_blocks` 表在读模型里从未被查询，该函数不可达。`parity.test.ts` 那条「不混入归档 block 快照」也是**恒真**断言，已一并删除。采集端仍在白采 blocks，见 #91 |
| 1218 | `test_today_period_dedupes_cumulative_ccusage_block_snapshots` | 累计式 block 快照去重 | **废弃**（#90 判定）| ~~`read-model.ts:941 dedupeCumulativeBlockRows`~~ **已于 #90 删除**：同上，不可达 |
| 1313 | `test_codex_drift_does_not_create_current_hour_residual_spike` | codex 漂移不制造当前小时假尖峰 | **迁 W** ⚠️（`parity.test.ts` 🆕） | `read-model.ts:1070 codexHourlyContext` 已实现；Worker 侧 `drift` 只在 `ingest.test.ts`（写侧）命中，读侧无用例 |
| 1374 | `test_codex_drift_with_all_daily_baseline_does_not_double_count_trend` | all-daily 基线下漂移不重复计数 | **迁 W** ⚠️（`parity.test.ts` 🆕） | 同上 |
| 1435 | `test_today_hourly_trend_is_capped_to_period_total_when_hourly_exceeds_daily` | 小时序列超过日总量时按比例压回 | **迁 W** ⚠️（`parity.test.ts` 🆕） | `read-model.ts:1014 capTodayHourlyToPeriodTotals` 已实现；Worker 测试目录 `cap` **零命中** |
| 1500 | `test_by_machine_groups_os_accounts_under_same_machine` | 同物理机不同 OS 用户在 by-machine 下作为 users | **合同** ⚠️（`value_golden.json` → `by_machine`） | `seed.sql` 只有一条 `os_identities`，`os_users` 在 golden 零命中 → 分组这一半没被回放 |
| 1575 | `test_by_machine_includes_zero_usage_source_identity_user` | 只有身份没有用量的用户也挂在机器下 | **合同** ⚠️（同上） | 同上 |
| 1627 | `test_source_status_includes_latest_source_identity` | 健康状态携带 host/user 身份 | **迁 W**（`web_surface.test.ts:214` / `:251`） | 已覆盖 |

**后 18 条：provider 槽位（`TestSnapshotProviderSlots`）**

主接替者是 `provider_slots_golden.json`（13 场景 × 2 端点），由 `provider-slots-parity.test.ts` 逐场景消费。

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 1787 | `test_provider_slots_expose_claude_usage_and_quota_as_independent_fields` | usage 与 quota 是两个独立字段 | **合同**（PS `01-usage-and-quota`） | 已覆盖 |
| 1825 | `test_provider_slots_keep_claude_usage_when_official_quota_is_stale` | 官方额度陈旧时用量仍保留 | **合同**（PS `08-stale-official-with-local-estimate`） | 已覆盖 |
| 1859 | `test_provider_slots_hide_expired_official_quota_but_keep_last_verified_at` | 过期额度隐藏但保留最近验证时间 | **合同**（PS `06-expired-official-quota`） | 已覆盖 |
| 1891 | `test_provider_slots_keep_claude_quota_when_claude_usage_is_absent` | 无用量时额度仍展示 | **合同**（PS `03-quota-without-usage`） | 已覆盖 |
| 1920 | `test_provider_slots_report_missing_usage_and_missing_quota_without_facts` | 两边都没有时报 missing | **合同**（PS `04-neither`） | 已覆盖 |
| 1933 | `test_codex_limit_window_never_occupies_claude_quota_slot` | codex 窗口不得占 claude 槽位 | **合同**（PS `05-codex-quota-only`） | 已覆盖 |
| 1968 | `test_last_verified_at_ignores_local_estimate_rows` | 本地估算不得冒充官方验证时间 | **合同**（PS `08` + `09`，由 `test_golden_never_borrows_local_estimate_freshness_for_official_quota` 锁死） | 已覆盖 |
| 2012 | `test_last_verified_at_belongs_to_the_reported_quota_source` | 验证时间必须与同对象的 source_id/source_type 一致 | **合同**（PS `08`） | 已覆盖 |
| 2054 | `test_local_estimate_only_provider_reports_no_official_verification` | 只有本地估算时 → unverified 且无验证时间 | **合同**（PS `09-local-estimate-only`） | 已覆盖 |
| 2085 | `test_last_verified_at_only_counts_successful_official_observations` | 非 observed 的行不算一次成功核对 | **合同**（PS `10-estimated-observation-newer-than-official`） | 已覆盖 |
| 2127 | `test_last_verified_at_ignores_failed_official_probes` | 失败探测不推进验证时间 | **合同**（PS `07-provider-failed-after-success`） | 已覆盖 |
| 2212 | `test_usage_slots_attribute_aggregate_agent_by_canonical_ai_provider` | `agent='all'` 时按 `ai_provider` 归属 | **合同**（PS `11-aggregate-agent-with-canonical-provider`） | 场景 SQL 实测含 `'all'` |
| 2223 | `test_usage_slots_attribute_unknown_agent_by_canonical_ai_provider` | `agent='unknown'` 时同样不丢用量 | **迁 W** ⚠️（`provider_slots` 🆕场景 SQL） | 13 个场景 SQL 里 **`'unknown'` 零命中**。此归属路径在 Worker 侧无回放 |
| 2233 | `test_usage_slots_attribute_anthropic_provider_to_claude` | `ai_provider='anthropic'` 归到 claude 槽 | **迁 W** ⚠️（`provider_slots` 🆕场景 SQL） | 场景 SQL 里 **`'anthropic'` 零命中** |
| 2240 | `test_unattributable_usage_is_reported_instead_of_silently_missing` | 完全无法归属的用量必须被点名 | **迁 W** ⚠️（`provider_slots` 🆕场景 SQL） | 场景 13 是「有 provider 无槽位」（antigravity），**不是**「无 canonical provider」。这条不变量在 Worker 侧无回放 |
| 2274 | `test_provider_usage_coverage_accounts_for_every_summary_token` | 覆盖率必须解释掉每一个 token（守恒） | **合同**（PS 全部 26 条记录的 `provider_usage_coverage`）+ 见 6.2 的守恒断言迁移 | 守恒断言本身在 `test_provider_slots_parity.py:49`，需一并迁 W |
| 2316 | `test_third_party_provider_usage_is_named_instead_of_hidden_in_attributed` | 第三方 provider 必须点名不得藏进 attributed | **合同**（PS `13-third-party-provider-without-slot`） | 已覆盖 |
| 2338 | `test_naive_limit_timestamps_fail_closed_instead_of_crashing` | 缺时区的时间戳 fail closed 而不是 500 | **合同**（PS `12-naive-limit-timestamps`） | 已覆盖 |

### 5.6 `tests/test_mobile_summary.py`（25 条，owner `mobile_summary.py`）

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 10 | `test_mobile_trend_points_preserve_agent_segments_and_unknown_conservation` | 趋势点保留 agent 分段且 unknown 守恒 | **迁 W**（`mobile-summary.test.ts:6`「groups gpt agents into Codex while preserving every point total」） | 已覆盖 |
| 47 | `test_stale_provider_keeps_safe_source_and_update_without_percentages` | 陈旧 provider 保留安全身份、不露百分比 | **迁 W**（`mobile-summary.test.ts:36`） | 已覆盖 |
| 67 | `test_provider_windows_never_mix_sources` | 不同来源的额度窗口不得混合 | **迁 W**（`mobile-summary.test.ts:46`） | 已覆盖 |
| 91 | `test_explicit_provider_failure_hides_previous_current_percentages` | 显式失败后立刻隐藏旧百分比 | **迁 W**（`mobile-summary.test.ts:60`） | 已覆盖 |
| 111 | `test_mobile_summary_only_returns_effective_quota_windows` | 只返回有效额度窗口 | **合同**（`value_golden.json` → `mobile-summary-week-observed-limits`） | 已覆盖 |
| 172 | `test_mobile_summary_exposes_safe_freshness_metadata` | 暴露安全的新鲜度元数据 | **迁 W**（`mobile-summary.test.ts:70`「hides stale remote windows while preserving the last trusted update」） | 已覆盖 |
| 202 | `test_limits_windows_only_include_official_observed_ok_rows` | 只有 `official && observed && ok` 才进窗口 | **合同**（PS `08` / `09` / `10`） | 这是 AGENTS.md 的官方额度红线，PS 场景直接锁死 |
| 278 | `test_filters_expired_short_quota_windows_and_keeps_fresh_weekly` | 过期短窗被过滤、新鲜周窗保留 | **合同**（PS `06-expired-official-quota` mobile 记录） | 已覆盖 |
| 324 | `test_keeps_fresh_short_quota_window_for_every_period` | 每个周期都保留新鲜短窗 | **合同** ⚠️（`value_golden.json` → `mobile-summary-*` 四周期） | golden 只有一条 limit window，「每个周期都保留」这条跨周期不变量未被真正回放 |
| 354 | `test_filters_stale_official_window_even_when_reset_is_still_in_future` | reset 未到也要按陈旧过滤 | **合同**（PS `08-stale-official-with-local-estimate` mobile） | 已覆盖 |
| 382 | `test_naive_short_quota_reset_does_not_crash_period_summary` | 缺时区的 reset 不导致崩溃 | **合同**（PS `12-naive-limit-timestamps` mobile） | 已覆盖 |
| 410 | `test_adds_safe_account_and_plan_labels_to_quota_windows` | 额度窗口带安全的账户/套餐标签 | **合同**（`value_golden.json`，`account_plan_label` 21 处 / `account_label` 21 处） | 已覆盖 |
| 460 | `test_uses_safe_ai_accounts_when_hourly_usage_is_empty` | 小时用量为空时回落 `ai_accounts` | **迁 W** ⚠️（`mobile-summary.test.ts` 🆕） | Worker `mobile-summary.ts:436 accountContextFrom` 已实现，无对应用例；PS `03/04` 场景不覆盖标签回落 |
| 500 | `test_maps_openai_ai_account_metadata_to_codex_quota` | openai 账户元数据映射到 codex 额度 | **迁 W** ⚠️（`mobile-summary.test.ts` 🆕） | 同上 |
| 541 | `test_merges_same_ai_account_metadata_from_hourly_and_account_registry` | 两个来源的同一账户元数据合并 | **迁 W** ⚠️（`mobile-summary.test.ts` 🆕） | `mobile-summary.ts:473 mergeAccountContext` 已实现，无用例 |
| 588 | `test_redacts_unsafe_account_labels` | 不安全账户标签被脱敏 | **迁 W** ⚠️（`mobile-summary.test.ts` 🆕） | `mobile-summary.ts:488 safeAccountLabel` 已实现；Worker 测试目录 `redact` 只在 `version-contract.test.ts` 命中，移动端脱敏无用例。**这是安全相关的覆盖缺口** |
| 621 | `test_humanizes_safe_unknown_plan_labels_without_internal_separators` | 未知套餐名人性化且不漏内部分隔符 | **迁 W** ⚠️（`mobile-summary.test.ts` 🆕） | `mobile-summary.ts:500 safePlanLabel` / `:517 titlePlanPart` 已实现，无用例 |
| 650 | `test_sources_only_include_non_zero_contributors_for_selected_period` | 来源列表只含该周期非零贡献者 | **合同**（`value_golden.json` → `mobile-summary-*`） | 已覆盖 |
| 676 | `test_failed_zero_source_remains_available_for_health_context` | 失败的零用量来源仍保留供健康上下文 | **迁 W**（`web_surface.test.ts:263`「keeps dashboard and mobile source health on current per-source states, including ok, failed, and stale sources」） | 已覆盖 |
| 699 | `test_os_user_breakdown_filters_zero_token_users` | OS 用户拆分过滤零 token 用户 | **合同** ⚠️（`value_golden.json`） | `os_users` 在 golden 零命中（seed 只有一个 OS 身份） |
| 724 | `test_sources_empty_when_every_contributor_is_zero` | 全零时来源列表为空 | **迁 W** ⚠️（`mobile-summary.test.ts` 🆕） | 无空库/全零用例 |
| 760 | `test_mobile_summary_passes_through_provider_slots_unchanged` | 槽位原样透传，移动端不重定义 | **合同**（PS 全部 13 条 `*:mobile-summary` 记录） | 已覆盖，且是 PS golden 存在的主要理由 |
| 819 | `test_mobile_provider_slots_default_to_missing_when_snapshot_has_none` | 快照无槽位时默认 missing | **合同**（PS `04-neither:mobile-summary`） | 已覆盖 |
| 832 | `test_mobile_missing_quota_slot_never_leaks_percentages_or_reset` | missing 槽位不得带百分比/reset | **合同**（PS，由 `test_golden_missing_quota_never_carries_percentages_or_reset` 逐条扫描锁死） | 已覆盖 |
| 871 | `test_missing_usage_status_is_not_recomputed_from_token_count` | missing 状态不得由 token 数反推重算（展示层零口径） | **合同**（PS `02` / `04` mobile 记录） | 已覆盖 |

### 5.7 `tests/test_snapshot_source_health.py`（7 条，owner `snapshot_source_health.py`）

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 11 | `test_build_source_status_keeps_stale_ok_and_never_seen_contract` | stale / ok / never-seen 三态合同 | **迁 W**（`web_surface.test.ts:251` / `:263`） | 已覆盖 |
| 48 | `test_build_source_status_respects_machine_and_account_filters` | 机器/账户过滤生效 | **合同**（`value_golden.json` → `summary-week-machine-filter` / `summary-week-account-filter`） | 已覆盖 |
| 69 | `test_build_source_status_keeps_machine_separate_from_network_host` | 展示机器名与网络 host 分离 | **迁 W** ⚠️（`web_surface.test.ts` 🆕） | Worker `read-model.ts:428 fetchSourceIdentities` 已实现；`web_surface.test.ts:214` 只测生产身份一致性，machine≠host 这条无用例 |
| 118 | `test_version_state_is_derived_for_every_source_with_a_reported_version` | 每个报了版本的来源都推出状态 | **迁 W**（`version_read_surface.test.ts:274` / `:292`） | 已覆盖 |
| 128 | `test_source_that_never_reported_a_version_is_unknown_not_assumed_compliant` | 没报版本 = unknown，不假定合规 | **迁 W**（`version_read_surface.test.ts:308`） | 已覆盖 |
| 135 | `test_version_block_keeps_a_stable_key_set_for_downstream_consumers` | 版本块 key 集合稳定 | **迁 W**（`version_read_surface.test.ts:274`「exposes the full Python-equivalent version block on every /api/summary source_status entry」） | 已覆盖 |
| 151 | `test_version_block_is_omitted_when_no_version_data_is_supplied_at_all` | 完全没有版本数据时省略该块 | **迁 W** ⚠️（`version_read_surface.test.ts` 🆕） | 现有用例都在有版本数据的 fixture 上；「整块省略」这一支未见断言 |

### 5.8 `tests/test_version_contract.py`（40 条）——**本表最需要判断力的部分**

拆分判据（依据见第 6 节的推导）：

> **判据**：这条断言守的是「设备**自己**上报前该怎么构造/自检」→ 留 Python；
> 守的是「服务端**收到别人的**上报后怎么判定/脱敏/排序」→ 服务端判定权威，归 `version-contract.ts`。

按这条判据，**只有 `TestLocalCollectorRelease` 的 4 条是采集端自报**，其余 36 条都是服务端权威。
`normalize_collector_release` 的**代码**必须留在 Python（`local_collector_release` 出站前调它自检），
但它的**权威测试**归 Worker——两侧不一致的风险由 `collector_payload_fixture.json`
（实测含 `collector_release`，由 `ingest.test.ts:868` 逐字段比对）兜住。

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| **`TestVersionStateVocabulary`（服务端判定词表）** ||||
| 13 | `test_issue_58_four_states_are_the_declared_contract` | 四态就是声明的合同 | **迁 W** ⚠️（`version-contract.test.ts` 🆕） | `version-contract.ts:23 VERSION_STATES` 已存在；Worker 无词表断言（`version_read_surface.test.ts:292` 是行为级、不是词表级） |
| 19 | `test_unknown_is_a_separate_degradation_state_not_one_of_the_four` | unknown 是降级态不是第五态 | **迁 W** ⚠️（同上） | `ALL_VERSION_STATES` 已存在，无断言 |
| 27 | `test_every_state_has_a_deterministic_severity_rank` | 每态有确定严重度 | **迁 W** ⚠️（同上） | `VERSION_STATE_SEVERITY` 已存在，无断言 |
| **`TestVersionCompare`（服务端版本比较，采集端不用）** ||||
| 45 | `test_compare_versions_orders_semver_numerically_not_lexically` | semver 数值序而非字典序 | **迁 W** ⚠️（`version-contract.test.ts` 🆕单元用例） | `version-contract.ts:147 compareVersions` 已实现；Worker 全部版本测试都是 HTTP 级，**没有一条 `compareVersions` 单元用例** |
| 50 | `test_prerelease_sorts_before_its_release` | prerelease 排在正式版之前 | **迁 W** ⚠️（同上） | 同上 |
| 54 | `test_prerelease_numbers_compare_numerically_not_lexically` | prerelease 数字段数值比较 | **迁 W** ⚠️（同上） | 同上 |
| 59 | `test_prerelease_precedence_follows_semver_rules` | 遵循 semver 优先级规则 | **迁 W** ⚠️（同上） | 同上 |
| 64 | `test_build_metadata_does_not_affect_precedence` | build metadata 不影响优先级 | **迁 W** ⚠️（同上） | 同上 |
| 68 | `test_a_beta_channel_device_behind_the_beta_target_is_not_called_ahead` | beta 通道设备落后于 beta 目标时不能判成「超前」 | **迁 W** ⚠️（同上，需带 `VersionPolicy` 覆写） | 这是判定策略行为，采集端不参与 |
| **`TestCollectorReleaseNormalization`（wire 校验与脱敏——服务端权威）** ||||
| 81 | `test_full_release_block_is_flattened_into_canonical_fields` | 完整块扁平成 canonical 字段 | **迁 W**（`version-contract.test.ts:82`） | 已覆盖 |
| 113 | `test_absent_block_degrades_to_none_instead_of_raising` | 缺块降级不抛 | **迁 W**（`version-contract.test.ts:122`） | 已覆盖 |
| 116 | `test_partial_block_keeps_known_fields_and_nulls_the_rest` | 部分块保留已知、其余置 null | **迁 W**（`version-contract.test.ts:133`） | 已覆盖 |
| 124 | `test_non_object_block_is_an_explicit_contract_error` | 非 object 是显式合同错误 | **迁 W**（`version-contract.test.ts:148`） | 已覆盖 |
| 129 | `test_unknown_key_is_rejected_so_extra_data_cannot_ride_along` | 未知 key 拒收，额外数据不得搭车 | **迁 W**（`version-contract.test.ts:45` / `:148`） | 已覆盖 |
| 134 | `test_a_credential_shaped_unknown_key_is_redacted_instead_of_echoed` | 凭据形状的未知 key 脱敏不回显 | **迁 W**（`version-contract.test.ts:45`，标题即「redacts unknown keys exactly like the Python owner does」） | 已覆盖。注意：这条 TS 用例的措辞把 Python 当 owner，迁移后需改写为自持 |
| 152 | `test_a_plain_field_name_is_still_echoed_so_the_error_stays_actionable` | 普通字段名仍回显，错误保持可操作 | **迁 W**（`version-contract.test.ts:335`） | 已覆盖 |
| 159 | `test_a_trailing_newline_cannot_smuggle_itself_through_the_whitelist` | 结尾换行不得穿过白名单 | **迁 W**（`version-contract.test.ts:281`） | 已覆盖（PR #65 修的正是这类两侧分叉） |
| 175 | `test_a_credential_shaped_unknown_key_inside_last_upgrade_is_also_redacted` | 嵌套 `last_upgrade` 里的凭据 key 同样脱敏 | **迁 W** ⚠️（`version-contract.test.ts:45` 需确认覆盖嵌套层） | `:45` 是否走到 `last_upgrade` 嵌套分支未逐条核实 |
| 182 | `test_token_shaped_value_is_rejected_and_never_echoed_back` | token 形状值拒收且不回显 | **迁 W**（`version-contract.test.ts:293`） | 已覆盖。**同时**是 `local_collector_release` 出站自检的基础，Python 侧由 L393 保底 |
| 189 | `test_absolute_path_value_is_rejected_and_never_echoed_back` | 绝对路径值拒收且不回显 | **迁 W**（`version-contract.test.ts:293`） | 同上 |
| 201 | `test_release_channel_is_restricted_to_declared_channels` | `release_channel` 限定枚举 | **迁 W** + **留 P（各一条）** | 服务端入站校验归 TS ⚠️（Worker 无该枚举拒绝用例）；`config.py:125` 用 `RELEASE_CHANNELS` 校验**设备配置文件**，这条采集端行为已由 `tests/test_device_config.py` 守（范围外），本条按服务端归 W |
| 206 | `test_last_upgrade_status_is_restricted_to_declared_results` | `last_upgrade.status` 限定枚举 | **迁 W** ⚠️（`version-contract.test.ts` 🆕） | Worker `enumOrNull` 已实现，无枚举拒绝用例 |
| **`TestCollectorReleaseEvaluation`（服务端判定——纯权威）** ||||
| 233 | `test_missing_release_is_unknown_and_not_silently_treated_as_compliant` | 缺版本 = unknown 不当合规 | **迁 W**（`version-contract.test.ts:122` + `version_read_surface.test.ts:308`） | 已覆盖 |
| 242 | `test_missing_collector_version_inside_block_is_still_unknown` | 块内缺版本号仍是 unknown | **迁 W**（`version_read_surface.test.ts:308`） | 已覆盖 |
| 249 | `test_version_at_target_is_current` | 等于目标版本 = current | **迁 W**（`version_read_surface.test.ts:292`「decides all four version states plus the unknown degradation」） | 已覆盖 |
| 256 | `test_version_behind_target_but_above_minimum_is_update_available` | 落后但高于最低 = update_available | **迁 W**（`version_read_surface.test.ts:292` / `:356`） | 已覆盖 |
| 263 | `test_version_below_minimum_is_unsupported_and_not_accepted` | 低于最低 = unsupported 且不接受 | **迁 W**（`version-contract.test.ts:168` / `:207`） | 已覆盖 |
| 270 | `test_parser_schema_below_minimum_is_unsupported` | parser schema 低于最低 = unsupported | **迁 W**（`version-contract.test.ts:207`） | 已覆盖 |
| 277 | `test_failed_last_upgrade_with_known_previous_version_is_rollback_available` | 升级失败且知道前版 = rollback_available | **迁 W**（`version_read_surface.test.ts:292`） | 已覆盖（四态全覆盖那条） |
| 288 | `test_version_ahead_of_target_is_rollback_available_to_target` | 超前目标 = 可回滚到目标 | **迁 W** ⚠️（`version_read_surface.test.ts` 🆕） | 四态覆盖用例是否含「超前」这一支未逐条核实；`compareVersions` 无单元用例意味着方向判断无独立保护 |
| 295 | `test_unsupported_wins_over_rollback_and_update` | 多态并发时 unsupported 优先 | **迁 W** ⚠️（`version-contract.test.ts` 🆕） | 优先级仲裁在 Worker 侧无用例 |
| 303 | `test_evaluation_always_reports_the_policy_it_used` | 判定结果必须回报所用策略 | **迁 W** ⚠️（`version_read_surface.test.ts:268` 只钉了策略常量，未断言「结果里回报策略」） | 需新增 |
| **`TestVersionHealthReadModel`（服务端聚合读模型）** ||||
| 328 | `test_needs_attention_lists_every_outdated_or_incompatible_source` | needs_attention 列全每个过期/不兼容来源 | **迁 W**（`version_read_surface.test.ts:356`） | 已覆盖 |
| 343 | `test_ordering_is_deterministic_by_severity_then_source_id` | 按严重度再 source_id 确定排序 | **迁 W**（`version-contract.test.ts:254`） | 已覆盖 |
| 360 | `test_counts_cover_every_state_even_when_zero` | 计数覆盖每个状态，零也要出现 | **迁 W**（`version_read_surface.test.ts:341`） | 已覆盖 |
| 374 | `test_server_block_is_always_reported` | 服务端版本块永远上报 | **迁 W**（`version_read_surface.test.ts:325` / `:411`） | 已覆盖 |
| **`TestLocalCollectorRelease`（采集端自报——留 Python）** ||||
| 383 | `test_local_release_is_a_valid_wire_block` | 本机构造的版本块是合法 wire 块 | **留 P** | `pusher.py:18` 在用，设备侧行为，Worker 结构上碰不到 |
| 393 | `test_local_release_rejects_unsafe_overrides_before_they_leave_the_device` | 不安全覆写在离开设备前被拒 | **留 P** | 出站自检，是 Python 保留 `normalize_collector_release` 的唯一理由，也是它拆分后**唯一剩下的测试** |
| 397 | `test_local_release_without_any_config_input_is_still_a_valid_block` | 无配置输入也产出合法块（最后兜底） | **留 P** | 设备侧兜底行为 |
| 404 | `test_parser_schema_version_stays_aligned_with_the_real_parser` | `COLLECTOR_PARSER_SCHEMA_VERSION` 与 `mswusage_codex.PARSER_SCHEMA_VERSION` 对齐 | **留 P** | 纯采集端两个常量的一致性，与服务端无关 |

**拆分小结**：`test_version_contract.py` 40 = **留 P 4 条**（`TestLocalCollectorRelease`）+ **迁 W 36 条**。
36 条里 **22 条已有 Worker 覆盖**，**14 条标 ⚠️**——其中 `TestVersionCompare` 整组 6 条与
`TestVersionStateVocabulary` 整组 3 条是**成组的空白**：Worker 的版本测试全部是 HTTP 端到端级，
`compareVersions` 与状态词表**没有任何单元级断言**。这是本表发现的最大成块缺口。

**为什么拆分线画在这里（判断依据，供复核）**：

1. **消费者反查**。实测 Python 侧 `version_contract` 的 import 方共 6 个：
   `pusher.py:18` 与 `config.py:9` 是采集端（存活），`ingest.py:8` / `snapshot_source_health.py:7` /
   `snapshot_builder.py:20` / `server_services.py:22` 是服务端（本轮删除）。
   采集端只 import 了 4 个名字：`COLLECTOR_RELEASE_FIELD`、`UNSUPPORTED_ERROR_TYPE`、
   `VersionContractError`、`local_collector_release`（`pusher.py`），以及
   `DEFAULT_RELEASE_CHANNEL`、`RELEASE_CHANNELS`（`config.py`）。
   → **采集端真正依赖的 API 面只有 `local_collector_release` + 三个符号 + 两个枚举常量**，
   对应的测试正好是 `TestLocalCollectorRelease` 那 4 条。
2. **`normalize` 是代码留、权威走**。`version_contract.py:386` 里 `local_collector_release`
   在返回前调用 `normalize_collector_release(block)` 做出站自检，所以这段**代码**必须留在 Python；
   但「收到别人的上报后怎么判定/脱敏/排序」的**权威**归 `version-contract.ts`。
   Python 侧拆分后只保留一条守卫（L393「不安全覆写在离开设备前被拒」）。
3. **两侧 normalize 漂移的兜底**是 `collector_payload_fixture.json`——实测该 fixture
   **含 `collector_release` 块**，由 `ingest.test.ts:868` 断言「采集端发出的每个顶层字段都必须是
   Worker 已声明并解析的字段」。设备构造出 Worker 不认的块时会红。**这是拆分成立的技术前提**，
   不是附带说明。
4. **反例检查**：如果按「函数名里有 collector 就留 Python」来拆，会把整个
   `TestCollectorReleaseNormalization`（13 条）留下——但那 13 条测的全是**服务端收到什么就拒什么**，
   与设备无关，留下等于在 Python 里维护一份服务端判定的影子实现，正是 ADR 要消灭的东西。

### 5.9 `tests/test_version_contract_doc.py`（15 条，文档合同）

Worker 侧**没有任何文档合同测试**。见 **PM-6**。

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 119 | `test_doc_exists_and_is_linked_from_architecture_overview` | 文档存在且被架构总文档引用 | **留 P** | 纯文档结构断言，不依赖 `version_contract` 的任何判定能力 |
| 123 | `test_collector_field_inventory_matches_code_constants_exactly` | 采集端字段清单与代码常量完全相等 | **留 P** | 采集端常量留 Python（`COLLECTOR_VERSION_FIELDS`），owner 不变 |
| 128 | `test_server_field_inventory_matches_code_constants_exactly` | 服务端字段清单与代码常量完全相等 | **迁 W** ⚠️（`🆕文件 version-contract-doc.test.ts`） | `SERVER_VERSION_FIELDS` 的权威变成 `version-contract.ts:92` |
| 133 | `test_presentation_field_inventory_matches_code_constants_exactly` | 呈现端字段清单与代码常量完全相等 | **迁 W** ⚠️（同上） | 同上。注意 `PRESENTATION_VERSION_FIELDS` 在 `version-contract.ts` 里**未见对应导出**，迁移时需先补 |
| 138 | `test_every_version_field_points_at_an_owner_path_that_really_exists` | 每个字段指向真实存在的 owner 路径 | **待定** | 卡点：拆分后同一张表里的 owner 路径一半是 `.py` 一半是 `.ts`，断言需要同时跨两侧解析。放 Python 还是 TS 取决于 PM-6 |
| 153 | `test_collector_fields_declare_their_wire_path_under_collector_release` | 采集端字段声明其在 `collector_release` 下的 wire 路径 | **留 P** | 采集端 wire 面，owner 不变 |
| 168 | `test_state_reason_map_used_by_this_test_is_backed_by_real_behaviour` | 本测试用的「状态→reason」映射表由真实 `evaluate` 反向验证（防止测试自己编一张表） | **迁 W** ⚠️（同上） | `evaluate` 的权威在 TS。这条是「测试自身也会骗人」的防线，不能弄丢 |
| 177 | `test_doc_documents_every_state_including_the_unknown_degradation` | 文档记录每个状态含 unknown | **迁 W** ⚠️（同上） | 状态词表权威在 TS |
| 186 | `test_each_documented_state_lists_the_reasons_the_code_actually_emits` | 文档列的 reason 必须是代码真的会产出的 | **迁 W** ⚠️（同上） | 同上 |
| 198 | `test_doc_records_the_deterministic_severity_order` | 文档记录确定的严重度顺序 | **迁 W** ⚠️（同上） | `VERSION_STATE_SEVERITY` 权威在 TS |
| 214 | `test_min_supported_version_section_says_whether_it_prompts_or_rejects` | 最低支持版本一节必须写明是提示还是拒绝，并带真实 `error_type` | **迁 W** ⚠️（同上） | `UNSUPPORTED_ERROR_TYPE` 与拒绝行为权威在 TS |
| 223 | `test_manifest_section_states_how_a_release_is_verified` | manifest 一节写明 release 如何校验 | **待定** | 卡点：release manifest 的 owner 是 `deploy_release.py`（采集端发布流程，留 Python），但该节位于版本合同文档内。归属取决于 PM-6 里文档是否整体搬家 |
| 230 | `test_doc_points_at_code_as_the_source_of_truth_for_thresholds` | 文档必须指向代码作为阈值事实源 | **待定** | 卡点：断言里写死的「代码路径」在拆分后要改成 `.ts`；改成哪一侧取决于 PM-6 |
| 239 | `test_all_relative_links_resolve` | 文档内相对链接可解析 | **留 P** | 纯文档卫生，零代码依赖（只需删掉模块级 `version_contract` import） |
| 252 | `test_doc_carries_no_credential_or_absolute_home_path` | 文档不含凭据或绝对 home 路径 | **留 P** | 同上，安全卫生断言 |

---

## 6. 旁及 61 条逐条映射

### 6.1 `tests/test_normalize_ingest.py`（7 条，import `ingest.IngestRequest` + `normalize`）

归属整体受 **PM-4** 影响：`normalize.py` 的唯一两个消费者（`server_services.py`、`collector.py`）都在本轮删除。

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 59 | `test_normalize_and_deduplicate_single_payload` | 单 payload 内相同 key 合并、后覆前 | **迁 W**（`ingest.test.ts:100`「keeps repeated ingest payload batches idempotent」） | 归一化与幂等的权威在 `write-model.ts` |
| 71 | `test_full_ccusage_report_is_used_and_preserved` | 从完整 ccusage report 归一化并保留结构化明细 | **迁 W**（`ingest.test.ts:85` / `:692`） | 已覆盖 |
| 116 | `test_full_ccusage_session_report_skips_codex_hourly_usage` | 不用 `session.lastActivity` 估算 codex 小时（避免假尖峰） | **迁 W**（`ingest.test.ts:431`「leaves archived Codex hourly rows empty」） | 已覆盖 |
| 182 | `test_mswusage_codex_report_normalizes_hourly_rows_with_provenance` | mswusage codex 小时行带 provenance 归一化 | **迁 W**（`ingest.test.ts:85` / `:692`） | 已覆盖 |
| 244 | `test_ingest_machine_name_overrides_network_host_for_display` | 展示用 `payload.machine`，网络 host 只作元数据 | **迁 W** ⚠️（`ingest.test.ts` 🆕） | 与 5.7 的 L69 是同一条不变量的写侧，Worker 无用例 |
| 272 | `test_full_ccusage_blocks_report_normalizes_block_windows` | 从 ccusage blocks 生成带起止的窗口事实 | **迁 W**（`ingest.test.ts` 中 `ccusage_blocks` 命中） | 已覆盖（写侧） |
| 325 | `test_merge_multiple_requests_idempotency` | 跨请求按稳定 key 幂等 upsert | **迁 W**（`ingest.test.ts:100`） | 已覆盖 |

### 6.2 `tests/test_provider_slots_parity.py`（9 条）

**实测**：9 条里只有 L45 真正调用 `_collect_records()`（即 Python 读模型）；其余 8 条只读 golden 文件，
是「golden 自身结构」断言。模块级 import 会让 9 条全部打断，但内容上只有 1 条与 Python 读模型耦合。

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 45 | `test_python_read_model_matches_provider_slots_golden` | Python 读模型 == PS golden；同时是 **PS golden 的生成器与防陈旧守卫** | **迁 W**（`provider-slots-parity.test.ts` 需接管生成 + 防陈旧，见阻断 P1） | 被测对象消失，但**守卫职责必须转移**，不是废弃 |
| 49 | `test_every_scenario_keeps_usage_accounting_consistent_with_summary` | 守恒：槽位之和 + 点名余量 == 周期总量 | **迁 W** ⚠️（`provider-slots-parity.test.ts` 🆕） | 这是 AGENTS.md 点名的「从产物独立算一遍」的守恒断言。TS 侧现在只做 `toEqual(golden)`，**没有独立重算守恒**。丢了它，golden 一旦被错误重新生成就没人发现 |
| 72 | `test_third_party_provider_tokens_are_named_not_hidden` | 第三方 provider token 必须点名（两端点都要） | **留 P**（纯 golden 结构扫描）或随 P1 迁 W | 只读 golden，不碰待删模块 |
| 85 | `test_aggregate_agent_usage_lands_in_the_canonical_provider_slot` | `agent='all'` + `ai_provider='claude'` 必须进 Claude 槽 | **留 P**（同上） | 只读 golden |
| 96 | `test_golden_covers_all_four_usage_and_quota_combinations` | golden 必须覆盖四种 usage×quota 组合 | **留 P**（同上） | golden 覆盖度断言，与实现无关 |
| 113 | `test_golden_missing_quota_never_carries_percentages_or_reset` | missing 额度不得带百分比/reset | **留 P**（同上） | 官方额度红线的扫描式断言 |
| 129 | `test_scenario_fixtures_are_offline_sql_replays` | 场景清单必须是 13 个离线 SQL 回放 | **留 P**（同上） | 纯文件清单断言 |
| 150 | `test_golden_covers_every_quota_missing_reason` | golden 覆盖全部 5 种 missing 原因 | **留 P**（同上） | 覆盖度断言 |
| 161 | `test_golden_never_borrows_local_estimate_freshness_for_official_quota` | 本地估算新鲜度不得冒充官方验证时间 | **留 P**（同上） | 只读 golden 的 08/09 记录 |

> 注：这 7 条 `留 P` 只在 **PS golden 仍留在仓库且仍被维护**的前提下成立。若 P1 把 golden 整体
> 搬到 Worker 侧自持，它们应一并改写为 TS，此时归属变为 **迁 W**。

### 6.3 `tests/test_value_golden_freshness.py`（3 条，#63 的防陈旧守卫）

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 86 | `test_committed_golden_matches_freshly_generated_records` | 已提交 golden == 此刻读模型重放结果（陈旧即红） | **迁 W**（`🆕` Worker 侧生成器 + 防陈旧守卫，阻断 P1） | 生成基准从 Python 读模型换成 Worker 自身；职责一比一转移，**不是废弃** |
| 99 | `test_golden_covers_every_declared_request` | 请求清单变了而 golden 没跟上也算陈旧 | **迁 W**（同上） | 同上 |
| 108 | `test_regeneration_is_deterministic` | 守卫本身不许随机红（固定时间/时区/抹易变字段） | **迁 W**（同上） | 这条是「守卫的守卫」，迁移时最容易被漏。Worker 侧要用 `AIUSAGE_NOW` 固定时间复现同一保证 |

### 6.4 `tests/test_storage_sqlite.py`（10 条）

**实测**：`write_sqlite` 的消费者只有 `collector.py`（legacy，随 #74 清理）与 `server_services.py`（本轮删除）
→ **用量写入这一半没有存活消费者**。`_safe_error` 只在 `storage_sqlite.py` 内部使用。

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 16 | `test_accuracy_evidence_is_persisted_verified_and_downgraded_for_legacy` | 准确性证据落库、验证与 legacy 降级 | **迁 W**（`ingest.test.ts:519`「requires two complete matching scans before verification and authoritative deletion」） | 已覆盖 |
| 139 | `test_sqlite_wal_mode_and_timeout` | 本地 SQLite 启用 WAL + 超时 | **废弃** | 断言的是本地 SQLite 文件引擎的 pragma。D1 没有 WAL 概念，服务端不存在这个对象。**但行为需求会在 #73 `collector_store.py` 上重新出现**——那是新模块的新测试，不是本条的迁移 |
| 156 | `test_sqlite_upsert_idempotency` | 相同 source×date×agent 只 upsert 不增行 | **迁 W**（`ingest.test.ts:100`） | 已覆盖 |
| 218 | `test_safe_error_sanitization` | 错误信息脱敏与截断 | **迁 W**（`ingest.test.ts:457`） | `_safe_error` 随模块消失；服务端侧的等价保证是 Worker 的敏感字段拒收与错误体脱敏 |
| 231 | `test_sqlite_preserves_structured_ccusage_raw_json` | 保留 ccusage 原始结构化 row/model JSON 供后续验算 | **迁 W**（`ingest.test.ts:85` / `:692`） | 已覆盖（对应 D1 的 `usage_daily_models` / raw json 列） |
| 279 | `test_sqlite_preserves_hourly_usage_and_raw_session_json` | 保留小时 usage facts 与 session 原始行 | **迁 W**（`ingest.test.ts:85` / `:118`） | 已覆盖 |
| 323 | `test_sqlite_preserves_block_usage_and_raw_block_json` | 保留 ccusage blocks 窗口事实 | **迁 W**（`ingest.test.ts` 中 `ccusage_blocks` 命中） | 已覆盖（写侧） |
| 369 | `test_mswusage_codex_replaces_old_session_derived_codex_hourly_rows` | mswusage 覆盖旧的 session 推导 codex 小时行 | **迁 W**（`ingest.test.ts:431`） | 已覆盖 |
| 433 | `test_sqlite_preserves_account_hourly_fact_dimensions` | 账户小时事实的维度完整保留 | **迁 W**（`ingest.test.ts:85`） | 已覆盖 |
| 499 | `test_account_hourly_fact_upsert_uses_logical_hour_key` | 账户小时事实按逻辑小时 key upsert | **迁 W**（`ingest.test.ts:100`） | 已覆盖 |

### 6.5 `tests/test_d1_schema_migration.py`（5 条）

**实测**：只有 L155 用到 `storage_sqlite._ensure_schema`（第 163 行）。另外 4 条只操作
`cloudflare/migrations/*.sql`，本来就是自立的 D1 迁移测试。ADR 说的「5 条以 storage_sqlite 作镜像基准」偏大。

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 155 | `test_initial_d1_migration_matches_sqlite_schema` | D1 首迁与 SQLite schema 逐列一致（镜像守卫） | **废弃 + 迁 W** | 比对对象（`_ensure_schema`）随 `storage_sqlite` 消失，镜像守卫失去意义 → 废弃；但 #74 验收要求 D1 自立的 schema 测试，需**新增**「fresh install schema 列布局快照」用例接替它守的「列不许悄悄漂移」 |
| 190 | `test_full_migration_chain_matches_fresh_schema`（#75 前名为 `..._columns`，已扩展到索引维度） | 全链路迁移与全新安装落到同一套表、列与索引 | **留 P** | 不使用 `_ensure_schema`，纯 D1 迁移行为，删除待删模块不打断 |
| 260 | `test_backfilled_indexes_match_their_owning_migration`（#75 新增） | 回填进 0001 的索引与其 owner 迁移里的定义一致 | **留 P** | 纯 D1 迁移行为。专防「索引名对、表或列错」——`IF NOT EXISTS` 会让迁移链继承 0001 的错误定义，两条路径「一致地错」，上一条守卫看不见 |
| 228 | `test_collector_version_migration_upgrades_deployed_table_without_data_loss` | 0007 在既有数据上升级不丢数据 | **留 P** | 同上 |
| 290 | `test_collector_version_migration_rerun_keeps_schema_but_resets_collector_version` | 手工重跑 0007 的特征化（结构可重复、值不保留） | **留 P** | 同上 |
| 345 | `test_limit_window_migration_keeps_latest_row_for_stable_key` | 额度窗口迁移按稳定 key 保留最新行 | **留 P** | 同上 |

### 6.6 `tests/test_limit_windows_store.py`（9 条）——整体受 **PM-2** 决定

**实测**：`write_limit_windows` 的存活消费者只有 `limits_runtime.py`；而 `cli.py:633` 的 `push-limits`
用 `dry_run=True`，**不写也不读**本地库；#72 剪断快照重建后仓库内**没有任何本地读取方**。
即该本地表当前「只写不读」。

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 21 | `test_limit_windows_upsert_by_provider_source_type_and_window` | 按 provider×source_type×window upsert | **待定 → PM-2** | 服务端等价保证在 `ingest.test.ts:206`；本地侧去留看 PM-2 |
| 67 | `test_limit_windows_preserve_confidence_and_source_type` | 保留 confidence 与 source_type | **待定 → PM-2** | 服务端等价：`ingest.test.ts:487` + PS golden |
| 91 | `test_stable_key_reconciles_source_type_change_without_duplicate_window` | source_type 变化按稳定 key 对账不产生重复窗口 | **待定 → PM-2** | 服务端等价：`ingest.test.ts:206` |
| 116 | `test_stable_key_rejects_older_retry_across_timezone_offsets` | 跨时区的旧重试不得覆盖新窗口 | **待定 → PM-2** | 服务端等价：`ingest.test.ts:228` |
| 139 | `test_older_success_retry_does_not_clear_newer_provider_failure` | 旧的成功重试不得清掉更新的失败 | **待定 → PM-2** | 服务端等价：`ingest.test.ts:258` |
| 164 | `test_limit_windows_keep_multiple_accounts_for_same_provider` | 同 provider 多账户窗口都保留 | **待定 → PM-2** ⚠️ | 服务端侧同样缺（见 5.5 的 L545） |
| 208 | `test_success_window_clears_prior_provider_failed_placeholder_for_same_account` | 成功窗口清掉同账户此前的失败占位 | **待定 → PM-2** | 服务端等价：`ingest.test.ts:431` |
| 252 | `test_limit_windows_write_without_usage_rows` | 没有用量行也能写额度窗口 | **待定 → PM-2** | 服务端等价：PS `03-quota-without-usage` |
| 279 | `test_limit_windows_schema_does_not_store_secrets_or_raw_provider_response` | 额度表不得存密钥或原始 provider 响应 | **待定 → PM-2**（**建议无论如何保留**） | 这是安全断言。即使 PM-2 选走法 B/C，也必须在新 owner 上重建，不得随表一起消失 |

### 6.7 `tests/test_dashboard_static.py`（8 条）——整体 **留 P**，受 **PM-1** 只影响路径常量

**实测**：本文件**零 import** 任何 `ai_usage_widget` 模块，只读 `src/ai_usage_widget/static/`。
该目录是 Worker `static-assets.ts` 的生成源，且被 `web_surface.test.ts:94` 直接读取比对，
**不能随 `server.py` 删除**。因此 8 条**没有一条是废弃**。

| 行号 | 测试函数 | 守什么 | 归属 |
| --- | --- | --- | --- |
| 16 | `test_web_header_uses_dual_ring_brand_mark` | 页头双环品牌标识的 HTML/CSS 结构 | **留 P**（PM-1 走法 B 时只改 `STATIC` 常量） |
| 28 | `test_web_dashboard_matches_latest_handoff_structure` | dashboard 结构与最新交接稿一致 | **留 P**（同上） |
| 60 | `test_mobile_hero_total_block_does_not_reserve_desktop_width` | 移动端 hero 不预留桌面宽度 | **留 P**（同上） |
| 69 | `test_limits_are_grouped_fresh_and_timestamped` | 额度分组、新鲜、带时间戳 | **留 P**（同上） |
| 79 | `test_sources_are_sorted_online_first_with_user_at_host_identity` | 来源在线优先排序、身份为 user@host | **留 P**（同上） |
| 87 | `test_web_source_cards_include_visible_non_ok_zero_usage_sources` | 非 ok 的零用量来源仍可见 | **留 P**（同上） |
| 100 | `test_web_hero_badge_does_not_fake_period_delta` | hero 徽标不伪造周期环比 | **留 P**（同上） |
| 109 | `test_stream_chart_uses_integer_nice_ticks` | 流图使用整数刻度 | **留 P**（同上） |

### 6.8 `tests/test_limits_runtime.py`（7 条）——整体 **留 P**

**实测**：`limits_runtime.py` 今天只 import `limits` 与 `storage_sqlite.write_limit_windows`；
对 `snapshot_builder` 的依赖边已在 commit `1d7a856`（#72）剪断，测试文件 91-93 行有注释记录。
**删除待删模块不会打断这 7 条。** ADR 第 7.2 节把它们计入「旁及 61」的口径已过期。

| 行号 | 测试函数 | 守什么 | 归属 |
| --- | --- | --- | --- |
| 40 | `test_runtime_writes_fake_provider_windows_and_rebuilds_snapshot` | provider 窗口写入（函数名里的「rebuilds_snapshot」已随 #72 失效，仅名字滞后） | **留 P**（落库断言受 PM-2 影响） |
| 95 | `test_runtime_collects_multiple_instances_of_same_provider` | 同 provider 多实例都采到 | **留 P** |
| 145 | `test_runtime_writes_failed_window_without_local_history_fallback` | 失败窗口如实写入，不用本地历史兜底 | **留 P**（官方额度红线的采集端一侧） |
| 165 | `test_runtime_does_not_report_cached_only_provider_as_success` | 仅命中缓存的 provider 不算成功 | **留 P**（同上） |
| 198 | `test_runtime_dry_run_collects_without_writing_sqlite_or_snapshot` | dry-run 不写库 | **留 P**（`push-limits` 正是走这条路径，受 PM-2 影响） |
| 234 | `test_runtime_rejects_unknown_provider_without_writing` | 未知 provider 拒绝且不写 | **留 P** |
| 251 | `test_runtime_rejects_empty_provider_list_without_writing` | 空 provider 列表拒绝且不写 | **留 P** |

### 6.9 `tests/test_cli_verify_cloud.py`（54 条中的 3 条）

耦合位置：`TestVerifyCloudFixturesStayBoundToReadModel`（文件第 615 行起），
import 自 `mobile_summary.build_mobile_summary`（第 23 行）与 `version_contract.build_version_health`（第 24 行）。
其余 51 条只用 `cli` / `verify_cloud`，不受影响。

| 行号 | 测试函数 | 守什么 | 归属 | 理由 / 目标 |
| --- | --- | --- | --- | --- |
| 626 | `test_mobile_fixture_is_what_the_mobile_dto_owner_produces` | `verify-cloud` 的 mobile fixture 必须真的是 DTO owner 产出的，不是手写 | **迁 W** ⚠️（fixture 生成器需改由 Worker 产出） | AGENTS.md「fixture 必须由 owner 模块产出」。owner 从 `mobile_summary.py` 换成 `mobile-summary.ts` 后，需要一条等价的「fixture 由 Worker 产出」守卫；直接删 = `verify-cloud` 的 fixture 退回手写状态 |
| 635 | `test_parity_mismatch_fixture_really_diverges_from_the_owner_output` | 「故意不一致」的 fixture 必须真的与 owner 输出不同（防止负面 fixture 其实是正确的） | **迁 W** ⚠️（同上） | 同上，这是负面 fixture 的有效性守卫 |
| 642 | `test_version_blocks_match_the_version_contract_owner` | fixture 里的版本块必须等于版本合同 owner 的输出 | **迁 W** ⚠️（owner 换成 `version-contract.ts`） | 同上 |

> `verify_cloud.py` 本身按 ADR 5.3 **留 Python**（只读打生产 API，是新架构的验收工具），
> 只是它的 fixture 校验 owner 要换边。

---

## 7. 抽查结果：71 条「说迁过去 / 说有接替，但 Worker 侧其实没测」

这是本表最重要的输出：**67 条标 ⚠️ + 4 条阻断 P0 的待定 = 71 条**，
占 249 的 **28.5%**。按缺口的成块程度排序：

| # | 缺口 | 条数 | Worker 侧实测现状 | 后果 |
| --- | --- | --- | --- | --- |
| 1 | **`/ingest` 写路径认证与入参校验** | 10 | `index.ts:90` 有 401、`write-model.ts:623/626` 有必填与类型校验；但 `ingest.test.ts` 里 `toBe(401)` **零命中**，也没有缺字段/非法形状的拒绝断言 | 写路径 401、缺 `schema_version`、缺必填、非法 mswusage 形状、hourly fact 缺字段、token 轮换——全部无断言 |
| 2 | **`test_version_contract_doc.py` 的服务端半边** | 7 | Worker 侧**没有任何文档合同测试文件**；`PRESENTATION_VERSION_FIELDS` 在 `version-contract.ts` 里未见导出 | 「文档与代码不一致会红」这条守卫整体消失（见 PM-6） |
| 3 | **`compareVersions` 无单元用例** | 6 | `version-contract.ts:147` 已实现；Worker 全部版本测试都是 HTTP 端到端级 | semver 数值序、prerelease 优先级、build metadata、beta 通道判定全部失去直接保护 |
| 4 | **版本判定细节（枚举拒绝 / 优先级 / 超前 / 回报策略 / 嵌套脱敏 / update_available 不拒收）** | 6 | 实现都在 `version-contract.ts`，用例只覆盖了 unsupported 与四态读取面 | 判定策略被误改不会红 |
| 5 | ~~**today 趋势的五条派生规则**~~ | 5 → **2** | **#90 实测：本条前提已失效。** `blockRows` 恒为空、`usage_blocks` 从未被读模型查询，故 `addBlockToHourBuckets` / `dedupeCumulativeBlockRows` 是**死代码**（已删除）；`capTodayHourlyToPeriodTotals` 虽被调用但唯一的溢出来源就是 block——把它整个改成 `return;`，全量 Worker 测试**结果一字不变**（刻意保留，防御性钳位）。活路径的 2 条已由 `today-trend.test.ts` 补齐 | 给死代码写守卫产出的是「已经守住了」的假象，比没有守卫更糟 |
| 6 | **移动端账户/套餐标签的安全处理** | 5 | `mobile-summary.ts:488 safeAccountLabel` / `:500 safePlanLabel` / `:517 titlePlanPart` / `:473 mergeAccountContext` 已实现；`redact` 关键字在 Worker 测试里只命中 `version-contract.test.ts` | **安全相关**：账户标签脱敏、套餐名人性化、多来源合并全部无用例 |
| 7 | ~~**`ccusage_daily_status` 整个字段（阻断 P0 / #78）**~~ | 0 | **已收口**：字段从采集端摘除，两侧一致忽略，向后兼容由跨实现探针守住 | 缺口关闭。残留的已知代价是「ccusage 挂了但账本可用」时失败原因不再上报，见第 1 节 |
| 8 | **`verify-cloud` fixture 的 owner 绑定** | 4 | fixture 的 owner 从 Python 读模型换边后，无等价「fixture 由 owner 产出」守卫；`api_contract_golden` 的 Worker 侧生成器同样缺位 | fixture 退回手写状态，违反 AGENTS.md「fixture 必须由 owner 模块产出」 |
| 9 | **同机多 OS 用户分组** | 4 | `seed.sql` 只有 1 条 `os_identities`，`os_users` 在 `value_golden.json` **零命中** | by-machine 分组这条产品特性在 Worker 侧从未被真正回放 |
| 10 | **版本状态词表与严重度** | 3 | 常量已存在，无词表级断言 | 词表被误改不会红 |
| 11 | **provider 归属的三条边界路径** | 3 | 13 个场景 SQL 里 `'unknown'` / `'anthropic'` **零命中**，且无「无 canonical provider」场景 | 「用量静默消失」这类最难发现的错失去守卫 |
| 12 | **多账户额度窗口** | 2 | `seed.sql` 只有 1 条 `limit_windows`，Worker 测试 `multi_account` **零命中** | 多账户用户的额度展示无守卫 |
| 13 | **来源健康的两条边界** | 2 | `machine` 与网络 `host` 分离、版本块整块省略，均无用例 | 同机多用户身份混淆无守卫 |
| 14 | **跨实现守恒断言** | 1 | `provider-slots-parity.test.ts` 只做 `toEqual(golden)`，**不独立重算守恒** | golden 若被错误重生成，无人发现——正是 AGENTS.md 点名的失效模式 |
| 15 | **其余零散**（空库 summary、四周期必须互不相同、台账部分覆盖时保留残差、混合 confidence 逐账户可见、读侧 bestLimitWindows 择优、`ai_accounts` 无事实时的回落、全零来源为空、每周期都保留新鲜短窗、machine 名覆盖 host） | 9 | 逐条见第 5–6 节 ⚠️ 标记 | — |
| | **合计** | **71** | | |

**结论**：按当前 Worker 测试面直接删除这 249 条，会在上述 71 条上造成**真实覆盖率下降**——
不是「测试变少」，是**行为失去守卫**。其中第 6 项（账户标签脱敏）与第 1 项（写路径认证）是安全相关，
第 5、9、11、12 项是用户直接可见的数字正确性。

**门禁建议**：#74 的开工条件应从「映射表交付」加强为
**「映射表交付 + 这 71 条对应的 Worker 用例先补齐并变绿」**。
理由是 AGENTS.md 那条硬规则：删除守卫时，「现在是绿的」不构成证据——
必须能证明**删除后仍然有东西会为同一个错误变红**。本表证明了对这 71 条而言，删除后不会有。

---

## 8. 意外事实（与 ADR / 任务书口径不一致的地方）

逐条列出，实施时以本节为准（代码和测试是唯一事实源）。

1. **「61 旁及」已过期 15 条。** `test_dashboard_static.py`（8）与 `test_limits_runtime.py`（7）
   今天**不 import 任何待删模块**——前者零 `ai_usage_widget` import，后者的
   `limits_runtime → snapshot_builder` 边已由 commit `1d7a856`（#72）剪断。
   真正会被删除打断的是 **234** 条，不是 249。

2. **`src/ai_usage_widget/static/` 不是 Python 服务端的私产，删不得。**
   `cloudflare/native-worker/src/static-assets.ts:1` 声明「Generated from src/ai_usage_widget/static」，
   `cloudflare/native-worker/test/web_surface.test.ts:94` **直接读该目录**做逐字节比对，
   `package.json:6` 的 `cf:pages:deploy` 也部署它。ADR 第 5.1 节把 `server.py` 整体列入删除时
   没有点出这条依赖。→ PM-1 的两种走法都不产生「废弃」，这与任务书假设的「两种走法处置完全不同」不符。

3. **`normalize.py` 会在 #74 后变成零消费者模块。** ADR 5.3 把它列在「留在 Python（采集端）」，
   但实测它的消费者只有 `server_services.py`（删）与 `collector.py`（legacy，随 #74 清理），
   `pusher.py` 不 import 它。→ PM-4。

4. **`collect-limits` 的本地额度落库当前只写不读。** `push-limits` 走 `dry_run=True` 直接推
   `result.windows`（`cli.py:633-660`），#72 剪断快照重建后仓库内无本地读取方。
   ADR 说 `storage_sqlite.py` 的存活部分是采集端需要的——实测存活的只有一条无人读的写入路径。→ PM-2。

5. **`test_d1_schema_migration.py` 只有 1 条真正用 `storage_sqlite`**（L155 → `_ensure_schema`，第 163 行），
   另外 4 条本来就是自立的 D1 迁移测试。ADR 6.3 / 7.2 把 5 条整体算作镜像基准，偏大。

6. **`test_provider_slots_parity.py` 只有 1 条真正调用 Python 读模型**（L45），另外 8 条只读 golden。
   模块级 import 会打断 9 条，但内容上只有 1 条与被删对象耦合。

7. **跨实现合同 fixture 有四份不是三份。** 任务书漏了
   `cloudflare/native-worker/test/provider_slots_golden.json`（13 场景 × 2 端点 = 26 条记录）。
   它是 `test_snapshot_builder.py` 后 18 条与 `test_mobile_summary.py` 槽位段落的主要接替者，
   没有它，这一大块只能标「废弃」或「无接替」。

8. **`api_contract_golden.json` 在 Worker 侧的比对强度远低于 Python 侧。**
   `parity.test.ts:71` 只对前 2 条做 `toEqual`，其余 14 条只校 status/content-type/kind。
   把 `test_web_server.py` 的 HTTP 面整体标成「由 API 合同接替」会高估接替强度（阻断 P2）。

9. **三份 golden 的生成器全部是即将被删的 Python 读模型。** 这是本表最系统性的风险：
   如果 #74 只删代码不迁生成器，「由合同 fixture 接替」这 51 条的接替者会在删除当天变成
   **冻结快照**，而且不会有任何测试变红——与 #63 抓到的失效模式同构（阻断 P1）。

10. **`version-contract.test.ts:45` 的用例标题写的是「redacts unknown keys exactly like the Python owner does」**，
    即 TS 侧当前把 Python 当作 owner 在描述自己。#74 删掉 Python 后这句话失去指涉对象，
    迁移时必须改写为自持表述，否则会留下一条描述与事实不符的用例。

11. **`PRESENTATION_VERSION_FIELDS` 在 `version-contract.ts` 里未见对应导出。**
    Python 侧 `version_contract.py:107` 有这个常量并被 `test_version_contract_doc.py:133` 守护。
    迁移文档合同前需先在 TS 侧补上，否则该条无处可迁。

---

## 9. 本表的核验方法（可复现）

```bash
# 1. 逐文件测试函数计数
for f in test_api_contract test_web_server test_server_services test_ingest_contract \
         test_snapshot_builder test_mobile_summary test_snapshot_source_health \
         test_version_contract test_version_contract_doc test_normalize_ingest \
         test_provider_slots_parity test_value_golden_freshness test_storage_sqlite \
         test_d1_schema_migration test_limit_windows_store test_dashboard_static \
         test_limits_runtime test_cli_verify_cloud; do
  printf "%-40s %s\n" "$f.py" "$(grep -c 'def test_' tests/$f.py)"
done

# 2. Python 全量测试数（本表基准 678）
PYTHONPATH=src:tests python3 -c \
  "import unittest;print(unittest.TestLoader().discover('tests',top_level_dir='tests').countTestCases())"

# 3. 哪些测试文件真的 import 了待删模块
for f in tests/test_*.py; do grep -l "ai_usage_widget\.\(server\|server_services\|ingest\|snapshot_\|mobile_summary\|storage_sqlite\)" "$f"; done

# 4. Worker 侧覆盖抽查（本表 ⚠️ 的判定方式）
grep -ril "<关键词>" cloudflare/native-worker/test/*.ts
```

**本表未做的事（诚实列出）**：

- 没有运行任何 Python 或 Worker 测试。全部 ⚠️ 判定基于 grep + 源码阅读，**未经运行时验证**。
- 没有逐条打开每个 Worker 用例的函数体确认它究竟断言了什么；对「已覆盖」的判定主要依据用例标题
  与被测路径。标题与实际断言不符的情况（AGENTS.md 明确警告过这类）本表无法排除。
- 没有核实 `provider_slots` 13 个场景 SQL 与 Python 测试的逐条语义对应，只核实了
  agent / provider 取值的存在性（这正是发现 5.5 中三条缺口的方式）。
- 生产环境未回源核实（证据等级未达 5）。
