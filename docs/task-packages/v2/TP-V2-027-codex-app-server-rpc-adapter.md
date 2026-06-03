# TP-V2-027 Codex App-Server RPC Adapter

Version: V2
ID: TP-V2-027
Status: done
Type: implementation
Depends on: TP-V2-024
Parallel with: none

## Goal

实现 Codex `app-server proxy` 的显式 RPC adapter：发送 `account/rateLimits/read` 请求，解析 app-server schema response，并输出 `LimitWindow`。

## Context

TP-V2-017 已有 Codex CLI RPC parser fixture，TP-V2-024 已有 `collect-limits` runtime wiring。当前缺口是把 Codex app-server 的真实 RPC schema 接到 provider，同时避免默认启动 daemon 或读取生产文件。

## Scope

- 新增 Codex app-server RPC provider，使用可注入 command runner。
- 默认命令为 `codex app-server proxy`，支持显式 `--sock`。
- 发送 `account/rateLimits/read` JSON request。
- 支持 app-server schema：`rateLimits.primary/secondary.usedPercent/resetsAt/windowDurationMins`。
- `resetsAt` 支持 app-server 的 epoch seconds，也保留既有 ISO fixture。
- `collect-limits` 支持显式 `--codex-rpc` + `--provider codex`。

## Out of Scope

- 不默认启动或管理 `codex app-server daemon`。
- 不读取 `~/.codex` auth 文件。
- 不在测试中连接真实 app-server socket。
- 不改变 WHAM adapter。
- 不处理 Claude provider。

## Red Test

- fake runner 收到 `codex app-server proxy` 命令和 `account/rateLimits/read` request。
- app-server schema response 可解析为 session/week `LimitWindow`。
- 非 0 exit 映射为 `provider_failed`。
- CLI 未传 `--codex-rpc` / `--codex-auth-file` / fixture 时不会启用真实 Codex provider。

## Implementation

- 扩展 `src/ai_usage_widget/codex_limits_provider.py`。
- 新增 `tests/test_codex_app_server_rpc_adapter.py`。
- 扩展 `collect-limits` provider factory。

## Acceptance Criteria

- adapter 可用 fake runner 端到端返回 observed Codex windows。
- request method 固定为 `account/rateLimits/read`。
- command/socket 只来自显式 CLI 参数或默认 Codex CLI，不测试真实 socket。
- 旧 Codex fixture parser 和 WHAM adapter 仍可用。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_codex_app_server_rpc_adapter tests.test_codex_limits_provider tests.test_cli_limits -v
PYTHONPATH=src python3 -m unittest tests.test_limits_runtime tests.test_limit_windows_store tests.test_snapshot_builder tests.test_web_server -v
rg -n "codex-rpc|CodexAppServer|account/rateLimits/read|rateLimits" src tests docs/task-packages/v2 README.md
```

## Handoff

- 汇报真实 app-server 未在测试中连接。
- 汇报 CLI 如何显式启用 Codex RPC adapter。
- 汇报仍未自动管理 daemon 生命周期。
