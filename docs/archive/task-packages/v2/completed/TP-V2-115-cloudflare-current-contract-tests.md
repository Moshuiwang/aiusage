# TP-V2-115 Cloudflare Current Contract Tests

Version: V2
ID: TP-V2-115
Status: done
Type: implementation
Depends on: none
Parallel with: TP-V2-114

## Goal

让 Cloudflare 部署合同测试与当前 Native Worker + D1 架构一致，不再要求已下线的 VPN2 回源。

## Context

当前 `wrangler.toml` 和 Cloudflare README 已指向 Native/D1 路线，但
`tests/test_cloudflare_deployment.py` 仍断言 VPN2 origin 和旧“统一入口回源”文案，导致全量
Python 基线稳定失败 2 项。

## Scope

- 先用失败断言固定当前 Native/D1 入口，不允许活动配置回退到 VPN2。
- 更新 Cloudflare 部署测试，使其验证当前 `wrangler.toml`、README 和架构事实。
- 同步仍把 VPN2 写成当前生产入口的顶层代理说明，避免后续 agent 误操作。
- 保留历史任务包中的历史描述，不改写已完成事实。

## Out of Scope

- 不部署或修改 Cloudflare 账号资源。
- 不删除历史回滚文档或 VPN2 备份说明。
- 不访问生产 API、D1、凭据或远程主机。
- 不改变 Worker 运行时业务逻辑。

## Red Test

先把合同断言改为当前 Native/D1 入口，并断言活动配置与顶层说明不把 VPN2 当作当前生产源；
当前陈旧说明或测试应使其失败。

## Implementation

1. 以 `docs/architecture/cloudflare-migration-remaining-work.md` 的当前事实为准更新测试。
2. 同步活动入口说明，不改历史记录。
3. 运行定向与全量 Python 测试，确认没有用放宽断言掩盖真实配置漂移。

## Acceptance Criteria

- Cloudflare 合同测试不再要求 `vpn2.chunbai.com:8443` 为活动 origin。
- 活动配置和顶层说明明确 Native Worker + D1 是当前生产链路。
- 历史迁移与回滚信息仍保留为历史或应急说明。
- 全量 Python 测试不再出现这 2 项陈旧断言失败。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_cloudflare_deployment -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
```

## Handoff

- 汇报更新后的当前入口合同及保留的历史信息。
- 证据写回 Parent Epic #32 的单一证据评论和对应 Fix Issue。
