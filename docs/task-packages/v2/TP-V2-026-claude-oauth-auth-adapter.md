# TP-V2-026 Claude OAuth Auth Adapter

Version: V2
ID: TP-V2-026
Status: done
Type: implementation
Depends on: TP-V2-024
Parallel with: none

## Goal

实现 Claude OAuth Usage API provider 的安全 adapter：从显式指定的 auth path 读取 token，通过可注入 HTTP client 获取 usage payload，并输出 `LimitWindow`。

## Context

TP-V2-018 已有 Claude OAuth payload parser，TP-V2-024 已有 `collect-limits` runtime wiring。当前缺口是 Claude provider 的真实 adapter 边界：credential loader、HTTP request shape、错误映射，以及不泄露 secret。

## Scope

- 新增 Claude auth loader，仅读取显式传入路径。
- 支持常见 auth JSON token shape。
- 新增 OAuth Usage HTTP client adapter，测试中用 fake HTTP client。
- 将 usage response 接入 `parse_claude_oauth_usage`。
- 错误映射为 `missing_credentials`、`unauthorized`、`provider_failed`。
- `collect-limits` 支持显式 `--claude-auth-file` + `--claude-usage-url` + `--provider claude`。

## Out of Scope

- 不默认读取本机 Claude 配置或生产凭据。
- 不读取、同步或解析 `~/.claude` 原始日志目录。
- 不在测试中调用真实 Claude 服务。
- 不实现 Claude CLI `/usage` real fallback。
- 不处理 Codex provider。

## Red Test

- auth loader 可从 fixture 提取 access token，但不会把 token 放进错误信息。
- 缺失 auth 文件返回 `missing_credentials`。
- OAuth HTTP adapter 使用 `Authorization: Bearer <token>` 请求显式 usage URL。
- 401/403 映射为 `unauthorized`。
- CLI 未传 `--claude-auth-file` 和 `--claude-usage-url` 时不会启用真实 Claude provider。

## Implementation

- 扩展 `src/ai_usage_widget/claude_limits_provider.py`。
- 新增测试 fixture `tests/fixtures/claude_auth_sample.json`。
- 新增 `tests/test_claude_oauth_adapter.py`。
- 扩展 `collect-limits` provider factory。

## Acceptance Criteria

- adapter 可用 fake HTTP client 端到端返回 observed Claude windows。
- 真实 credential 文件只在显式路径传入时读取。
- token 不出现在异常文本、CLI 输出或 SQLite。
- 旧 fixture runtime 仍可用。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_claude_oauth_adapter tests.test_cli_limits tests.test_limits_runtime -v
PYTHONPATH=src python3 -m unittest tests.test_claude_limits_provider tests.test_limit_windows_store tests.test_snapshot_builder tests.test_web_server -v
rg -n "claude-auth-file|claude-usage-url|ClaudeOAuth|missing_credentials|unauthorized" src tests docs/task-packages/v2 README.md
```

## Handoff

- 汇报支持的 auth JSON shape。
- 汇报真实网络仍未在测试中调用。
- 汇报 CLI 如何显式启用 Claude OAuth adapter。
