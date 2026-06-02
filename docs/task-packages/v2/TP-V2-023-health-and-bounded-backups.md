# TP-V2-023 Health and Bounded Backups

Version: V2
ID: TP-V2-023
Status: done
Type: implementation
Depends on: TP-V2-022
Parallel with: none

## Goal

给线上服务补每日自动备份和低开销健康检查，并确保备份不会无限增长撑爆机器。

## Context

`vpn2` 是个人 usage 汇聚服务端，SQLite 是 canonical store。备份必须有保留策略；health API 只能读少量元数据和现有 snapshot，不能触发重建或大表扫描。

## Scope

- `backup` CLI 增加 `--keep` 和 `--max-total-mb`。
- `/api/health` 返回 DB 文件状态、snapshot 更新时间和 source status 计数。
- 文档说明每日 systemd backup timer 示例。
- 线上 `vpn2` 配置每日 backup timer，使用小保留窗口。

## Out of Scope

- 不做外部告警系统。
- 不上传备份到云存储。
- 不在 health API 返回 token、原始 payload 或原始日志。

## Red Test

- 备份命令会按数量和总容量删除旧备份。
- `/api/health` 未认证返回 401。
- `/api/health` 已认证返回低成本状态结构。

## Implementation

- 扩展 `backup_sqlite` 和 CLI 参数。
- 在 server 增加 `handle_get_health`。
- 使用现有 `latest.json` 计算 source 状态，不触发 snapshot rebuild。

## Acceptance Criteria

- 默认最多保留 14 份、512 MB。
- 线上 timer 使用最多 7 份、128 MB。
- health API 可用于 smoke check。
- 全量测试通过。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_backup tests.test_web_server tests.test_cli_pusher -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
rg -n "api/health|--max-total-mb|--keep|backup" README.md docs src tests
```

## Handoff

- 汇报线上 timer 名称。
- 汇报保留策略。
- 汇报 health API smoke 输出。
