# TP-V2-086 M0 API 合同测试基线

Status: done
Milestone: Cloudflare 迁移 M0（见 `docs/architecture/cloudflare-migration-objective.md`）

## Goal

把"当前后端 API 的对外合同"固化成 golden 合同测试：响应顶层字段集合、类型、状态码、错误枚举。作为后续 TS Worker / D1 实现逐字段一致性的基准线。

## Context

后端将从 Python(HTTPServer)+SQLite 迁到 TS Worker+D1。要证明"迁移后体验不变"，必须先把"迁移前行为"钉死。`tests/` 已有行为测试（`test_web_server.py`、`test_mobile_summary.py`、`test_server_services.py`、`test_ingest_contract.py` 等），但缺少面向 parity 的、对响应字段形状做稳定快照的 golden 合同测试。本任务补这一层，不替代现有测试。

## Scope

- 端点：`/api/summary`、`/api/mobile/summary`、`/api/health`、`/ingest`、`/ingest-limits`、`/login`、`/`、`/static/*`（含鉴权与状态码）。
- 维度：
  - period：`today` / `week` / `month` / `all`；
  - filter：`machine`、`account`；
  - limits：missing / observed；
  - ingest：成功 / 认证失败 / schema 非法 / 幂等重复上报。
- 方法：用确定性 fixture 播种临时 SQLite，调用 service 层（`server_services` / `snapshot_builder` / `mobile_summary`），对响应做「键集合 + 类型 + 枚举值」的稳定快照断言；对易变值（如 `generated_at`、`accepted_at`、文件路径、size_bytes、mtime）做掩码。
- 产出：`tests/fixtures/contract/` 下的 golden 文件 + `tests/test_api_contract.py`。

## Out of Scope

- 任何 TS / D1 / wrangler / 生产 / 运维。
- 不改 `src/` 业务逻辑、不改 API path/method/status、不改 SQLite schema。
- 不修改现有测试文件。

## Red Test

先写会失败的合同测试（golden 不存在或不匹配 → 红），再生成 golden 让其转绿。每个端点至少一条断言「字段形状稳定」。

## Implementation

按 Scope 实现，遵守 `AGENTS.md` 与 TDD。掩码易变字段，保证测试可重复。golden 内不得出现 token、真实绝对路径、原始 usage。

## Acceptance Criteria

- 新合同测试覆盖上述端点与维度。
- `PYTHONPATH=src python3 -m unittest tests.test_api_contract -v` 全绿。
- 全量 `PYTHONPATH=src python3 -m unittest discover -s tests` 无回归。
- diff 仅新增测试与 fixtures，不动 `src/` 业务逻辑（可用 `git diff --stat` 自证）。
- golden 文件经检查不含敏感内容。

## Verification

- 上述两条 unittest 命令的输出。
- `git diff --stat` 显示只新增 `tests/`。

## Handoff

报告：新增文件清单、跑过的测试命令与结果、未覆盖项、对 M1（D1 schema）的建议。不要 `git add` / `commit`。
