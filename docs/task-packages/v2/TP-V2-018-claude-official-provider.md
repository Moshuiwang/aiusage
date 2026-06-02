# TP-V2-018 Claude Official Provider

Version: V2
ID: TP-V2-018
Status: ready
Type: implementation
Depends on: TP-V2-016
Parallel with: none

## Goal

实现 Claude Code 官方额度 provider 的离线可测核心：OAuth Usage API parser 优先，CLI `/usage` parser fallback。

## Context

Claude Code limits 不能从 `~/.claude/projects` 日志推断。首选读取 Claude OAuth credentials 后调用 Usage API；失败时可以通过 Claude CLI PTY 手动触发 `/usage` 并解析官方 CLI 展示。

## Scope

- 新增 Claude OAuth usage response fixture parser。
- 新增 Claude CLI `/usage` 文本 fixture parser。
- 定义 provider ordering：OAuth API -> CLI `/usage` -> Web API placeholder。

## Out of Scope

- 不读取真实 `~/.claude/.credentials.json`。
- 不访问 macOS Keychain。
- 不启动真实 `claude` CLI。
- 不调用 Claude Web API。

## Red Test

- OAuth fixture 可输出 current session 和 weekly windows。
- CLI `/usage` 文本 fixture 可解析 used percent 和 reset time。
- OAuth 成功时不触发 CLI fallback。
- 本地 project history 不能输出 official reset。

## Implementation

- 新增 Claude provider parser 模块。
- 新增 `tests/fixtures/claude_oauth_usage.json`。
- 新增 `tests/fixtures/claude_usage_cli.txt`。
- 新增 fake provider runner。

## Acceptance Criteria

- Claude provider 可从 OAuth fixture 输出 observed limits。
- CLI fallback 输出 `source_type: "official_cli"` 或等价来源。
- 失败状态结构化。
- 不读取真实 Claude 配置。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_claude_limits_provider -v
rg -n "Claude|oauth|/usage|official_cli" docs src tests
```

## Handoff

- 汇报 OAuth fixture 字段。
- 汇报 CLI `/usage` parser 限制。
- 明确 Keychain / Web API 尚未接入。
