# TP-V2-002 Ingest Auth and Errors

Version: V2
ID: TP-V2-002
Status: done
Type: implementation
Depends on: TP-V2-001
Parallel with: none

## Goal

为 HTTP ingest 增加个人用途认证和结构化错误响应。

## Context

HTTP server 只服务本人设备，但仍不能成为匿名写入接口。认证目标是保护个人 server，不是实现团队权限系统。

## Scope

- 定义 ingest token 的配置读取边界。
- 实现认证失败、缺少 token、token 格式错误的结构化响应。
- 添加 payload size、method、content type 的错误测试。

## Out of Scope

- 不做多用户权限。
- 不做 OAuth。
- 不做 token 管理后台。
- 不把 token 写入仓库、fixture 或日志。

## Red Test

- 缺少认证信息返回 `http_auth_failed`。
- 错误 token 返回 `http_auth_failed`，日志不包含明文 token。
- 非 JSON 请求返回 `http_schema_invalid`。
- 超过 payload size 限制返回结构化错误。

## Implementation

- 使用本地忽略配置或环境变量读取 server ingest token。
- 响应统一包含 `status`、`error_type`、`message`。
- 日志中对 token、路径和长 payload 做截断或脱敏。

## Acceptance Criteria

- 未认证请求不会写入 store。
- 错误响应可被 device pusher 识别。
- 日志不泄露 token 或大段原始 payload。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
rg -n "token|Authorization|http_auth_failed|payload size" tests src docs/task-packages/v2
```

## Handoff

- 汇报认证配置入口。
- 汇报错误类型清单。
- 明确没有提交 token 或本地配置。
