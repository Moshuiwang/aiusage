# TP-V2-103 Usage Ledger Menu Popover MVP

Version: V2
ID: TP-V2-103
Status: done
Type: implementation
Depends on: TP-V2-060, TP-V2-061, TP-V2-064, TP-V2-089
Parallel with: none

## Goal

让当前 macOS menu popover 继续使用现有 `/api/mobile/summary`，但其中 today / week / month / all 的用量总数来自 Usage Ledger 新口径，不再因为 Codex session 归档导致历史日/月用量回落。

## Context

已完成的 Usage Ledger PRD、架构、数据库和接口文档确认了两个关键产品口径：

- Codex 使用 `token_count.timestamp + last_token_usage` 入账，并且必须扫描 active sessions 和 archived sessions。
- Claude 使用 assistant message 的 top-level `timestamp + message.usage` 入账，同一个 `message.id + requestId` 只算最终有效 usage。
- 小时事实可以每 N 分钟重报最近窗口，服务端按稳定键去重后当前小时可更新；上一个小时在本小时首次上报后自然稳定。
- 历史全量重算和日常增量上报要分开，避免日常任务每次做全盘扫描。

当前 D1 已有 `usage_hourly_facts` 和账号归因表，Mac menu popover 也已经只读 `/api/mobile/summary`。本任务优先把这些能力连成用户可见闭环。

## Scope

- 本机采集：
  - Codex 本机扫描默认覆盖 `~/.codex/sessions` 和 `~/.codex/archived_sessions`。
  - Claude 本机扫描覆盖当前 OS 用户的 `~/.claude/projects/**/*.jsonl`。
  - CLI 支持 `incremental` 和 `full-rescan` 两种口径；日常 pusher 使用 `incremental`。
  - 不能输出原始日志路径、文件名、prompt、response、tool output、token 或 raw JSONL。
- 上报：
  - Codex 和 Claude 小时事实写入现有 `usage_hourly_facts` payload。
  - 账号无法确认时，使用 `unconfirmed_local_source`，popover 不显示成已确认账号。
- 服务端读模型：
  - `/api/summary` 和 `/api/mobile/summary` 在有 `usage_hourly_facts` 时，用这些小时事实生成周期总量、趋势和来源拆分。
  - 对同一 source/date/agent，Usage Ledger 事实优先于旧 `usage_daily`。
  - 旧 `usage_daily` 在没有新事实时继续作为 fallback，保护既有 daily baseline。
- Cloudflare native Worker / D1 与本地 Python snapshot builder 保持同口径。

## Out of Scope

- 不改 macOS menu popover 的视觉布局。
- 不在本轮做 iPhone、Watch、Android 或 Windows 真机验收。
- 不直接修改生产账户文件。
- 不提交 SSH key、token、原始 usage 日志、`config/sources.local.json` 或生成数据。
- 不把 `ccusage daily`、`ccusage blocks` 或本地估算伪装成官方额度状态。
- 不做完整历史生产 backfill 的自动化运维；如需修正线上历史，需要显式运行 `full-rescan` 上报。

## Red Test

- Codex parser：fixture 同时放在 active 和 archived，断言两边都会被扫描且重复事件不会双算。
- Claude parser：同一 `message.id + requestId` 出现多次时只保留最终有效 usage。
- Pusher：没有 `ai_accounts` 时仍上报 Codex / Claude 小时事实，归因是 `unconfirmed_local_source`。
- Snapshot / Worker read model：当 `usage_hourly_facts` 与旧 `usage_daily` 同时存在时，popover 周期总量使用 ledger 事实，不随旧 daily 缩小。
- Mobile summary：`/api/mobile/summary` 的 period total 与 ledger 汇总一致。

## Implementation

1. 补任务包和索引，确认本轮只做 Usage Ledger 到现有 popover API 的 MVP。
2. 先写失败测试，覆盖 parser、pusher、Python snapshot 和 Cloudflare Worker read model。
3. 扩展 Codex scanner：active + archived、去重、`incremental/full-rescan` 参数。
4. 新增 Claude assistant usage scanner：按 `message.id + requestId` 去重，不上传原始内容。
5. 扩展 pusher：把 Codex / Claude scanner 输出转为 `usage_hourly_facts`；账号不确定时用未确认归因。
6. 扩展 Python snapshot builder 和 native Worker read model：ledger facts 优先生成用户可见周期总量。
7. 运行 targeted Python、Swift/Worker 合同测试和一次本地 API 验证。

## Acceptance Criteria

- 当前 Mac menu popover 消费的 `/api/mobile/summary` 中，today/week/month/all 的 `period.total_tokens` 可由 Usage Ledger 小时事实驱动。
- Codex session 归档不会让已上报的历史小时事实变少。
- 日常增量上报不会每次做全量扫描；全量重算必须显式选择。
- 账号不确定时，数据仍可入账，但显示为未确认来源，不伪装成官方账号。
- 没有 ledger facts 的旧日期仍走既有 daily fallback。
- 所有测试输出和 payload 不泄漏本机原始日志路径或内容。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_mswusage_codex tests.test_mswusage_claude tests.test_pusher tests.test_snapshot_builder tests.test_mobile_summary -v
npm test --prefix cloudflare/native-worker -- --run
swift test --package-path clients/macos
```

如执行线上或本机真实上报，还需要补充：

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli mswusage-codex --json --timezone Asia/Shanghai --mode full-rescan
PYTHONPATH=src python3 -m ai_usage_widget.cli mswusage-claude --json --timezone Asia/Shanghai --mode full-rescan
curl -sS "https://aiusage.chunbai.com/api/mobile/summary?period=today" -H "Authorization: Bearer $AI_USAGE_TOKEN"
```

## Handoff

- 汇报哪些数据源已经切到 Usage Ledger。
- 汇报 `/api/mobile/summary` 的用户可见 period total 验证结果。
- 汇报是否执行真实 `full-rescan` 上报；未执行则说明线上 popover 仍需等待数据入账或部署后刷新。
- 汇报测试命令和结果。
