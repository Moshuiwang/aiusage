# TP-V2-040 Claude CLI Limit Message Parser

Version: V2
ID: TP-V2-040
Status: done
Type: implementation
Depends on: TP-V2-039
Parallel with: none

## Goal

当 Claude CLI 只返回 `hit your session limit · resets ...` 文本时，将其降级解析为可写入的 session limit window，避免 `claudew` 在限额期整条 provider 失败。

## Context

`claudew` 等价于 `CLAUDE_CONFIG_DIR=/Users/wangzhipeng/.claudew claude`。当前该账号运行 `claude -p ...` 返回 session limit 文本，但没有 `active_limits.json`。TP-V2-039 已支持多账号和 `env`，还需要对这个 CLI limit message 做最小可用解析。

## Scope

- 扩展 Claude CLI parser，识别 session limit reset 文本。
- 只生成 session window，不伪造 weekly window。
- 保持 `--dry-run` 不写 SQLite/latest。
- 更新测试和最小文档说明。

## Out of Scope

- 不读取 Claude 原始日志目录。
- 不推断 weekly quota。
- 不输出或提交账号、token、原始响应。

## Red Test

- 为 `parse_claude_cli_usage` 增加 limit message fixture 测试。
- 断言输出 `window=session`、`used_percent=100`、`remaining_percent=0`、`source_type=official_cli_limit_message`。

## Implementation

- 在常规 `/usage` regex 失败前或失败后识别 `resets HH:MMam/pm (Timezone)`。
- 基于 `observed_at` 的日期和 reset time 拼出 ISO reset timestamp。
- 如果 reset time 已早于 observed time，则按次日处理。

## Acceptance Criteria

- `claudew` 限额文本 dry-run 不再导致 provider 失败。
- 只写一个 session window。
- 全量测试通过。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests/test_claude_limits_provider.py tests/test_claude_cli_adapter.py tests/test_cli_limits.py -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报 `claudew` dry-run 是否成功。
- 如果没有 weekly window，明确说明这是 limit message 的数据边界。
