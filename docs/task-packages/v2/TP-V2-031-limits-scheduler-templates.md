# TP-V2-031 Limits Scheduler Templates

Version: V2
ID: TP-V2-031
Status: done
Type: documentation
Depends on: TP-V2-030
Parallel with: none

## Goal

补齐 official limits provider 的 scheduler 模板，让 `collect-limits --limits-config` 能以当前 OS 用户身份定时运行，并提供部署前 dry-run 命令。

## Context

TP-V2-029 提供 `config/limits.local.json`，TP-V2-030 提供 `--dry-run`。当前 `docs/schedulers.md` 主要覆盖 usage pusher，还缺 limits provider 的 launchd/systemd/Windows Task Scheduler 模板。

## Scope

- 更新 `docs/schedulers.md`。
- 增加 macOS launchd limits collector 示例。
- 增加 Linux user systemd limits collector 示例。
- 增加 Windows Task Scheduler limits collector 示例。
- 明确必须在拥有 Codex/Claude credential 的 OS 用户上下文运行。

## Out of Scope

- 不生成真实 plist/service 文件。
- 不写真实 auth path。
- 不执行真实 provider。
- 不修改 production config。

## Red Test

- 文档应出现 `collect-limits --limits-config`。
- 文档应出现 `--dry-run`。
- 文档应出现 `config/limits.local.json`。
- 文档应明确不要用 root 代跑用户级 Claude/Codex credential。

## Implementation

- 只修改 `docs/schedulers.md` 和任务索引。

## Acceptance Criteria

- 三个平台都有 limits scheduler 示例。
- dry-run 和正式运行命令分开。
- 文档不包含真实 token 或 auth 文件路径。

## Verification

```bash
rg -n "collect-limits|limits.local|dry-run|root|LaunchAgent|systemd|Task Scheduler" docs/schedulers.md docs/task-packages/v2/TP-V2-031-limits-scheduler-templates.md
```

## Handoff

- 汇报这是模板，不会自动安装 scheduler。
