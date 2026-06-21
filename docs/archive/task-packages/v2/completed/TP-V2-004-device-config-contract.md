# TP-V2-004 Device Config Contract

Version: V2
ID: TP-V2-004
Status: done
Type: implementation
Depends on: none
Parallel with: TP-V2-001

## Goal

定义终端侧 pusher 的本地配置契约。

## Context

每台 Mac、Linux server、Windows desktop 都需要在自己的账户上下文运行采集并 push 到 HTTP server。配置必须显式包含 source identity、server URL、timezone 和 timeout。

## Scope

- 新增或调整 device config schema。
- 添加 Mac、Linux、Windows fixture。
- 校验必填字段、重复 source id、未知平台、timezone 缺失。

## Out of Scope

- 不执行真实 `ccusage`。
- 不发真实 HTTP 请求。
- 不保存 token 明文 fixture。
- 不写 server store。

## Red Test

- 缺少 `source_id`、`server_url`、`timezone`、`platform` 任一字段时报错。
- Windows fixture 可通过 schema validation。
- 配置包含 SSH 字段时报错或被拒绝。

## Implementation

- 定义字段：
  - `schema_version`
  - `source_id`
  - `host`
  - `os_user`
  - `platform`
  - `timezone`
  - `server_url`
  - `timeout_seconds`
  - `token_env`
- `token_env` 只保存环境变量名，不保存 token 值。

## Acceptance Criteria

- 三个平台 fixture 都能通过。
- invalid config 错误类型稳定。
- schema 不要求 SSH host/user/key。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
rg -n "server_url|token_env|platform|ssh|SSH" config tests src docs/task-packages/v2
```

## Handoff

- 汇报 device config 字段。
- 汇报 fixture 覆盖的平台。
- 明确没有提交本地 token。
