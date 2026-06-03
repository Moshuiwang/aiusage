# TP-V2-033 Limits Config Check

Version: V2
ID: TP-V2-033
Status: done
Type: implementation
Depends on: TP-V2-029
Parallel with: none

## Goal

为 `collect-limits` 增加 `--check-config`：只校验 `config/limits.local.json` 并输出脱敏 provider plan，不执行真实 Codex/Claude provider，不写 SQLite/latest。

## Context

真实 provider smoke 会触碰本机 Claude/Codex 登录态。TP-V2-029 已提供 limits config，TP-V2-030 已提供 dry-run。还需要一个更轻量的 config-only 检查命令，帮助部署前先确认配置形状和 provider mode。

## Scope

- `collect-limits --limits-config <path> --check-config`。
- 输出 JSON：`success`、`check_config`、`timezone`、`sqlite`、`latest`、`providers`。
- provider plan 只输出布尔开关，不输出 credential path、socket path 或 URL。
- 不实例化真实 provider，不调用 runtime collect。

## Out of Scope

- 不检查 auth file 是否存在。
- 不连接 Codex app-server。
- 不执行 Claude CLI。
- 不写 SQLite/latest。

## Red Test

- config summary 不包含 `auth_file`、`usage_url`、`rpc_sock` 字段值。
- CLI `--check-config` 可返回脱敏 provider plan。
- CLI `--check-config` 没有 `--limits-config` 时失败。

## Implementation

- 扩展 `src/ai_usage_widget/limits_config.py`。
- 扩展 `src/ai_usage_widget/cli.py`。
- 补 `tests/test_limits_config.py` / `tests/test_cli_limits.py`。

## Acceptance Criteria

- check-config 只读 config，不执行 provider。
- 输出不泄露本机路径或 URL。
- 全量测试通过。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_limits_config tests.test_cli_limits -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
rg -n "check-config|check_config|summarize_limits_config" src tests docs README.md
```

## Handoff

- 汇报这是 config-only 检查，不替代真实 smoke。
