# TP-V2-030 Limits Dry Run

Version: V2
ID: TP-V2-030
Status: done
Type: implementation
Depends on: TP-V2-029
Parallel with: none

## Goal

为 `collect-limits` 新增 `--dry-run`：执行 provider/config 校验和采集路径，但不写 SQLite、不生成 snapshot，方便 scheduler 部署前验证。

## Context

TP-V2-029 已经提供 `config/limits.local.json` 配置契约。上线 launchd/systemd 前需要一个不会改生产数据的 smoke 命令，用于验证 provider command、auth path、usage URL 和 config shape。

## Scope

- `collect-limits` 新增 `--dry-run`。
- dry-run 会执行 provider collect，并返回 provider 状态。
- dry-run 不调用 `write_limit_windows`，不调用 `build_snapshot`。
- dry-run 输出 JSON 中标记 `dry_run: true`。
- 更新 README / operations docs。

## Out of Scope

- 不执行真实 provider smoke。
- 不创建 scheduler 文件。
- 不修改生产 SQLite。
- 不改变非 dry-run 行为。

## Red Test

- `LimitsRuntime.collect(..., dry_run=True)` 不创建 SQLite 文件。
- `collect-limits --dry-run --provider-fixture ...` 不写入 SQLite / latest。
- 非 dry-run 旧 fixture runtime 仍写 SQLite。

## Implementation

- 扩展 `src/ai_usage_widget/limits_runtime.py`。
- 扩展 `src/ai_usage_widget/cli.py`。
- 补 `tests/test_limits_runtime.py` / `tests/test_cli_limits.py`。
- 更新 README / operations docs。

## Acceptance Criteria

- dry-run 可用于 fixture 和 limits config。
- dry-run 不产生数据副作用。
- CLI JSON 清楚标记 `dry_run`。
- 全量测试通过。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_limits_runtime tests.test_cli_limits -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
rg -n "dry-run|dry_run|collect-limits" src tests docs README.md
```

## Handoff

- 汇报 dry-run 不写 SQLite/latest。
- 汇报真实 provider smoke 仍需显式本地执行。
