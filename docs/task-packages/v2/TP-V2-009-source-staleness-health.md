# TP-V2-009 Source Staleness Health

Version: V2
ID: TP-V2-009
Status: ready
Type: implementation
Depends on: TP-V2-007
Parallel with: TP-V2-008

## Goal

为主动 push 架构定义 stale source 和最近上报状态。

## Context

主动 push 后，server 不再能通过 SSH 主动确认远端状态。离线设备必须通过最后上报时间和 expected interval 判断 stale。

## Scope

- source health 增加 `last_seen_at`、`expected_interval_minutes`、`stale_after_minutes`。
- server 生成 stale 状态。
- 测试今日 0 用量和 stale source 的区别。

## Out of Scope

- 不主动 ping 设备。
- 不通过 SSH 检查设备。
- 不实现通知系统。

## Red Test

- source 超过 stale threshold 后状态为 `stale`。
- 今日 0 用量但刚上报的 source 仍为 `ok`。
- 从未上报的 configured source 显示 `missing` 或 `never_seen`。

## Implementation

- staleness 基于 server 当前时间和 source config。
- source status message 截断且不含敏感路径。
- snapshot 和 Web API 可复用同一 health 计算。

## Acceptance Criteria

- UI 能区分离线、失败和 0 usage。
- staleness 测试使用固定时间，不依赖当前日期。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
rg -n "stale|last_seen|never_seen|expected_interval" tests src docs
```

## Handoff

- 汇报 stale 阈值来源。
- 汇报状态枚举。
- 标出后续通知任务是否需要新增。
