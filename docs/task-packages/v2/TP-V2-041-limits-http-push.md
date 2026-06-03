# TP-V2-041 Limits HTTP Push

Version: V2
ID: TP-V2-041
Status: done
Type: implementation
Depends on: TP-V2-039, TP-V2-040
Parallel with: Mobile app prototype work

## Goal

让本机采集到的多账号官方额度窗口可以通过 HTTP 安全推送到生产 SQLite canonical store，并在生产 dashboard / summary 中展示。

## Context

生产环境不能直接读取本机 `~/.codex`、`~/.claude` 或 `~/.claudew`，官方额度采集必须在对应本机账号上下文运行。现有 runtime 已能从本机 `config/limits.local.json` 采集 `codex-main`、`claude-main`、`claude-w`，但生产尚无接收 limits-only payload 的 HTTP endpoint。

## Scope

- 新增 limits-only HTTP ingest endpoint，复用现有 Bearer token 认证。
- 新增 CLI push 入口，从本机 limits provider 采集窗口并 POST 到服务端。
- 复用 `LimitWindow` contract、`write_limit_windows` 和 snapshot rebuild。
- 文档只更新当前任务包和 V2 index 的 TP-V2-041 条目。

## Out of Scope

- 不把官方额度凭据复制到生产。
- 不提交 `config/limits.local.json`、token、SSH key、原始 usage 日志或生成数据。
- 不把 `ccusage daily`、`ccusage blocks` 或本地估算伪装成官方额度。
- 不处理 iPhone 原型、mobile docs 或 limits doctor 既有未提交改动。

## Red Test

- `tests/test_web_server.py`：`POST /ingest-limits` 在 Bearer token 正确时写入 limit windows 并可由 `/api/summary` 读取，缺失或错误 token 返回 401。
- `tests/test_cli_limits.py`：`push-limits` 使用 fixture 或 limits config 收集窗口，向 HTTP endpoint 推送 payload；`--dry-run` 不发请求。

## Implementation

- 在 server handler 中增加 `/ingest-limits` 分支。
- 校验 payload schema：`schema_version`、`observed_at`、`windows`；逐条调用 `parse_limit_window`。
- 写入 SQLite 后调用 `build_snapshot`。
- 新增轻量 HTTP client helper，避免打印 token。
- 扩展 limits runtime result 以携带采集到的窗口，供 `push-limits` 使用。

## Acceptance Criteria

- 合法 limits push 返回 JSON：`success=true`、`windows_written=N`。
- 未授权 push 返回 401。
- push 后 `/api/summary` 的 `limits` 包含多账号 `source_id`。
- `push-limits --dry-run` 只采集校验，不写本地 DB，也不发 HTTP 请求。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_web_server.TestWebServerSummary.test_ingest_limits_accepts_authorized_payload_and_updates_summary tests.test_web_server.TestWebServerSummary.test_ingest_limits_requires_auth -v
PYTHONPATH=src python3 -m unittest tests.test_cli_limits.TestCliLimits.test_push_limits_fixture_posts_windows tests.test_cli_limits.TestCliLimits.test_push_limits_dry_run_does_not_post -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 回报本机测试结果。
- 如部署生产，回报远端测试、service restart、public health 和 `/api/summary` limits smoke。
