# TP-V2-036 Antigravity Limits Fixture Parser

Version: V2
ID: TP-V2-036
Status: done
Type: implementation
Depends on: TP-V2-016
Parallel with: none

## Goal

为 Antigravity official limits provider 建立离线可测的 fixture parser baseline，覆盖候选 Language Server `GetUserStatus` 和 fallback `GetCommandModelConfigs` 输出形状。

## Context

架构已预留 Antigravity provider，但不能在单元测试中启动真实 Language Server，也不能把本地历史 token 推断伪装成官方额度。现有 Claude / Codex provider 采用 fixture parser 和可注入 reader 模式。

## Scope

- 新增 Antigravity provider parser 模块。
- 新增 `GetUserStatus` 和 `GetCommandModelConfigs` fixture。
- 新增单元测试覆盖 official window 映射、fallback 顺序和 malformed payload。
- 更新状态和架构文档。

## Out of Scope

- 不启动真实 Antigravity Language Server。
- 不读取用户本地 Antigravity 配置、缓存或日志。
- 不接入 `collect-limits --limits-config` 真实 runtime。

## Red Test

- 先新增 `tests/test_antigravity_limits_provider.py`，确认因 `ai_usage_widget.antigravity_limits_provider` 缺失而失败。

## Implementation

- 实现 `parse_antigravity_user_status`。
- 实现 `parse_antigravity_command_model_configs`。
- 实现 `AntigravityLimitsProvider`，优先 user status，status reader 不可用时 fallback command model configs reader。

## Acceptance Criteria

- Antigravity windows 输出 `provider=antigravity`。
- remaining fraction / remaining percent 可转换为 used / remaining percent。
- 输出 `source_type=language_server` 或 `language_server_config`，`confidence=observed`，并满足 `LimitWindow.is_official`。
- 缺 reset time 的 payload 被拒绝。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests/test_antigravity_limits_provider.py -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报这是 Antigravity 离线 fixture parser baseline，不包含真实 Language Server reader。
