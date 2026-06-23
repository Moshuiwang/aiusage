# TP-V2-088 M2 TS Worker 只读 API

Status: done
Milestone: Cloudflare 迁移 M2（见 `docs/architecture/cloudflare-migration-objective.md`）
依赖：TP-V2-086（合同 golden）、TP-V2-087（D1 schema）

## Goal

用 TypeScript Worker 实现只读路径 `/api/summary` 和 `/api/mobile/summary`，从 D1 测试库 / fixture 返回数据，输出与现有 Python 版**逐字段一致**（用 M0 的 golden 合同测试验证 parity）。**不切生产、不实现写入。**

## Context

当前 Cloudflare 侧只有单文件代理 `cloudflare/aiusage-api-worker.js`，没有 TS 工程、构建、测试运行器或本地 D1 绑定。M2 要把这套基础搭起来，并复刻 `snapshot_builder.py` 的读模型口径与 `mobile_summary.py` 的 DTO 裁剪，**不重新定义口径**。Python 版是"标准答案"，TS 翻译必须对齐。

## Scope

- 搭 TS Worker 工程：构建、测试运行器（vitest + workers pool 或等价）、本地 D1 binding（`wrangler dev --local` / miniflare）。
- 实现只读 `/api/summary`、`/api/mobile/summary`：period `today/week/month/all`、`machine`/`account` filter、limits 字段、trend、source_status。
- 鉴权只读路径：Bearer token 与 session cookie 校验（与现有口径一致）。
- parity（结构级）：用 M0 golden 合同测试驱动，TS 输出字段集合/类型/枚举与 Python 一致；易变字段掩码。
- parity（**数值级**，本里程碑硬要求）：建立单一来源 seed（SQL fixture），同一份 seed 同时喂 Python read model 与 TS Worker；Python 生成 value-golden（完整响应值，掩码易变字段），TS 比对完整响应体**值**逐字段相等——证明的是「相同数字」，不止「相同结构」。

## Out of Scope

- 不实现写入 `/ingest`、`/ingest-limits`（M3）。
- 不切生产、不改 Python 后端、不导真实数据。
- 不实现登录页 / 静态资源托管的最终形态（按需最小桩）。

## Red Test

先写 parity 测试（TS 输出 vs M0 golden）跑红，再实现 Worker 只读逻辑转绿。

## Acceptance Criteria

- 结构级 parity 测试通过：TS `/api/summary`、`/api/mobile/summary` 输出与 Python golden 字段集合/类型/枚举一致。
- **数值级 parity 测试通过**：同一 seed 下 TS 完整响应体的值与 Python value-golden 逐字段相等（易变字段掩码）。
- `wrangler dev --local` 能起并响应只读请求。
- 不触生产、不改 Python 后端。

## Verification

parity 测试输出；本地 `wrangler dev` smoke。

## Handoff

报告：TS 工程结构、parity 结果、未对齐的口径（如有）、对 M3（写入 + 双写）的建议。不要 `git add` / `commit`。
