# TP-V2-032 Limits Smoke Handoff

Version: V2
ID: TP-V2-032
Status: done
Type: documentation
Depends on: TP-V2-031
Parallel with: none

## Goal

更新 handoff 文档，补齐 official limits provider 的真实 smoke 前置步骤、dry-run 命令和当前验证结果。

## Context

TP-V2-024 到 TP-V2-031 已经完成 official limits runtime、provider adapters、config、dry-run 和 scheduler 模板。现有 `docs/handoff.md` 仍停留在 V2 ingest/dashboard 初期，需要同步当前状态。

## Scope

- 更新 `docs/handoff.md`。
- 写清 `config/limits.local.json` 不提交。
- 写清 dry-run 与正式运行命令。
- 写清真实 smoke 会触碰本机 Claude/Codex 登录态，需要本机 config 明确存在。

## Out of Scope

- 不执行真实 provider smoke。
- 不写真实 credential path。
- 不修改代码。

## Red Test

- handoff 中出现 `official limits`。
- handoff 中出现 `config/limits.local.json`。
- handoff 中出现 `collect-limits --limits-config` 和 `--dry-run`。
- handoff 中出现当前 Python / Swift 验证数量。

## Implementation

- 只修改 `docs/handoff.md` 和任务索引。

## Acceptance Criteria

- 交接文档能指导下一位 agent 做真实 smoke。
- 文档不包含真实 token 或 auth path。

## Verification

```bash
rg -n "official limits|limits.local|collect-limits|dry-run|123|Swift" docs/handoff.md docs/task-packages/v2/TP-V2-032-limits-smoke-handoff.md
```

## Handoff

- 汇报这是 handoff 文档更新，不含真实 smoke 执行。
