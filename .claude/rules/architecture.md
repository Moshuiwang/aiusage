---
paths:
  - "src/**/*.py"
  - "tests/**/*.py"
---

# Python 服务端架构边界

> **2026-08-02 架构决策（#67）：服务端收敛为 Cloudflare Worker + D1 单实现。**
> 服务端路径的权威已转移到 `cloudflare/native-worker/src/*.ts` + `cloudflare/migrations/`；
> 采集端仍是 Python。**下面的 Python 服务端模块已冻结**，见本文「Python 服务端冻结」一节。
> 决策全文与理由：[`docs/architecture/server-path-consolidation-decision.md`](../../docs/architecture/server-path-consolidation-decision.md)。

核心数据流是**单向 push 管道**，不要反向依赖。生产链路是 Worker + D1；下图中 `server.py` 到
`mobile_summary.py` 这段是**冻结中的本地开发/合同测试路径**，随 #71（`wrangler dev` 接替）与
#74（删除）退役：

```
设备本机采集 (pusher.py: ccusage daily/session/blocks + mswusage-codex)   [Python，保留]
  -> POST /ingest, /ingest-limits
     ├─ 生产：Cloudflare Worker index.ts -> write-model.ts -> D1              [权威]
     └─ 本地开发（冻结）：
        server.py            HTTP 适配，仅路由/认证/请求响应
        server_services.py   业务编排，不依赖 HTTP 对象
        storage_sqlite.py    本地 canonical store（生产权威库是 D1）
        snapshot_builder.py  /api/summary read model
        mobile_summary.py    /api/mobile/summary DTO，只裁剪不重算口径
  -> clients（Web / iOS App+Widget / Watch / macOS 菜单栏）                  只读，零口径计算
```

## 模块 owner 边界

新增字段或接口先找 owner，**不要**在 route handler、客户端或文档里重定义口径。
「状态」列说明该关注点在 #67 决策后的归属：**权威已转移**的行，新字段只能加在 TS 侧。

| 关注点 | 唯一权威 | 状态 |
| --- | --- | --- |
| HTTP 路由 / 认证 / 登录 cookie / 静态文件 | 生产：`cloudflare/native-worker/src/index.ts` | 权威已转移。`server.py` **冻结**，本地开发入口改 `wrangler dev`（#71），随 #74 删除 |
| ingest / limits ingest / summary / health 编排 | `cloudflare/native-worker/src/index.ts` + `write-model.ts` / `read-model.ts` | 权威已转移。`server_services.py` **冻结**，随 #74 删除 |
| ingest payload 校验 + 敏感字段边界 | `cloudflare/native-worker/src/write-model.ts` | 权威已转移。`ingest.py` **冻结**，随 #74 删除 |
| canonical store schema / upsert / 迁移 | `cloudflare/migrations/` | 权威已转移。`storage_sqlite.py` **冻结**（当前还兼任 D1 schema 镜像基准，#74 时由 migrations 自立测试接替后收缩或删除） |
| Web summary 读模型（period/filter/trend/limits/hourly residual） | `cloudflare/native-worker/src/read-model.ts` | 权威已转移。`snapshot_builder.py`（+ `snapshot_*.py` helper）**冻结**，随 #74 删除 |
| Mobile DTO | `cloudflare/native-worker/src/mobile-summary.ts` | 权威已转移。`mobile_summary.py` **冻结**，随 #74 删除 |
| 版本合同：服务端判定（四态、最低支持版本、拒绝不兼容 payload） | `cloudflare/native-worker/src/version-contract.ts` | 权威已转移。`version_contract.py` 的服务端判定部分**冻结**，随 #74 删除 |
| 版本合同：采集端自报 | `version_contract.py`（采集端保留部分） | **留 Python**（`pusher.py`、`config.py` 在用），不冻结 |
| 设备本机采集与 HTTP 上报 | `pusher.py`、`runners.py`、`mswusage_*.py` | **留 Python**，不冻结 |
| 采集端 payload 合同 fixture | `pusher.py`（owner 模块产出，**禁止手写**） | **留 Python**。生成 `scripts/gen_collector_payload_fixture.py`，防陈旧守卫 `tests/test_collector_payload_contract.py` |
| 采集端本地 outbox / 可靠投递 | `collector_store.py` | **已建**（#73）。缓冲不是档案，历史权威永远在 D1。库路径**要求绝对路径**（默认 `~/.ai-usage/collector_outbox.sqlite`）——采集由 LaunchAgent/systemd 拉起时 cwd 是 `/` 或 `$HOME`，相对路径会导致同机开两个库且排空守卫误放行 |
| 官方额度 provider / runtime / doctor / scheduler / push | `*_limits_provider.py`、`limits_*.py` | **留 Python**，不冻结。但 `limits_runtime.py -> snapshot_builder` 这条依赖边由 #72 剪断，剪断前不得加深 |
| 部署单元 / 发布 / 体检 | `deploy_units.py`、`deploy_release.py`、`deploy_doctor.py` | **留 Python**，不冻结 |
| 本地快照线 `widget_sync.py` / `sync-widget` / `latest.json` | 无 | **判死**，随 #72 处置。不得新增消费者 |

接口与 schema 的唯一权威是上述代码，不是 `docs/architecture/interfaces.md`（索引而已）。

## Python 服务端冻结（#67 决策，2026-08-02 生效）

服务端权威实现是 Cloudflare Worker + D1。下列 Python 模块**已冻结**，随 #74 分期删除。

**冻结名单**：`server.py`、`server_services.py`、`ingest.py`、`snapshot_builder.py`、
`snapshot_filters.py`、`snapshot_periods.py`、`snapshot_source_health.py`、`snapshot_trends.py`、
`mobile_summary.py`、`storage_sqlite.py`、`version_contract.py` 的**服务端判定部分**、
`normalize.py` 的**服务端归一化部分**。

> `normalize.py` **在 #74 之后会变成零消费者模块**，去留待 PM 定（映射表 PM-4）。
> 实测：它的消费者只有 `server_services.py`（随 #74 删除）与 `collector.py`
> （ADR 5.4 判 legacy、随 #74 清理）；**`pusher.py` 不 import 它**。
> 所以它既不属于「留在 Python 正常开发」，也不是简单的「拆分」——采集端根本不用它。
>
> 这条的发现过程本身值得记：先查「谁 import 了 `ingest`」发现 `normalize.py → ingest.py`
> 这条边（#72 治理断言的 glob 只扫 `pusher.py` / `limits_*.py` / `mswusage_*.py` /
> `deploy_*.py`，扫不到它），据此误判为「混合模块需拆分」；再查「删除之后谁还用它」
> 才得出零消费者的结论。**只查入边不查出边会得出似是而非的结论。**

**可以改**：

- 修复迁移阻断问题（挡住 #71 / #72 / #73 / #74 的问题）。
- 修复安全问题、凭据泄露、数据损坏。
- 让现有测试重新变绿的**最小**修复。
- 删除代码（这正是目标方向）。

**不可以改**：

- 承接任何**新产品字段、新 API、新口径、新展示逻辑**。
- **「Worker 那边也要加，顺手在 Python 这边同步一份」同样禁止**——这正是让
  「Python / TS / 半迁移」三种状态长期并存的机制，是决策要消灭的东西。
- 为了让 Python 侧「看起来更完整」而做的重构、优化、补测试。

**新字段的唯一去处**：`cloudflare/native-worker/src/*.ts` + `cloudflare/migrations/`。

**不在冻结名单内**（正常开发）：采集端全部模块——`pusher.py`、`runners.py`、`mswusage_*.py`、
`*_limits_provider.py`、`limits_*.py`、`deploy_*.py`、`config.py`、`cli.py`、
`models.py`、`timeutil.py` / `timezones.py`、`lock.py`、`backup.py`、`auth.py`、
`verify_cloud.py`、`version_contract.py` 的采集端自报部分。

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
- **不为冻结名单里的模块新增测试**（除非是抓迁移阻断问题的红测）。服务端行为的新测试写在
  `cloudflare/native-worker/test/`。#74 前需交付「旧测试 → 新归属」映射表，涵盖
  188 个主体测试（9 文件）+ 61 个旁及测试（9 文件），明细见 ADR 第七节。
- 无 lint / formatter 配置。CLI 入口 `ai_usage_widget.cli:main`，日常用 `python3 -m ai_usage_widget.cli`。
- `collector.py` / SSH 是 legacy，新功能不得依赖。
