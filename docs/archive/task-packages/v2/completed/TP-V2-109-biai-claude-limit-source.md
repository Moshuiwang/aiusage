# TP-V2-109 BIAI Claude Limit Source

Version: V2
ID: TP-V2-109
Status: in_progress
Type: implementation
Depends on: TP-V2-108
Parallel with: none

## Goal

Mac 本机没有 Claude 活动时，仍可从 BIAI 看到可验证的 Claude 官方额度窗口，并明确远程来源、新鲜度和不可用状态。

## Context

GitHub Issue #27 / Epic #29 要求 BIAI 每个 OS 用户只在自己的账户上下文读取官方 Claude 状态，并通过既有 limits ingest 按稳定键上报。生产写入和 Mac 安装/启动必须绑定独立 Review 后的精确 head，经人类检查点放行。

## Scope

- 用 fixture 覆盖 BIAI 官方 Claude 状态的可用、断连、过期、重复上报与未知结果对账。
- 保持稳定键 `source_id + provider + window`，相同键重复上报可安全覆盖。
- mobile summary / Mac Popover 展示 BIAI 来源、最后更新时间和暂不可用状态。
- 只读检查 BIAI 各 OS 用户上下文的官方状态和 systemd 元数据；生产写入仅在人类检查点后执行。
- 允许修改 limits runtime/ingest/read model、mobile summary、Mac 客户端与对应测试/fixture。

## Out of Scope

- 不跨用户读取，不接触 `/home/ubuntu`。
- 不从 Mac 读取、同步或解析远程 `.claude` / `.codex` 原始日志。
- 不记录 token、SSH 信息、凭据、原始额度响应或原始 usage 内容。
- 不使用 daily、blocks 或本地估算冒充官方额度。
- 人类检查点前不写 BIAI/生产，不安装或启动 Mac App。

## Red Test

- 先写 BIAI 可用、断连、过期、重复上报和未知写入回读的失败测试。
- 先写 Mac 远程来源、更新时间与暂不可用展示的失败测试。

## Implementation

1. 使用现有 Claude 官方 provider，在各自 OS 用户上下文产生安全的额度窗口。
2. 通过稳定键支持幂等 ingest；未知结果先回读同键，不盲目重试。
3. read model 对过期或断连窗口 fail closed，并保留安全的来源和最后更新时间提示。
4. Mac 卡片可识别 BIAI source label，且本机无 Claude 用量也不影响额度展示。

## Acceptance Criteria

- BIAI 可用时，Mac 显示非空 Claude 官方窗口、比例与重置时间。
- 用户能看出数据来自 BIAI，并知道何时更新。
- 断连、过期或字段变化时显示“暂不可用”，旧数字不冒充实时。
- 重复上报按稳定键收敛；未知写入结果先回读，无法对账即停止。
- 人类检查点后，Mac “今日”“本周”各有一张当前、非空、真实数据截图。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_claude_limits_provider tests.test_cli_limits tests.test_mobile_summary tests.test_server_services -v
npm run cf:native:test -- --run
swift test --package-path clients/macos
```

## Handoff

- 回报脱敏 BIAI 健康、稳定键回读对账、Mac 两张截图、最终 head SHA、PR checks 和 Issue #27 单一证据评论。
