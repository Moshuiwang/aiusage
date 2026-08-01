# TP-V2-125 Linux Collector Timer Reliability

Version: V2
ID: TP-V2-125
Status: done
Type: implementation
Depends on: TP-V2-107
Parallel with: TP-V2-122, TP-V2-123, TP-V2-124

## Goal

让 BIAI Linux 用量采集器始终有可核查的下一次执行计划，避免 timer 显示 enabled/active 但长期不再触发。

## Context

2026-08-01 线上核查发现 5 个用户级 timer 都是 enabled/active，但 `SubState=elapsed`、`NextElapse` 为空，最后一次 D1/source report 停在约 2.5 天前。线上 unit 使用 `OnUnitActiveSec=30min`，而仓库运行手册使用 `OnCalendar=*:0/30` 和 `Persistent=true`。

## Scope

- 提供可部署、可测试的用户级 timer 模板和 BIAI system-level drop-in。
- 固定 5 个 BIAI timer 到同 basename service 的部署清单。
- 使用固定半小时日历计划和 missed-run 恢复。
- 逐个升级 5 个 OS 用户，保留旧 unit 作为回滚证据。
- 每个用户都核查下一次执行时间，并至少验证一次真实 D1 回写。

## Out of Scope

- 不跨用户读取原始 Claude/Codex 日志。
- 不修改或输出 token。
- 不让 root 代替普通用户运行采集。
- 不用 enabled/active 单独作为成功证据。

## Red Test

- 仓库必须存在用户级 timer 模板。
- 模板必须包含 `OnCalendar=*:0/30`、`Persistent=true`、`AccuracySec=1min`。
- 模板禁止使用本次已静默停摆的 `OnUnitActiveSec`。

## Implementation

1. 新增唯一来源的 systemd 用户 timer 模板和 BIAI system-level drop-in。
2. 用清单固定 5 个 timer/service 映射，drop-in 不覆盖 `Unit=`。
3. 文档指向模板，避免线上手抄漂移。
4. 逐 unit 备份、部署、daemon-reload、enable/restart。
5. 若 `Persistent=true` 立即补跑，先等待 service 完成，不能把 `active/running` 误判为失败。
6. 核对 `NextElapse`，必要时触发一次 service，并从 D1 写后读。

## Acceptance Criteria

- 5 个 timer 都有非空且未来的下一次触发时间。
- 5 个 service 都完成一次各自用户上下文的真实上报。
- D1 对应 source report 更新时间推进，页面来源不再静默过期。
- 回归测试阻止重新引入 `OnUnitActiveSec`。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_systemd_timer_contract -v
git diff --check
```

## Handoff

- 回报 5 个 timer 的下一次执行时间、service 结果、D1 写后读时间和回滚文件位置。
