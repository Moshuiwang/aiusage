---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
---

# Python 服务端架构边界

> **2026-08-02 架构决策（#67）：服务端收敛为 Cloudflare Worker + D1 单实现。**
> 服务端权威在 `cloudflare/native-worker/src/*.ts` + `cloudflare/migrations/`；
> 采集端仍是 Python。**Python 服务端路径已于 #74 删除（2026-08-03）**，
> 见本文「Python 服务端已删除」一节。
> 决策全文与理由：[`docs/architecture/server-path-consolidation-decision.md`](../../docs/architecture/server-path-consolidation-decision.md)。

核心数据流是**单向 push 管道**，不要反向依赖：

```
设备本机采集 (pusher.py: ccusage daily/session + mswusage-codex)          [Python，采集端]
  -> POST /ingest, /ingest-limits
     Cloudflare Worker index.ts -> write-model.ts -> D1                     [唯一服务端实现]
  -> /api/summary、/api/mobile/summary、/api/health（read-model.ts / mobile-summary.ts）
  -> clients（Web / iOS App+Widget / Watch / macOS 菜单栏）                  只读，零口径计算
```

本地开发入口是 `scripts/dev_worker.sh`（wrangler dev + 本地 D1，与生产同款实现，#71）。

## 模块 owner 边界

新增字段或接口先找 owner，**不要**在 route handler、客户端或文档里重定义口径。
「状态」列说明该关注点在 #67 决策后的归属：**权威已转移**的行，新字段只能加在 TS 侧。

| 关注点 | 唯一权威 | 状态 |
| --- | --- | --- |
| HTTP 路由 / 认证 / 登录 cookie / 静态文件 | `cloudflare/native-worker/src/index.ts`（静态资源在 `cloudflare/native-worker/static/`，PM-1） | `server.py` 已随 #74 删除；本地开发入口 `wrangler dev`（#71） |
| ingest / limits ingest / summary / health 编排 | `cloudflare/native-worker/src/index.ts` + `write-model.ts` / `read-model.ts` | `server_services.py` 已随 #74 删除 |
| ingest payload 校验 + 敏感字段边界 | `cloudflare/native-worker/src/write-model.ts` | `ingest.py` 已随 #74 删除 |
| canonical store schema / upsert / 迁移 | `cloudflare/migrations/` | `storage_sqlite.py` 已随 #74 删除；schema 守卫改为 `test_d1_schema_migration.py` 的显式列布局快照（自立，不再镜像） |
| Web summary 读模型（period/filter/trend/limits/hourly residual） | `cloudflare/native-worker/src/read-model.ts` | `snapshot_builder.py`（+ `snapshot_*.py` helper）已随 #74 删除 |
| Mobile DTO | `cloudflare/native-worker/src/mobile-summary.ts` | `mobile_summary.py` 已随 #74 删除 |
| 版本合同：服务端判定（四态、最低支持版本、拒绝不兼容 payload） | `cloudflare/native-worker/src/version-contract.ts` | `version_contract.py` 的服务端判定部分已随 #74 删除，Python 只剩采集端自报半边 |
| 版本合同：采集端自报 | `version_contract.py`（采集端保留部分） | **留 Python**（`pusher.py`、`config.py` 在用），不冻结 |
| 设备本机采集与 HTTP 上报 | `pusher.py`、`runners.py`、`mswusage_*.py` | **留 Python**，不冻结 |
| 采集端 payload 合同 fixture | `pusher.py`（owner 模块产出，**禁止手写**） | **留 Python**。生成 `scripts/gen_collector_payload_fixture.py`，防陈旧守卫 `tests/test_collector_payload_contract.py` |
| 服务端合同 golden：`value_golden.json` / `provider_slots_golden.json` / `api_contract_golden.json` / macOS owner fixture | `cloudflare/native-worker/test/golden/`（收集器即 owner，**禁止手写**） | **权威已转移**（#74 P1）。生成 `npm run cf:golden:gen`，防陈旧守卫 `golden-freshness.test.ts` + `provider-slots-parity.test.ts`。Python 侧的 `gen_value_golden.py` / `gen_provider_slots_golden.py` / `test_value_golden_freshness.py` / `test_provider_slots_parity.py` / `test_api_contract.py` 已删除 |
| 采集端本地 outbox / 可靠投递 | `collector_store.py` | **已建**（#73）。缓冲不是档案，历史权威永远在 D1。库路径**要求绝对路径**（默认 `~/.ai-usage/collector_outbox.sqlite`）——采集由 LaunchAgent/systemd 拉起时 cwd 是 `/` 或 `$HOME`，相对路径会导致同机开两个库且排空守卫误放行。<br>调用方：用量事实走 `pusher.py`，额度观测走 `limits_push.py::deliver_limits_payload`（#87 接线，`push-limits --config` 才启用）。额度带 TTL + 按槽位集合去重，用量不设 TTL 也绝不去重——两种可靠性语义不同，不要合并。运维入口 `outbox-status` / `outbox-export` / `outbox-drain` |
| 官方额度 provider / runtime / doctor / scheduler / push | `*_limits_provider.py`、`limits_*.py` | **留 Python**。#74/PM-2 起 `collect-limits` 不落任何本地库，采集结果只在内存与 `push-limits` 上报链路 |
| 部署单元 / 发布 / 体检 | `deploy_units.py`、`deploy_release.py`、`deploy_doctor.py` | **留 Python**，不冻结 |
| 本地快照线 `widget_sync.py` / `sync-widget` / `latest.json` | 无 | **判死**，随 #72 处置。不得新增消费者 |

接口与 schema 的唯一权威是上述代码，不是 `docs/architecture/interfaces.md`（索引而已）。

## Python 服务端已删除（#67 决策，#74 执行，2026-08-03）

服务端唯一实现是 Cloudflare Worker + D1。下列 Python 模块**已删除**（删除前 tag
`pre-server-deletion-eee4f35`，需要历史时从 git 找回）：

`server.py`、`server_services.py`、`ingest.py`、`snapshot_builder.py`、
`snapshot_filters.py`、`snapshot_periods.py`、`snapshot_source_health.py`、`snapshot_trends.py`、
`mobile_summary.py`、`storage_sqlite.py`、`storage_json.py`、`normalize.py`（PM-4）、
`collector.py`（legacy）、`timeutil.py`（随 collector 归零消费者），以及
`version_contract.py` 的服务端判定部分（拆分，采集端自报半边保留）。

**反回潮规则**（由 `tests/test_architecture_governance.py` 的 AST 守卫钉住）：

- 采集端模块不得 import 上述任何名字；新建同名模块同样会被当场拦下。
- 服务端行为（汇聚、周期截断、归属守恒、额度窗口采用、健康判定、版本判定）的
  **新字段唯一去处**是 `cloudflare/native-worker/src/*.ts` + `cloudflare/migrations/`；
  不允许在 Python 侧「顺手同步一份」——那正是单实现决策要消灭的形态。

**不在删除名单内**（正常开发）：采集端全部模块——`pusher.py`、`runners.py`、`mswusage_*.py`、
`*_limits_provider.py`、`limits_*.py`、`collector_store.py`、`deploy_*.py`、`config.py`、
`cli.py`、`models.py`、`timezones.py`、`lock.py`、`backup.py`、`auth.py`、`http_identity.py`、
`d1_legacy_backfill.py`、`verify_cloud.py`、`version_contract.py` 的采集端自报部分。

**判断口径**（拿不准时用这条，来自 #67 不变量 1）：
这个值只依赖本机可见输入吗？是 → 采集端（Python，正常开发）；
需要跨设备全局视图（汇聚、周期截断、归属守恒、额度窗口采用、健康判定）→ Worker（TS）。
展示层零口径计算。

## 当前 HTTP 接口

`/ingest`、`/ingest-limits`（Bearer）、`/api/summary`、`/api/mobile/summary`、
`/api/health`（Bearer 或 cookie）、`/login`、`/`、`/dashboard`、`/static/*`。
summary 与 mobile 共享查询参数 `date` / `period(today|week|month|all)` / `machine` / `account`。

**API 合同（path / method / status code / JSON）在整个收敛过程中零变化。** 服务端换实现不是
换接口；任何要改接口的想法都是另一个决策，不能夹带在迁移里。

## 测试约定

- 纯标准库 `unittest`，无 pytest、无网络、无真实 `ccusage`/SSH/provider。
- 新测试必须可离线 fixture 重放。
- 重构必须保持现有 API path、HTTP method、status code 和 JSON 合约不变。
- **服务端行为的新测试写在 `cloudflare/native-worker/test/`**。「旧测试 → 新归属」映射表
  已随 #74 执行完毕并逐条勾销（`docs/architecture/server-path-test-migration-map.md` 第 10 节）。
- 无 lint / formatter 配置。CLI 入口 `ai_usage_widget.cli:main`，日常用 `python3 -m ai_usage_widget.cli`。
- legacy 的 `collector.py` / SSH 拉取路径已随 #74 删除；汇聚端只接受设备 push 的结构化 payload。
