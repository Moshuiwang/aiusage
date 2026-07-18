# TP-V2-105 Codex Cumulative Delta Dedupe

Version: V2
ID: TP-V2-105
Status: done
Type: implementation
Depends on: TP-V2-103
Parallel with: none

## Goal

让 Mac 和 Linux 共用的 Codex Usage Ledger 解析器只记录真实新增用量，不再把累计量未增长的重复 `token_count` 当成新用量。

## Context

2026-07-18 核查确认，较新 Codex 版本会写出 timestamp 不同、`last_token_usage` 仍有数值、但 `total_token_usage` 没有增长的事件。当前事件指纹包含 timestamp，因此这些事件会重复入账。Mac 2026-07-16 已确认多算 907,852 tokens；BIAI Linux 也存在同类事件。GitHub issue: #22。

## Scope

- 修改 `src/ai_usage_widget/mswusage_codex.py` 的事件规范化和去重。
- 优先使用同一 session 的 `total_token_usage` 状态识别重复事件；允许 Codex 在压缩、分支或恢复后重置累计量。
- 先按 session 与事件时间稳定排序；不能依赖 active/archived 目录读取顺序。
- incremental 模式先读取候选文件中的窗口前事件作为状态 seed，但只输出窗口内事件。
- 缺少 session 的文件使用内部匿名文件作用域，不能把不同文件错误串成一个累计序列。
- 保持 active + archived、incremental/full-rescan、Asia/Shanghai 分桶合同。
- 扩展 Codex parser 和 pusher 测试。
- 文件读取结果必须显式报告 `scan_complete` 和 read error count，不能静默把不完整扫描当成完整快照。

## Out of Scope

- 不改变 Claude 计数语义。
- 不改变官方额度百分比。
- 不直接写生产 D1 或回填 BIAI；生产升级由 TP-V2-107 执行。
- 不输出原始日志路径、prompt、response 或 raw JSONL。

## Red Test

- 两条 timestamp 不同但累计量不增长的事件，旧实现会双算，新断言只计一次。
- 累计量增长时仍按事件发生时间落入正确小时。
- active/archived 重复会话不会双算。
- 乱序事件与跨窗口重复事件不会多算或漏算。
- 无 session 的两个文件不会共享累计状态。
- 旧格式缺少 `total_token_usage` 时使用兼容 fallback。

## Implementation

1. 先提取候选事件，保留安全 session scope、事件时间、last usage 和 cumulative usage；不输出原始文件信息。
2. 按 scope、事件时间和稳定输入序号排序；相同真实 session 的 active/archived 副本进入同一序列，无 session 文件各自隔离。
3. 在同一 scope 维护已见过的完整累计状态。窗口前事件只负责 seed，不计入输出；窗口内再次出现完全相同的累计状态时标记为 duplicate/no-growth 并跳过。
4. `last_token_usage` 是实际入账事实；累计量只用于重复识别。累计量下降视为可解释的 reset/branch 并开启新 epoch，不能仅因低于历史高水位而丢弃。累计差值与本次用量不一致只记录 non-contiguous transition；只有累计状态分项小于本次用量分项这一结构性矛盾才记录 unresolved mismatch，且该报告不能用于删除或 verified。
5. 缺少累计量的旧格式继续使用稳定事件指纹 fallback，不参与累计状态判断。
6. 在报告中输出 scanned、seeded、accepted、exact-duplicate、no-growth、reset/branch、non-contiguous transition、same-total state change、fallback、read-error 和 unresolved-mismatch 计数，以及 `scan_complete` 与安全覆盖起止时间。

## Acceptance Criteria

- 重复扫描相同输入结果幂等。
- Mac 7/16 复现 fixture 不再多算。
- 既有正常 fixture 数值不回归。
- pusher stable fact key 不变，不制造新重复行。
- incremental 的首个窗口内重复事件能由窗口前 seed 正确跳过。
- 报告 digest 仅基于规范化安全汇总，同一输入重复扫描保持一致。
- 任一读取错误或 unresolved mismatch 都令 `scan_complete=false`，不能进入权威 reconciliation。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_mswusage_codex tests.test_pusher -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
```

## Handoff

- 汇报重复事件被跳过的数量和 token 差额。
- 汇报旧格式 fallback 是否被覆盖。
- 把生产升级和回填交给 TP-V2-107。
