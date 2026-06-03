# TP-V2-039 Limits Multi Account CLI

Version: V2
ID: TP-V2-039
Status: done
Type: implementation
Depends on: TP-V2-029, TP-V2-030, TP-V2-037
Parallel with: none

## Goal

让 official limits runtime 支持同一 provider 的多个账号实例，特别是默认 `claude` 和带 `CLAUDE_CONFIG_DIR` 的第二个 Claude CLI 账号，且写入 SQLite / snapshot 时不会互相覆盖。

## Context

当前 `collect-limits --limits-config` 以 provider name 作为实例 key。多个 `claude` provider 会互相覆盖，SQLite `limit_windows` 主键也只包含 `provider/source_type/window`。用户本机有两个 Claude 账号：默认 `claude` 和 `claudew` alias，后者等价于 `CLAUDE_CONFIG_DIR=/Users/wangzhipeng/.claudew claude`。

## Scope

- 扩展 limits config，允许 provider 配置可选 `source_id`。
- 扩展 Claude CLI provider，允许配置命令环境变量，以支持 `CLAUDE_CONFIG_DIR`。
- 扩展 runtime provider key，使同一 provider 的多个实例都能执行。
- 扩展 `limit_windows` schema / upsert / snapshot，按 `source_id` 区分多个账号。
- 更新示例配置和最小文档说明。

## Out of Scope

- 不读取或提交真实 Codex / Claude token。
- 不创建生产 `config/limits.local.json`。
- 不实现 limits HTTP push。
- 不改 dashboard 视觉布局；只保证 snapshot/API 能区分多账号。

## Red Test

- 新增 config 测试：两个 `claude` provider 可用不同 `source_id` 和 `env` 通过解析。
- 新增 CLI adapter 测试：Claude CLI runner 接收配置的 env。
- 新增 store 测试：两个 `claude` limit windows 使用不同 `source_id` 不互相覆盖。
- 新增 runtime 测试：同一 provider name 的多个实例都会 collect。

## Implementation

- 为 `LimitWindow` 增加 `source_id`，默认回退到 provider 名。
- `limit_windows` 增加 `source_id` 列，并把主键迁移到 `source_id/provider/source_type/window`。
- `limits_config` 支持 `source_id` 和安全的 `env` map，继续拒绝 inline secret 字段。
- `ClaudeCliUsageProvider` 支持传入 env，并在 subprocess 中合并环境。
- `collect-limits` 从 config 构建多个 provider 实例 key。

## Acceptance Criteria

- `codex-main`、`claude-main`、`claude-w` 这类实例可以共存。
- 两个 Claude CLI 账号写入 SQLite 后保留两组 session/week windows。
- `--check-config` 输出只包含脱敏 plan，不输出 env value。
- `--dry-run` 仍不写 SQLite/latest。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests/test_limits_config.py tests/test_claude_cli_adapter.py tests/test_claude_limits_provider.py tests/test_codex_limits_provider.py tests/test_limit_windows_store.py tests/test_limits_runtime.py tests/test_cli_limits.py tests/test_snapshot_builder.py -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报新增配置字段、迁移行为、验证命令。
- 如未执行真实 `claude` / `claudew` smoke，明确说明。
