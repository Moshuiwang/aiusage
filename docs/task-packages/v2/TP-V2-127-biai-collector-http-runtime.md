# TP-V2-127 BIAI Collector HTTP Runtime

Version: V2
ID: TP-V2-127
Status: done
Type: implementation
Depends on: TP-V2-123, TP-V2-125
Parallel with: none

## Goal

让 BIAI 5 个采集器使用可追溯的产品 HTTP 身份，穿过 Cloudflare 入口防护并恢复真实 D1 上报。

## Context

2026-08-01 第一个 timer 修复试点中，调度已进入 waiting，但 service 退出 1 且 D1 未推进。BIAI 现场复现：默认 urllib 请求身份返回 403，`AIUsagePusher/1.0` 已穿过入口防护；远端 pusher hash 不属于当前 Git 历史，缺少可追溯发布证据。

## Scope

- 对比远端运行时代码与当前仓库的非敏感差异。
- 备份后只升级共享 HTTP identity 与 pusher 代码。
- 保持各用户配置、token、原始 usage 数据和依赖不变。
- 先单台试点，再逐台升级；每台均做 service + D1 写后读。
- 与 TP-V2-125 的 calendar timer 一起完成最终验收。

## Out of Scope

- 不读取或输出远程原始 Claude/Codex 日志。
- 不修改、打印或轮换 token。
- 不直接修改 D1。
- 不批量并发部署。

## Red Test

- 默认 urllib 身份被正式入口 403 拦截。
- 产品身份可穿过入口防护。
- 仓库测试必须固定用量与额度客户端共用产品 User-Agent。

## Implementation

1. 记录远端旧文件 hash 与回滚位置。
2. 部署仓库 `http_identity.py` 和 `pusher.py`。
3. 直接运行单台 service，要求 exit 0 且 D1 source report 推进。
4. 单台通过后逐台部署，每台失败即回滚并停止。
5. 最终核对 5 个运行时 hash 与仓库一致。

## Acceptance Criteria

- 5 个 service 最近一次真实运行均 exit 0。
- 5 个 D1 source report 时间均推进。
- 5 个 runtime 的两个文件 hash 与当前仓库一致。
- 旧代码和 timer 均有可用回滚备份。

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_pusher tests.test_limits_push -v
git diff --check
```

## Handoff

- 回报逐台 service、D1 写后读、文件 hash 和回滚位置；不回报凭据或原始日志。
