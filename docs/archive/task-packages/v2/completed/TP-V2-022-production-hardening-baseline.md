# TP-V2-022 Production Hardening Baseline

Version: V2
ID: TP-V2-022
Status: done
Type: implementation
Depends on: TP-V2-013, TP-V2-014
Parallel with: none

## Goal

为线上 HTTP push 部署补齐第一层加固：token 轮换、SQLite 在线备份、pusher 单实例锁。

## Context

三台机器已经通过 HTTP push 上报真实 usage。线上风险优先来自单 token 不可局部撤销、SQLite 缺少一致性备份入口，以及 timer 触发时上一次 pusher 未结束导致进程堆积。

## Scope

- 服务端支持多个 active ingest token。
- CLI 支持 SQLite online backup 命令。
- 终端侧 `push` 支持 lock file，避免同一用户上下文重复运行。
- 更新 operations 和 scheduler 文档。

## Out of Scope

- 不实现 token 管理后台。
- 不自动生成或提交真实 token。
- 不实现 provider limits。
- 不实现告警系统。

## Red Test

- `TokenAuthenticator` 接受 legacy token 和 labeled rotated token。
- SQLite backup 创建可通过 `PRAGMA integrity_check` 的备份文件。
- pusher lock 拒绝第二个 owner。

## Implementation

- 新增 `auth.py`、`backup.py`、`lock.py`。
- `server` 读取单 token 和 token specs。
- `cli push` 增加 `--lock-file`。
- `cli backup` 使用 SQLite online backup API。

## Acceptance Criteria

- 旧 `AI_USAGE_INGEST_TOKEN` 仍兼容。
- 新 `AI_USAGE_INGEST_TOKENS` 支持逗号分隔的 `label:token`。
- backup 不直接复制 WAL 半截状态。
- lock 已存在时 pusher 退出失败并返回结构化错误。
- 文档不包含真实 token。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_auth tests.test_backup tests.test_lock tests.test_cli_pusher tests.test_web_server -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
rg -n "AI_USAGE_INGEST_TOKENS|--lock-file|backup" README.md docs src tests
```

## Handoff

- 汇报 token 轮换格式。
- 汇报 backup 命令。
- 汇报 pusher lock 配置方式。
