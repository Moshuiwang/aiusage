# TP-V2-037 Limits Doctor Readiness

Version: V2
ID: TP-V2-037
Status: done
Type: implementation
Depends on: TP-V2-033
Parallel with: none

## Goal

新增 `collect-limits --doctor` readiness 检查，用脱敏 JSON 判断真实 provider smoke 前缺什么配置、命令或本机路径。

## Context

真实 provider smoke 需要本机 `config/limits.local.json` 和本机登录态。当前不能直接读取 token 或执行 provider；需要先有一个低风险诊断命令，把配置是否存在、provider 是否可执行、auth path 是否存在这些条件结构化输出。

## Scope

- 新增 limits doctor 模块。
- 为 `collect-limits` 增加 `--doctor`。
- 检查 `--limits-config` 是否存在并能解析。
- 对 Codex 检查 auth path、`codex` 命令、可选 RPC socket。
- 对 Claude 检查 auth path、usage URL 配置和 `claude` 命令。
- 输出 JSON 不包含真实 path、URL、token 或 secret。

## Out of Scope

- 不读取 auth 文件内容。
- 不执行 Codex / Claude / Antigravity provider。
- 不写 SQLite、latest snapshot 或生产账户文件。
- 不接 Antigravity real Language Server reader。

## Red Test

- 新增 doctor 单元测试，先确认缺少实现时失败。
- 新增 CLI 测试，确认 `collect-limits --doctor` 输出脱敏 JSON。

## Implementation

- 实现 `run_limits_doctor`，支持注入 command resolver 便于测试。
- CLI 在 `--doctor` 时直接输出 doctor report。
- 只返回布尔状态和能力摘要，不输出敏感路径。

## Acceptance Criteria

- 缺少 `--limits-config` 时返回 JSON failure，不是普通 stderr 字符串。
- 存在配置时输出 provider readiness。
- 输出不包含 auth path、socket path 或 usage URL。
- doctor 不创建 SQLite/latest 文件。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests/test_limits_doctor.py tests/test_cli_limits.py -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m ai_usage_widget.cli collect-limits --doctor
```

## Handoff

- 汇报 doctor 是 smoke 前置诊断，不替代真实 provider smoke。
