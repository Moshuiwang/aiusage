# TP-V2-087 M1 D1 Schema 与免费额度核对

Status: done
Milestone: Cloudflare 迁移 M1（见 `docs/architecture/cloudflare-migration-objective.md`）
依赖：TP-V2-086

## Goal

产出 production D1 的 schema 定稿、SQLite→D1 的 SQL 差异清单、免费档额度核算与读写策略、历史数据导入方案（含校验）。**全程不触生产、不导真实数据。**

## Context

当前权威库是 `src/ai_usage_widget/storage_sqlite.py` 里的 SQLite。D1 与 SQLite 兼容但有差异：无 `PRAGMA journal_mode=WAL` / `busy_timeout` 语义、`ALTER TABLE` 受限、`executescript` 多语句要拆成 batch、事务模型不同、单查询结果行数与语句大小有上限、免费档对存储/每日读写行数/查询次数有额度。这些必须在写任何 Worker 代码前算清。

## Scope

- 把 `storage_sqlite.py` 现有全部表 / 索引 / 主键 / upsert 翻译成 D1 迁移 SQL（建议 `cloudflare/migrations/`）。
- 逐条列 SQL 差异与对策：PRAGMA、`ALTER TABLE` 自迁移逻辑（`_ensure_column` / `_ensure_limit_windows_schema`）、`ON CONFLICT DO UPDATE` upsert、`limit_windows` 历史重建等。
- 核算免费 D1 额度（存储、每日读写行数、查询次数、单查询结果行数、语句大小），引用当前 Cloudflare 官方文档并标注来源；对照现有数据量与 ingest 频率，给出「查询时计算 + 缓存 + 批量写」的读写策略。
- 设计历史 SQLite→D1 导入方案：导出、导入、**行数校验 + 抽样字段校验** 两道关；写成可执行步骤，但本任务不执行。

## Out of Scope

- 不建生产资源、不部署、不导真实数据。
- 不实现 TS Worker 业务逻辑（本任务以 schema / SQL 草案 / 策略文档为主）。

## Red Test

为迁移 SQL 写一个本地校验：在 `wrangler d1 --local` 或本地 sqlite 上 apply 迁移，断言建出的表结构与现有 SQLite 等价（表名、列、主键、索引）。先红后绿。

## Acceptance Criteria

- 迁移 SQL 能在本地建出与现有 SQLite 等价的表结构。
- 差异清单完整、每条有对策。
- 额度核算有明确数字与官方来源链接。
- 导入方案含可执行的双重校验步骤。
- 不触生产、不导真实数据。

## Verification

本地 apply 命令输出；表结构对比结果。

## Handoff

报告：schema/迁移 SQL 文件、差异清单、额度结论、导入方案、对 M2（只读 TS API）的建议。不要 `git add` / `commit`。
