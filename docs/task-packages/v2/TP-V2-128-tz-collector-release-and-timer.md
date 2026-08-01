# TP-V2-128 TZ Collector Release And Timer

Version: V2
ID: TP-V2-128
Status: done
Type: implementation
Depends on: TP-V2-123, TP-V2-125
Parallel with: none

## Goal

让 TZ 两个采集器使用可追溯的仓库代码和持久日历 timer，避免现场版本漂移及重启后静默停摆。

## Context

2026-08-01 只读核查发现两个 TZ 账户当前 HTTP 可用，但运行目录无 Git，pusher hash 不属于当前仓库历史；timer 仍使用 `OnBootSec + OnUnitActiveSec`，未采用仓库唯一日历模板。

## Scope

- 逐账户备份并部署当前 `pusher.py` 与 `http_identity.py`。
- 逐账户部署仓库用户级 calendar timer。
- 保持配置、token、parser、原始 usage 数据和其他依赖不变。
- 每账户做 service、D1 写后读、future NextElapse 和 hash 验收。

## Out of Scope

- 不修改生产账户配置。
- 不读取或输出原始 Claude/Codex 日志。
- 不执行历史 full-rescan/reconciliation。
- 不直接修改 D1。

## Red Test

- 产品 UA 与默认 urllib 在线对照。
- 用户级 timer 模板必须是 persistent calendar，禁止 `OnUnitActiveSec`。
- pusher/http identity 回归测试必须通过。

## Implementation

1. 先 tz-wangzp，成功后再 tz-wangzhipeng。
2. 每账户保存旧文件和 timer 回滚副本。
3. 部署代码与 timer，等待可能的 Persistent 补跑完成。
4. 验证 service exit 0、D1 推进、timer waiting+future Next、hash 一致。

## Acceptance Criteria

- 两账户最近一次 service 均 exit 0，D1 状态为 ok。
- 两个 timer 均 active/waiting 且有未来触发时间。
- 两账户运行时代码 hash 与仓库一致。
- 旧文件可回滚且没有修改任何凭据或配置。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_pusher tests.test_systemd_timer_contract -v
git diff --check
```

## Handoff

- 回报逐账户 service、D1、NextElapse、hash 和备份位置，不回报凭据或原始日志。
