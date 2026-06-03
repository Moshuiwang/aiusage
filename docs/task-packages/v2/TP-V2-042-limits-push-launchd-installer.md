# TP-V2-042 Limits Push Launchd Installer

Version: V2
ID: TP-V2-042
Status: done
Type: implementation
Depends on: TP-V2-041
Parallel with: Mobile app prototype work

## Goal

把本机官方额度 `push-limits` 从手动命令变成可安装的 macOS LaunchAgent 定时任务，持续推送到生产 `/ingest-limits`。

## Context

TP-V2-041 已完成本机采集并 HTTP push 到生产。当前缺口是持续自动更新：生产不能读取本机 credential，所以 scheduler 必须运行在拥有 Codex / Claude 登录态的当前 macOS 用户上下文。

## Scope

- 新增可测试的 macOS launchd scheduler installer。
- 生成 runner shell、LaunchAgent plist、日志目录和 0600 token env 文件。
- 新增 CLI：`install-limits-scheduler`，支持 `--dry-run` 和 `--write-token-from-env`。
- 安装后可用 `launchctl bootstrap/kickstart` 激活。
- 文档更新只覆盖 scheduler 的 limits push 自动安装路径。

## Out of Scope

- 不提交 token、SSH key、`config/limits.local.json`、生成数据或 launchd 本机生成文件。
- 不把生产 credential 复制进 repo。
- 不修改 iPhone prototype、mobile docs、TP-V2-038 删除或 limits doctor 既有脏改。
- 不用 root 代跑本机 Claude / Codex credential。

## Red Test

- `tests/test_limits_scheduler.py`：installer 生成的 plist 指向 runner，包含 30 分钟 interval、stdout/stderr 日志路径，且不包含 token。
- `tests/test_limits_scheduler.py`：token env 文件由环境变量写入，权限为 `0600`。
- `tests/test_cli_limits_scheduler.py`：`install-limits-scheduler --dry-run` 输出计划但不写文件；正式安装写入 plist/runner/env。

## Implementation

- 新增 `limits_scheduler.py`，使用 `plistlib` 生成 LaunchAgent。
- runner 使用 `/bin/zsh`，进入 repo，source token env 文件，设置 `PYTHONPATH=src` 后执行 `push-limits`。
- CLI 默认 interval 为 1800 秒，避免高频采集。
- CLI 输出脱敏 JSON，不打印 token。

## Acceptance Criteria

- dry-run 不写文件。
- 正式安装写入 runner、plist、日志目录和 env 文件。
- plist/runner 不包含明文 token。
- 本机能 `launchctl bootstrap` 并 `kickstart` 成功触发一次。
- 生产 summary 能继续看到 limits 更新。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_limits_scheduler tests.test_cli_limits_scheduler -v
PYTHONPATH=src python3 -m unittest tests.test_cli_limits tests.test_web_server tests.test_limits_runtime tests.test_claude_cli_adapter -v
```

## Handoff

- 回报生成文件路径、launchctl 状态、日志路径和生产 smoke 结果。
