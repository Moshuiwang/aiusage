# Status

> **进度不在本文件。** 当前待办、进行中和已完成状态的唯一真值是 GitHub：
> [Issues](https://github.com/Moshuiwang/aiusage/issues) 与
> [Project #1 AI Usage Delivery](https://github.com/users/Moshuiwang/projects/1)。
> 本文件只记录**不随单个任务变化的当前事实和有效决策**，不写「下一步」，不写已完成清单。

## 当前生产事实

- 生产入口：`https://aiusage.chunbai.com`，由 Cloudflare Worker + Cloudflare D1 承载。
- 数据库类型：Cloudflare D1，SQLite-compatible serverless SQL，不是 PostgreSQL。
- VPN2 旧 AI Usage 后端已下线，不再参与读写链路。
- 本机上报：macOS LaunchAgent `com.chunbai.aiusage.pusher` 每 300 秒运行 Python pusher。
- 上报内容：只上传去敏后的 Codex / Claude 小时用量事实和必要归因字段；不上传原始 session、
  prompt、response、tool output 或原始日志路径。
- 去重口径：服务端对同一来源、agent、账号归因、小时窗口和 provenance upsert；
  重复上报更新同一小时桶，不累加成重复用量。
- **服务端只有一份权威实现**：Cloudflare Worker + D1。Python 服务端（`server.py` 那条链）
  已冻结，只修迁移阻断问题，不承接新产品字段，随 #74 删除。本地开发跑 `scripts/dev_worker.sh`
  （wrangler dev + 本地 D1，与生产同款实现），不再用 `cli server`。
- **版本可见性已上线**：`/api/summary` 的 `source_status[].version` 与顶层 `version_health`、
  `/api/health` 的 `versions` 返回各设备版本状态。语义是「**最后一次被服务端成功接收的版本**」，
  不是「设备当前运行的版本」——不兼容 payload 在写库之前就被拒绝。
- **D1 迁移已到 `0007`**。注意 `0001_initial_schema.sql` 是**累计快照**（0002/0003/0004/0006 已回填），
  但 `0005` 的两个审计索引未回填，所以「只跑 0001 的新建库」与生产 schema 有差异（#75）。

> D1 体量等会随时间变化的数字不在此维护，需要时直接查。

## 有效决策

- **产品方向**：个人使用的多设备 AI usage 观测数据产品。
- **采集方向**：各终端在自己的 OS 用户上下文运行本机采集，主动 push 结构化 usage payload 到
  Cloudflare Worker；`ccusage` 只作日级对账和历史兜底，不应阻断 Codex / Claude Usage Ledger 明细上报。
- **展示方向**：Web dashboard 是完整查看入口；客户端按 `clients/` 分层。iPhone App + iOS Widget
  已落地；macOS 只做菜单栏或轻量桌面入口，不回到 macOS Widget 主线；Windows 走托盘或轻量桌面入口；
  Android 复用移动端摘要合同。
- **limits 原则**：历史 token / session logs 只做统计，不参与官方 reset time 计算。
- **Codex provider**：OAuth/WHAM usage 优先，`codex app-server` RPC `account/rateLimits/read` fallback。
- **Claude provider**：OAuth Usage API 优先，Claude CLI `/usage` fallback。
- **服务端路径收敛**（#67，2026-08-02）：服务端收敛为 Cloudflare Worker + D1 **单实现**。
  采集端永远是 Python——它要读本机 ccusage / mswusage 与 OS 用户上下文，Worker 沙箱做不到，
  所以「采集端 ↔ 服务端」是一条**永久的跨语言边界**，只能治理不能消灭。
  决策全文与被否决选项的理由见 `docs/architecture/server-path-consolidation-decision.md`。
  - **职责判据**：只依赖本机可见输入的运算放采集端；需要跨设备全局视图的（汇聚、周期截断、
    归属守恒、额度窗口采用、健康判定）放 Worker；展示层零口径计算。
  - **事实层红线**：D1 必须保存满足已声明历史范围与重算精度所需的 canonical facts；
    rollup 与采集端预计算只是加速层。裁剪事实层必须先有保留期决策与会变红的守卫。
  - **采集端产出事实，不产出跨设备结论**；推送体不得只推预计算结果。
- **新字段的唯一去处**：`cloudflare/native-worker/src/*.ts` + `cloudflare/migrations/`。
  「Worker 加了、顺手在 Python 同步一份」是被明令禁止的——那正是让三种状态长期并存的机制。
- **执行规则**：所有开发任务 TDD；验证走 `scripts/verify.sh`（会按改动面自动裁剪，
  `--full` 强制全量，`--explain-scope` 查看判定依据）。

## 注意

- 不要把任务细节写回本文件，也不要在这里重建进度表。
- V1/V2 任务包体系已于 2026-08-01 整体归档，见 `docs/task-packages/v2/INDEX.md`；
  新工作直接开 GitHub Issue，不再新增 `TP-V2-nnn` 编号。
- 既有 macOS Widget 文档和任务包只作历史/兼容资料，不是后续产品交付目标。
