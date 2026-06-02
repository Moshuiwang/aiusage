# TP-V2-017 Codex Official Provider

Version: V2
ID: TP-V2-017
Status: ready
Type: implementation
Depends on: TP-V2-016
Parallel with: none

## Goal

实现 Codex 官方额度 provider 的离线可测核心：OAuth/WHAM parser 优先，CLI RPC parser fallback。

## Context

CodexBar 源码核验结论：

- App runtime auto 顺序：OAuth/WHAM usage -> Codex CLI RPC。
- OAuth/WHAM 读取 `~/.codex/auth.json` token，调用 `GET https://chatgpt.com/backend-api/wham/usage`。
- CLI RPC 启动 `codex -s read-only -a untrusted app-server`，调用 `account/read` 和 `account/rateLimits/read`。
- CLI runtime 的 web dashboard 优先级不作为本项目后台采集默认方案。

## Scope

- 新增 WHAM usage response fixture parser。
- 新增 `account/rateLimits/read` response fixture parser。
- 实现 provider strategy ordering，不在测试中启动真实 `codex app-server`。
- 输出统一 `LimitWindow`。

## Out of Scope

- 不读取真实 `~/.codex/auth.json`。
- 不调用真实 `chatgpt.com`。
- 不启动真实 Codex CLI。
- 不接 OpenAI web dashboard cookies。

## Red Test

- Auto strategy 在 OAuth fixture 可用时选择 WHAM result。
- OAuth unauthorized / missing credentials 才进入 CLI RPC fallback。
- WHAM `primary_window` / `secondary_window` 可映射为 session / week。
- RPC `account/rateLimits/read` 可映射 resetsAt、usedPercent、windowDurationMins。

## Implementation

- 新增 Codex provider parser 模块。
- 新增 `tests/fixtures/codex_wham_usage.json`。
- 新增 `tests/fixtures/codex_rpc_rate_limits.json`。
- 新增 fake fetcher / fake executor，不访问网络。

## Acceptance Criteria

- Codex provider 可从 WHAM fixture 输出 5h / week windows。
- Codex provider 可从 RPC fixture 输出 fallback windows。
- Auto priority 被测试固定为 WHAM first、RPC second。
- 错误状态不会回退到本地 token history。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_codex_limits_provider -v
rg -n "wham|rateLimits|account/rateLimits/read|Codex" docs src tests
```

## Handoff

- 汇报 CodexBar 源码依据。
- 汇报实现的 fixture shape。
- 明确真实 API / CLI 启动仍未接入。
