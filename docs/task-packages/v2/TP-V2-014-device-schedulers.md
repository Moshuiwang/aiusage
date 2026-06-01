# TP-V2-014 Device Schedulers

Version: V2
ID: TP-V2-014
Status: ready
Type: documentation
Depends on: TP-V2-005
Parallel with: TP-V2-013

## Goal

记录 Mac、Linux、Windows 终端侧定时 pusher 的安装方式。

## Context

主动 push 架构需要每台设备自己定时运行 pusher。不同平台分别使用 launchd、systemd timer、Windows Task Scheduler。

## Scope

- 文档化三个平台的 dry-run 配置。
- 明确命令只在当前 OS 用户上下文运行。
- 明确 token 来自本机环境或本地忽略配置。

## Out of Scope

- 不写远程安装器。
- 不通过 SSH 分发任务。
- 不修改生产账户文件。

## Red Test

- 文档包含 launchd、systemd、Task Scheduler。
- 文档包含 dry-run。
- 文档不包含真实 token。

## Implementation

- 新增 scheduler 文档。
- 给出最小命令模板。
- 标注每个平台的日志位置和禁忌。

## Acceptance Criteria

- 用户能手动在每台设备配置定时 push。
- 每个 OS 用户只运行自己的 pusher。
- 不要求汇聚端 SSH 到设备。

## Verification

```bash
rg -n "launchd|systemd|Task Scheduler|dry-run|SSH" docs README.md
git diff --check
```

## Handoff

- 汇报文档路径。
- 汇报未实际安装 scheduler。
- 汇报平台差异。
