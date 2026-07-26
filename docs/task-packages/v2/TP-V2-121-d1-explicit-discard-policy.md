# TP-V2-121 D1 Explicit Discard Policy

Version: V2
ID: TP-V2-121
Status: done
Type: implementation
Depends on: TP-V2-120
Parallel with: none

## Goal

把已确认的历史数据取舍固化为显式、可审计的 D1 补齐策略：放弃旧
`agent=all` 候选，以及仅因缺少 AI 账号映射而无法补齐的候选。

## Context

生产 dry-run 发现旧 `agent=all` 与具体身份明细重叠，同时有部分历史候选没有
可靠 AI 账号归属。产品明确接受这两类历史数据不补齐，但不接受静默丢弃或放宽
其他身份安全门禁。

## Scope

- 为补齐工具增加两个默认关闭的显式丢弃开关。
- 只跳过 `agent=all` 和“仅缺账号映射”两类候选。
- 报告丢弃的身份键、日/小时行数、原始 token 和用户可见历史缺口。
- 区分已接受口径 `parity` 与完整旧表口径 `full_legacy_parity`。
- 更新生产交接命令与验收说明。

## Out of Scope

- 不访问或修改生产 D1。
- 不自动丢弃机器、系统账号、多账号或来源身份歧义。
- 不改变旧表只读、模型明细为空、批次与定向回滚合同。
- 不部署 Worker。

## Red Test

- 显式开启策略时，`agent=all` 和缺账号候选必须被跳过并形成结构化报告。
- 补齐可执行部分后，已接受口径差异为 0，完整旧表口径保留明确缺口。
- 未开启策略时继续保持 fail-closed。

## Implementation

1. 在 `BackfillOptions` 和 CLI 增加两个显式开关。
2. 在身份解析前丢弃 `agent=all`；只消化缺账号这一种身份错误。
3. 保存丢弃计划并输出聚合统计，不输出凭据或原始日志。
4. 以精确日键从验收基线扣除已接受丢弃数据，同时保留完整旧口径对比。

## Acceptance Criteria

- 默认行为不变，身份歧义仍停止。
- 两个开关同时开启时，生产快照 dry-run 状态可为 `ready` 且 unresolved 为 0。
- 其他身份歧义不能被丢弃开关掩盖。
- SQL 仍只写四张新表，旧表保持只读。
- 报告能解释所有主动接受的历史数据缺口。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_d1_legacy_backfill -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- Ops 必须显式传递两个开关，不能依赖默认值。
- 发布前重新采集生产快照并审核 `discarded` 与 `full_legacy_parity`。
- 本任务不授权生产写入或 Worker 发布。
