# TP-V2-013 Server Operations

Version: V2
ID: TP-V2-013
Status: done
Type: documentation
Depends on: TP-V2-010
Parallel with: TP-V2-014

## Goal

记录个人 HTTP server 的运行、配置、备份和安全边界。

## Context

这个 server 只服务个人设备，但会接收 usage payload，因此需要清楚的本地配置、token、端口、备份和日志规则。

## Scope

- 文档化 server 启动命令。
- 文档化 token 配置方式。
- 文档化 SQLite 和 snapshot 路径。
- 文档化不要暴露 SSH、不要提交本地配置。

## Out of Scope

- 不写部署平台自动化。
- 不做公网安全审计。
- 不做多用户权限系统。

## Red Test

- 文档 grep 必须包含 server URL、token env、SQLite path、backup。
- 文档不能包含真实 token。

## Implementation

- 新增或更新 operations 文档。
- README 链接到该文档。
- 明确本机、内网、反代三种边界只作为部署说明，不做强绑定。

## Acceptance Criteria

- 用户能按文档启动个人 server。
- 用户知道哪些文件不能提交。
- 用户知道如何备份 SQLite。

## Verification

```bash
rg -n "server_url|token_env|SQLite|backup|SSH" README.md docs
git diff --check
```

## Handoff

- 汇报文档路径。
- 汇报没有写入真实 token。
- 汇报仍需用户自行选择部署位置。
