# TP-V2-001 HTTP Ingest Contract

Version: V2
ID: TP-V2-001
Status: done
Type: implementation
Depends on: none
Parallel with: TP-V2-004

## Goal

定义个人 HTTP server 的 usage ingest payload 和响应契约。

## Context

V2 不再由 Mac 或 server 通过 SSH 抓远端 usage。每台终端在自己的 OS 用户上下文运行 `ccusage daily --json --timezone <tz>`，再主动 push 结构化 payload 到 HTTP server。

## Scope

- 新增或调整 HTTP ingest schema。
- 新增 usage push fixture。
- 新增 server 侧 request validation 单元测试。
- 允许修改文档中显式引用的 schema 或 fixture 文件。

## Out of Scope

- 不实现真实网络监听。
- 不实现认证策略细节。
- 不写 SQLite。
- 不做 Web dashboard。
- 不读取 `.claude`、`.codex` 原始日志目录。

## Red Test

- malformed payload 缺少 `schema_version` 时失败。
- payload 缺少 `source_id`、`host`、`os_user`、`timezone`、`observed_at` 任一字段时失败。
- payload 上传原始日志路径或原始日志内容字段时失败。
- valid fixture 能解析成内部 ingest request。

## Implementation

- 定义最小 payload 字段：
  - `schema_version`
  - `source_id`
  - `host`
  - `os_user`
  - `platform`
  - `timezone`
  - `observed_at`
  - `collection_window`
  - `usage_daily`
- 定义最小响应字段：
  - `status`
  - `source_id`
  - `accepted_at`
  - `message`
- 对未知必需字段缺失、类型错误、超大 payload 返回结构化错误。

## Acceptance Criteria

- usage ingest contract 有 fixture。
- valid fixture 通过 validation。
- invalid fixture 输出稳定错误类型。
- schema 不包含 SSH 字段。
- schema 不允许原始 usage 日志目录。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
rg -n "ssh|SSH|\\.claude|\\.codex" docs/task-packages/v2/TP-V2-001-http-ingest-contract.md
```

## Handoff

- 汇报新增或修改的 schema、fixture、测试文件。
- 汇报失败 payload 的错误类型。
- 说明是否触碰真实配置或生产数据。
