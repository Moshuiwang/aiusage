# Architecture

当前架构权威文档已经收敛到固定入口：

- 当前真实架构和治理边界：[`docs/architecture/architecture.md`](architecture/architecture.md)
- 当前 SQLite 结构索引：[`docs/architecture/database.md`](architecture/database.md)
- 当前 HTTP / summary / mobile 接口索引：[`docs/architecture/interfaces.md`](architecture/interfaces.md)
- 项目地图与客户端目录边界：[`docs/project-map.md`](project-map.md)

本文件只保留入口指针，避免 AI Agent 同时读取两份互补但不同步的架构文档。

## Round 8 迁移记录

已迁移到权威区：

- 分层职责、source/trust boundary、presentation 边界：并入
  [`docs/architecture/architecture.md`](architecture/architecture.md) 的当前架构和放置规则。
- SQLite 表职责、WAL/busy timeout、upsert 和敏感数据边界：核对
  `src/ai_usage_widget/storage_sqlite.py` 后写入
  [`docs/architecture/database.md`](architecture/database.md)。
- 当前 `/ingest`、`/ingest-limits`、`/api/summary`、`/api/mobile/summary`、
  `/api/health` 合同和错误 shape：核对 `server.py`、`server_services.py`、
  `ingest.py`、`limits.py`、`snapshot_builder.py`、`mobile_summary.py` 后写入
  [`docs/architecture/interfaces.md`](architecture/interfaces.md)。
- 客户端当前目录和目标目录映射：迁移到
  [`docs/project-map.md`](project-map.md)。

已标为目标 / 未实现：

- `snapshot_builds`、`source_status_hourly`、`collector_cursors`、
  `client_snapshot_cache`、`display_preferences` 当前代码没有对应现状表。
- 旧 `latest.json` 示例中的 `limits.used`、`limits.limit`、`used_percentage`、
  `resets_at` 不是当前输出字段；当前字段以 `snapshot_builder.py` 和
  `docs/architecture/interfaces.md` 为准。
- launchd / systemd / Windows Task Scheduler 自动化、Android、Windows、macOS
  轻量客户端属于后续任务，不是 Round 8 实现内容。

已降级为历史参考：

- 旧根架构文档中的目标态示意、历史部署策略和未落地 schema 只作为迁移记录保留；
  当前事实以后只看上方权威入口。
