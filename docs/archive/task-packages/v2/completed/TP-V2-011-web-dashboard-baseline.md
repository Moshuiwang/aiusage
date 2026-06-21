# TP-V2-011 Web Dashboard Baseline

Version: V2
ID: TP-V2-011
Status: done
Type: implementation
Depends on: TP-V2-010
Parallel with: none

## Goal

实现 Web dashboard 的 baseline 页面。

## Context

页面目标是给个人用户从浏览器查看所有终端的今日用量和采集健康状态。

## Scope

- 展示今日 total tokens。
- 展示按 machine、account、agent 的拆分。
- 展示 source health 和最近上报时间。
- 添加前端或 HTML 渲染测试。

## Out of Scope

- 不做营销 landing page。
- 不做多用户管理。
- 不做 limits 图。
- 不做复杂趋势图。

## Red Test

- 给定 summary API fixture，页面渲染 total tokens。
- 多 source fixture 渲染机器拆分。
- stale source 显示为非 ok 状态。

## Implementation

- 页面第一屏就是 dashboard。
- 控件和文案面向个人运维视角。
- 不在浏览器端计算复杂聚合。

## Acceptance Criteria

- 页面能查看所有终端 baseline usage。
- 失败和 stale 状态可见。
- 空态明确，不显示成 0 usage。

## Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- 汇报页面入口。
- 汇报测试方式。
- 如启动了本地 server，汇报 URL。
