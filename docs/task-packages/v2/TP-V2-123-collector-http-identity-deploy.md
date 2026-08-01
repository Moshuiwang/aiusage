# TP-V2-123 Collector HTTP Identity Deploy

Version: V2
ID: TP-V2-123
Status: done
Type: implementation
Depends on: TP-V2-042, TP-V2-104
Parallel with: TP-V2-122

## Goal

让本机用量和额度采集器使用稳定的产品 HTTP 身份，避免 Cloudflare 把默认 Python 客户端误拦为 403/1010。

## Context

2026-08-01 现场复现：同一 token、同一只读健康请求，`Python-urllib/3.9` 返回 403，`AIUsagePusher/1.0` 返回 200。用量采集器已在仓库补过 User-Agent，但本机运行时未升级；额度采集器代码仍未设置 User-Agent。

## Scope

- 用量与额度 HTTP 客户端共用稳定产品 User-Agent。
- 为额度上传增加失败测试。
- 升级本机两套隔离运行时并触发一次真实上报。
- 写后从线上状态回读本机来源和额度新鲜度。

## Out of Scope

- 不轮换 token。
- 不修改或打印本机凭据。
- 不读取、同步或解析远程原始 usage 日志。
- 不改变额度计算口径。

## Red Test

- 额度上传请求必须携带产品 User-Agent，不能使用 urllib 默认值。
- 用量和额度客户端必须引用同一产品身份常量。

## Implementation

1. 提取共享 HTTP 身份常量。
2. 接入两条上传链路。
3. 更新本机隔离运行时，保持既有配置与 token 文件不变。
4. kickstart 后核对 LaunchAgent 退出码、成功日志和线上更新时间。

## Acceptance Criteria

- 默认 Python 身份仍被线上拦截时，产品身份请求可通过。
- 用量 LaunchAgent 最近退出码为 0；额度 LaunchAgent 仅在所有 provider 都有当前官方窗口时为 0，否则必须明确失败而不是假成功。
- 线上本机 usage/limits 更新时间重新推进。
- 后续代码回归测试能阻止 User-Agent 丢失。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_limits_push tests.test_pusher -v
git diff --check
```

## Handoff

- 回报 403/200 对照、本机运行时版本证据、LaunchAgent 结果和线上写后读；额度真实不可用时按 TP-V2-124 报告。
