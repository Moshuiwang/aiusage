# TP-V2-106 Collector Accuracy Coverage Contract

Version: V2
ID: TP-V2-106
Status: done
Type: implementation
Depends on: TP-V2-105
Parallel with: none

## Goal

让用户能区分“采集任务运行成功”和“数据经过完整性校验”，避免来源显示 `ok` 但历史明显缺失。

## Context

BIAI 五个 systemd timer 都成功、API source status 都是 `ok`，但 7 月 12–15 日历史没有完成全量回填。现有状态只证明进程和 HTTP push 成功，不证明时间范围完整或数值准确。GitHub issue: #23。

## Scope

- 为 mswusage report / hourly facts 增加安全的 collector metadata：版本、mode、lookback、覆盖范围、扫描/接受/跳过计数和 accuracy 状态。
- 让 ingest/storage/read model 以 source + agent 为单位保留安全诊断，即使该来源本次用量为 0。
- 兼容缺少新字段的旧采集器，并标为 `unknown` / `unverified`。
- 增加 API/诊断测试，不泄露原始日志信息。

## Out of Scope

- 不改变 source connectivity `ok/stale/failed` 的既有语义。
- 不在客户端展示原始诊断明细。
- 不直接升级 BIAI 或回填历史。

## Red Test

- incremental 成功但没有 full-rescan 证据时，accuracy 不能是 verified。
- full-rescan 报告包含完整覆盖范围、`scan_complete=true`、read error=0、unresolved mismatch=0 和幂等证据时，才可标为 verified。
- no-growth/重复事件存在时，报告必须显示跳过数量。
- 旧 payload 继续被接收，但 accuracy 为 unknown。
- 两次 full-rescan 的安全 digest 不一致时不能 verified。
- parser 版本变化后必须重新核验，不能沿用旧 verified。

## Implementation

1. 定义最小、可选、向后兼容的 collector metadata 合同：collector version、parser schema、mode、lookback、coverage、counts、safe report digest，以及由服务器独立复算的事实 digest。
2. 定义权威状态机：旧 payload=`unknown`；incremental 或首次 full-rescan=`unverified`；仅当两次报告同版本、同覆盖、同 report digest、同 facts digest、`scan_complete=true`、read error=0、unresolved mismatch=0 且服务器 reconciliation 成功时=`verified`；其余情况=`unverified`。
3. 由 parser/pusher 生成单次运行证据；由服务器保存连续运行证据并决定状态，客户端不得自行宣称 verified。
4. 以独立 source accuracy 记录保存状态，不能依赖 hourly fact，因此零用量来源也可显示核验结果。
5. read model 输出 connectivity 与 accuracy 两栏，避免 `ok` 被误读为准确；旧采集器再次上报或 parser 版本变化时立即撤销既有 verified，重新完成双跑后才可恢复。

## Acceptance Criteria

- 用户能看到来源是“在线但历史未核验”或“在线且已核验”。
- mode、覆盖范围和 collector version 可追踪。
- 老采集器不会被拒绝，但不会冒充 verified。
- verified 必须有服务器记录的两次独立 full-rescan 一致证据和 reconciliation 成功证据。
- 不完整扫描即使两次 digest 相同也不能 verified，且不得触发删除。
- 零用量来源也能得到准确性状态。
- 无敏感路径、凭据或原始内容进入 payload/API。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_pusher tests.test_ingest tests.test_storage_sqlite tests.test_snapshot_builder tests.test_mobile_summary -v
npm test --prefix cloudflare/native-worker -- --run
git diff --check
```

## Handoff

- 汇报新旧 collector 在 API 中的准确性状态。
- 把 BIAI 生产验证交给 TP-V2-107。
