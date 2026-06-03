# TP-V2-003 Ingest Idempotent Upsert

Version: V2
ID: TP-V2-003
Status: done
Type: implementation
Depends on: TP-V2-001
Parallel with: TP-V2-006

## Goal

让重复 push 同一 source/date/agent 的 daily usage 时不会产生重复事实。

## Context

终端 pusher 可能因为重试、网络恢复或定时任务重复运行而多次上传同一天数据。server 必须用稳定 key upsert。

## Scope

- 定义 ingest 幂等 key。
- 在 server 侧验证重复 payload 的处理结果。
- 为后续 SQLite 写入提供稳定事实 key。

## Out of Scope

- 不实现完整 SQLite schema。
- 不做历史冲突 UI。
- 不做跨 source 自动合并。

## Red Test

- 同一 `source_id`、`date`、`agent`、`model` 重复上传只产生一个目标 fact。
- 同一 source 的更新 payload 会覆盖当前日可变 token totals，并保留 observed metadata。
- 不同 source 的同一天同 agent 不会互相覆盖。

## Implementation

- 使用 `source_id + date + agent + model` 作为 usage fact 基础 key。
- 对 source report 使用 `source_id + observed_at` 或 collection run id 记录状态。
- 把幂等结果标记为 `accepted`、`updated` 或 `duplicate`。

## Acceptance Criteria

- 重试安全。
- 多设备隔离。
- 幂等行为有测试 fixture。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
rg -n "idempot|duplicate|upsert|source_id" tests src docs/task-packages/v2
```

## Handoff

- 汇报幂等 key。
- 汇报重复 payload 的响应状态。
- 标出还没有落到 SQLite 的后续任务。
