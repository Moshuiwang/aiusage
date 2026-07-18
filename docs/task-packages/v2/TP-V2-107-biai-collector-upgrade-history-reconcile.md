# TP-V2-107 BIAI Collector Upgrade And History Reconcile

Version: V2
ID: TP-V2-107
Status: done
Type: deployment
Depends on: TP-V2-105, TP-V2-106
Parallel with: none

## Goal

升级 BIAI 五个 Linux 用户的共享采集器，安全修正 2026-07-12 至今的历史用量，并证明机器、D1 和用户可见 API 逐日一致。

## Context

日常 incremental 默认只回看 48 小时。2026-07-18 核查确认，BIAI 7/16–7/18 与服务器一致，但 7/12–7/15 明显缺少历史。当前 full-rescan 又会受 TP-V2-105 的重复事件问题影响，因此必须先修 parser，再回填。GitHub issue: #24。

## Scope

- 只读备份现有 `/opt/ai-usage-widget` 部署版本和 unit 状态。
- 先升级 `wangzp` canary，再升级共享 collector。
- 每个用户在自己的 OS 上下文运行两次 full-rescan，验证幂等。
- 对五个 source 执行受控历史 push/backfill。
- full-rescan 使用权威 snapshot reconciliation：仅在完整性门槛通过后，服务器按同一 source + agent + 覆盖窗口原子删除本次快照已不存在的旧小时事实。
- 核对 systemd、D1、`/api/mobile/summary` 的逐日值和覆盖状态。

## Out of Scope

- 不读取或同步远程 raw `~/.codex` / `~/.claude` 到 Mac。
- 不接触 `/home/ubuntu`。
- 不跨用户采集。
- 不改额度数据。

## Red Test

- 部署前保存 7/12 至当前的机器汇总、D1/API 汇总和差异表。
- 相同 full-rescan 两次结果必须一致，否则停止回填。
- 回填前必须证明旧错误小时可由 reconciliation 删除，而不是只覆盖仍存在的小时。
- `scan_complete=false`、任一读取错误或 unresolved mismatch 时，只允许 upsert，禁止 reconciliation 删除。

## Implementation

1. 记录部署前 unit/result/timer、API 基线，并备份五个 source 在目标日期范围内的 D1 facts 与准确性状态。
2. 将候选版本放入独立 release 路径；`wangzp` canary 直接运行候选版本，不切换共享 `/opt` 当前版本，也不触发 timer。
3. canary 双跑 full-rescan，校验 safe digest、覆盖范围和逐小时结果一致。
4. 暂停五个 timer，等待在途任务结束；切换共享 release 后再逐用户双跑，避免 incremental 与回填并发写。
5. 对每个成功双跑的 source + agent 执行带 reconciliation 的 full-rescan push；单个来源失败不继续下一个写入步骤。
6. 恢复 timer，确认首轮 incremental 成功；等待 D1/read model 更新并逐日对账。
7. 回滚同时覆盖 collector release、timer 状态和目标范围 D1 facts；任何一层校验失败立即停止后续来源。

## Acceptance Criteria

- 五个 timer 保持成功且来源在线。
- 五用户 collector version、mode、覆盖范围可见。
- full-rescan 双跑幂等。
- reconciliation 能清除修复后不再存在的旧错误小时，且不能越过声明覆盖范围。
- source + agent + coverage 的 upsert 与删除必须原子完成，失败时保留原数据。
- 7/12 至当前：机器、D1、week/month/all API 每日值一致。
- 无用量用户明确为真实 0。
- 有明确回滚证据且无敏感信息泄露。

## Verification

```bash
systemctl list-timers --all | grep ai-usage-pusher
curl -sS 'https://aiusage.chunbai.com/api/mobile/summary?period=week' -H 'Authorization: Bearer ***'
```

## Handoff

- 汇报部署版本、五用户状态、回填前后逐日差异和剩余风险。
