# TP-V2-016 Official Limits Contract

Version: V2
ID: TP-V2-016
Status: done
Type: implementation
Depends on: TP-V2-010
Parallel with: none

## Goal

定义官方 limits provider 的统一 payload、fixture 和 parser contract。

## Context

`ccusage daily`、SQLite history 和 session JSONL 只能做历史 token/cost 统计，不能推断官方 quota/reset。Claude Code、Codex、后续 Antigravity 需要独立 provider 输出 official limit facts。

## Scope

- 新增 official limits payload fixture。
- 新增 parser / model 单元测试。
- 定义字段：provider、window、used_percent、remaining_percent、reset_at、window_duration_minutes、observed_at、source_type、confidence、status。
- 允许更新 `docs/subscription-usage-source.md` 的字段说明。

## Out of Scope

- 不调用真实 Claude/Codex/Antigravity API。
- 不读取真实 `~/.claude` 或 `~/.codex`。
- 不写 SQLite。
- 不改 Dashboard UI。

## Red Test

- 缺少 `provider`、`window`、`reset_at` 或 `observed_at` 时 parser 报稳定错误。
- `confidence != "observed"` 的 payload 不能被标记为 official。
- 本地历史估算 source_type 不能输出为 official reset。

## Implementation

- 新增 `src/ai_usage_widget/limits.py` 或等价模块。
- 新增 `tests/fixtures/limits_official_sample.json`。
- 新增 `tests/test_limits_contract.py`。
- parser 输出内部 `LimitWindow` 数据结构。

## Acceptance Criteria

- official limits fixture 可解析。
- malformed fixture 有结构化错误。
- parser 不接受本地 history 推导的 official reset。
- 字段命名与 snapshot `limits` 兼容。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_limits_contract -v
rg -n "official|reset_at|confidence|source_type" docs/subscription-usage-source.md src tests
```

## Handoff

- 汇报 limits payload shape。
- 汇报 fixture 路径和 parser 错误类型。
- 明确没有读取真实 provider 凭据。
