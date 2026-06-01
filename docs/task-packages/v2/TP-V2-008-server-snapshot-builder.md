# TP-V2-008 Server Snapshot Builder

Version: V2
ID: TP-V2-008
Status: ready
Type: implementation
Depends on: TP-V2-007
Parallel with: none

## Goal

从 server SQLite canonical store 构建展示快照。

## Context

Web dashboard 可以直接走 Web API，但 Widget 和 CLI report 仍适合读取 versioned snapshot。snapshot 必须由 store 派生，不由展示层现场聚合复杂逻辑。

## Scope

- 从 SQLite 构建 summary、groups、items、source_status。
- 原子写入 `latest.json`。
- 保留或明确迁移旧 Widget 所需字段。

## Out of Scope

- 不做 Web dashboard。
- 不做 limits 展示。
- 不读取真实生产 SQLite。

## Red Test

- 多 source fixture 生成今日 summary。
- 失败 source 出现在 `source_status`。
- 缺少 limits 时 snapshot 仍合法。
- 写入使用临时目录且原子化。

## Implementation

- snapshot schema version 保持明确。
- groups 至少包含 by_machine、by_account、by_agent。
- snapshot builder 不执行 `ccusage` 或 HTTP 请求。

## Acceptance Criteria

- fixture 到 snapshot 的 contract test 通过。
- Widget 兼容字段策略明确。
- snapshot 中不包含 token、SSH key 或原始日志。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
rg -n "schema_version|source_status|groups|limits" tests src docs
```

## Handoff

- 汇报 snapshot 字段。
- 汇报兼容字段。
- 汇报是否同步 Widget 后续任务。
