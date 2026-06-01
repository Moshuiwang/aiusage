# TP-V2-005 Device Pusher Fake HTTP

Version: V2
ID: TP-V2-005
Status: ready
Type: implementation
Depends on: TP-V2-004
Parallel with: none

## Goal

让终端侧 pusher 可测试地执行本机采集并通过 fake HTTP client push。

## Context

开发测试不能依赖真实 server、真实网络或当天真实 usage。pusher 需要可注入 command executor 和 HTTP client。

## Scope

- pusher 接收 fake executor 输出。
- pusher 使用 fake HTTP client 发送 payload。
- 捕获 timeout、HTTP status、错误响应和 duration。

## Out of Scope

- 不实现 server ingest。
- 不跑真实 `ccusage`。
- 不监听真实端口。
- 不处理 scheduler。

## Red Test

- fake executor 成功时，fake HTTP client 收到一次 POST。
- fake HTTP 401 时，pusher 返回 `http_auth_failed`。
- fake HTTP timeout 时，pusher 返回 `timeout`。
- command failed 时不发 HTTP 请求。

## Implementation

- 抽象 command executor。
- 抽象 HTTP client。
- pusher 返回结构化 source status。

## Acceptance Criteria

- pusher 单元测试不访问网络。
- command failure 和 HTTP failure 可区分。
- source status 可进入后续 snapshot。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
rg -n "Fake|fake|http_auth_failed|timeout" tests src
```

## Handoff

- 汇报 fake executor / fake HTTP client 的接口。
- 汇报错误状态映射。
- 说明没有运行真实采集。
