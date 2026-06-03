# TP-V2-029 Limits Config Contract

Version: V2
ID: TP-V2-029
Status: done
Type: implementation
Depends on: TP-V2-024
Parallel with: none

## Goal

新增 `collect-limits` 的本地配置契约，用 `config/limits.local.json` 描述 provider 启用方式、SQLite 和 snapshot 路径，便于后续 launchd/systemd 调度。

## Context

TP-V2-024 到 TP-V2-028 已经提供 fixture runtime、Codex WHAM、Codex RPC、Claude OAuth 和 Claude CLI adapters。当前命令行参数已经足够验证，但部署时会变成很长的命令。需要一个不提交真实凭据、不存 token 明文的本地 config contract。

## Scope

- 新增 limits config loader。
- 新增 `config/limits.example.json`。
- `collect-limits` 支持 `--limits-config`。
- config 只允许 credential path / usage URL / provider 开关，不允许内联 token/secret。
- CLI 参数仍保留，config 作为部署友好的入口。

## Out of Scope

- 不提交 `config/limits.local.json`。
- 不写真实 auth file path。
- 不执行真实 Codex/Claude provider。
- 不改 existing ingest device config。
- 不改 scheduler 安装流程。

## Red Test

- example/config payload 可解析出 enabled providers、sqlite/latest/timezone。
- config 中出现 token/secret/access_token 字段会被拒绝。
- Codex provider 缺少 `auth_file` 且未启用 `rpc` 会被拒绝。
- Claude provider 缺少 OAuth pair 且未启用 `cli` 会被拒绝。
- `collect-limits --limits-config` 可用 fake providers 执行。

## Implementation

- 新增 `src/ai_usage_widget/limits_config.py`。
- 新增 `tests/test_limits_config.py`。
- 扩展 `src/ai_usage_widget/cli.py` provider factory。
- 更新 README / operations docs。

## Acceptance Criteria

- config loader 不保留 raw token。
- config 可同时启用 Codex 和 Claude。
- CLI 参数和 fixture runtime 旧入口仍可用。
- 全量测试通过。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_limits_config tests.test_cli_limits -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
rg -n "limits-config|limits.example|limits.local|LimitsConfig" src tests docs README.md config
```

## Handoff

- 汇报 config 字段边界。
- 汇报真实 local config 仍需用户在本机自行创建且不提交。
