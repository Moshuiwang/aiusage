# TP-V2-024 Official Limits Runtime Wiring

Version: V2
ID: TP-V2-024
Status: done
Type: implementation
Depends on: TP-V2-021
Parallel with: none

## Goal

新增 official limits runtime wiring，把 provider 输出写入 SQLite `limit_windows`，并可重建 snapshot。

## Context

TP-V2-016 到 TP-V2-021 已完成 limits contract、Codex / Claude offline parser、SQLite store、snapshot/API 和 Web 展示。当前缺少一个可执行入口把 provider result 串到 store/snapshot。

## Scope

- 新增 `collect-limits` CLI 或等价入口。
- 新增 runtime service，支持注入 fake provider runner。
- 写入 `limit_windows`。
- 可选触发 snapshot rebuild。
- provider 失败时写结构化 failed / missing 状态。

## Out of Scope

- 不读取真实 `~/.codex/auth.json`。
- 不读取真实 `~/.claude/.credentials.json` 或 macOS Keychain。
- 不调用真实网络 API。
- 不启动真实 Codex / Claude CLI。
- 不实现 Antigravity provider。
- 不修改 Dashboard UI。

## Red Test

- fake Codex / Claude provider 的 observed windows 可通过 runtime 写入 `limit_windows`。
- CLI `collect-limits --provider-fixture` 可写 SQLite 并生成 snapshot `limits`。
- provider missing credentials / failure 不回退 local history，而是写 failed window。
- 未启用 provider 时返回结构化错误，不写 secret 字段。

## Implementation

- 新增 `src/ai_usage_widget/limits_runtime.py`。
- 扩展 `src/ai_usage_widget/cli.py` 增加 `collect-limits`。
- 新增测试 `tests/test_limits_runtime.py` 和 CLI 测试。
- 只使用 fixture/fake provider，不接真实凭据。

## Acceptance Criteria

- runtime 可端到端写 `limit_windows`。
- snapshot `limits` 能看到 runtime 写入的结果。
- 失败 provider 产生 `status: provider_failed` 或 `missing_credentials`。
- 不读取真实 credentials，不访问网络。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_limits_runtime tests.test_cli_limits -v
PYTHONPATH=src python3 -m unittest tests.test_limits_contract tests.test_codex_limits_provider tests.test_claude_limits_provider tests.test_limit_windows_store tests.test_snapshot_builder tests.test_web_server -v
rg -n "collect-limits|LimitsRuntime|provider_failed|missing_credentials" src tests docs/task-packages/v2
```

## Handoff

- 汇报 CLI 使用方式。
- 汇报 fake/offline provider 边界。
- 汇报真实 provider adapter 仍未接入。
