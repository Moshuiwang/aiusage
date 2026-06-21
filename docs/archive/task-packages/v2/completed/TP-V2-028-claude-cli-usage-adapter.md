# TP-V2-028 Claude CLI Usage Adapter

Version: V2
ID: TP-V2-028
Status: done
Type: implementation
Depends on: TP-V2-024
Parallel with: none

## Goal

实现 Claude CLI `/usage` 的显式 fallback adapter：通过可注入 command runner 执行 `claude -p /usage`，解析官方 CLI 输出，并输出 `LimitWindow`。

## Context

TP-V2-018 已有 Claude `/usage` text parser，TP-V2-024 已有 `collect-limits` runtime wiring，TP-V2-026 已有 Claude OAuth adapter。当前缺口是把 Claude CLI `/usage` 作为显式 fallback 接入 runtime，同时不读取 `.claude` 原始日志目录。

## Scope

- 新增 Claude CLI usage provider，使用可注入 command runner。
- 默认命令为 `claude -p /usage --output-format text --no-session-persistence`。
- `collect-limits` 支持显式 `--claude-cli` + `--provider claude`。
- 支持 OAuth adapter 遇到 `missing_credentials` / `unauthorized` 时 fallback 到 CLI provider。
- 非 0 exit 映射为 `provider_failed`。

## Out of Scope

- 不在测试中执行真实 `claude -p /usage`。
- 不读取、同步或解析 `~/.claude` 原始日志目录。
- 不伪造官方额度状态；只解析 Claude CLI 自身输出。
- 不管理 Claude 登录态。
- 不处理 Codex provider。

## Red Test

- fake runner 收到默认 `claude -p /usage` 命令。
- CLI 输出 fixture 可解析为 session/week `LimitWindow`。
- 非 0 exit 映射为 `provider_failed`。
- CLI 未传 `--claude-cli` / `--claude-auth-file` / fixture 时不会启用真实 Claude provider。
- OAuth auth failure 可 fallback 到 CLI provider。

## Implementation

- 扩展 `src/ai_usage_widget/claude_limits_provider.py`。
- 新增 `tests/test_claude_cli_adapter.py`。
- 扩展 `collect-limits` provider factory。

## Acceptance Criteria

- adapter 可用 fake runner 端到端返回 observed Claude windows。
- command runner 不在测试中连接真实 Claude 账号。
- fallback 只发生在 OAuth credential/auth 类错误。
- 旧 OAuth adapter 和 fixture runtime 仍可用。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_claude_cli_adapter tests.test_claude_limits_provider tests.test_cli_limits -v
PYTHONPATH=src python3 -m unittest tests.test_limits_runtime tests.test_limit_windows_store tests.test_snapshot_builder tests.test_web_server -v
rg -n "claude-cli|ClaudeCli|/usage|provider_failed" src tests docs/task-packages/v2 README.md
```

## Handoff

- 汇报真实 Claude CLI 未在测试中执行。
- 汇报 CLI 如何显式启用 Claude CLI adapter。
- 汇报 fallback 条件。
