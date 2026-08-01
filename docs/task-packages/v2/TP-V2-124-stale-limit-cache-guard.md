# TP-V2-124 Stale Limit Cache Guard

Version: V2
ID: TP-V2-124
Status: done
Type: implementation
Depends on: TP-V2-041, TP-V2-109
Parallel with: none

## Goal

旧额度缓存不能被重新标成当前、可信且采集成功，生产写入也必须拒绝这种假新鲜窗口。

## Context

2026-08-01 本机额度采集恢复联网后，Claude `active_limits_cache` 中 5 月已过期的窗口被写成 13:20 `observed_at`、`status=ok`。用户读模型会过滤该来源，但 D1 和采集器成功状态仍不诚实。

## Scope

- cached limits 一律标为不可用/非官方，不能是 observed + ok。
- 额度运行时只有拿到当前官方窗口才报告 provider `ok`。
- Native Worker 拒绝 active cache 冒充 ok/observed，以及 reset 已不晚于 observed 的 ok 窗口。
- 保持有效 Codex 窗口可独立上传，Claude 不可用时明确降级。

## Out of Scope

- 不把缓存估算改造成官方额度。
- 不读取或输出认证文件内容。
- 不删除生产历史行。

## Red Test

- active cache 解析结果不能是 `status=ok` 或 `confidence=observed`。
- 只有 cached/unknown 窗口时 provider runtime 不能返回成功。
- Native ingest 对伪装成 ok/observed 的 active cache 返回 400。
- Native ingest 对 reset 已过期但 status=ok 的窗口返回 400。

## Implementation

1. 在 provider 边界把 active cache 降级成 unavailable + estimated。
2. 在 runtime 以当前官方窗口决定 provider 成功状态。
3. 在生产写入边界增加双重校验。

## Acceptance Criteria

- 旧 Claude 缓存不再产生成功采集结论。
- D1 不再接受新的 cached ok/observed 行。
- Codex 当前官方窗口仍正常可见。
- Claude 当前不可验证时用户只看到暂不可用，不显示旧百分比。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_claude_limits_provider tests.test_claude_cli_adapter tests.test_limits_runtime -v
npm run cf:native:test -- --run
git diff --check
```

## Handoff

- 回报红绿测试、线上 D1 窗口状态和用户摘要降级结果。
