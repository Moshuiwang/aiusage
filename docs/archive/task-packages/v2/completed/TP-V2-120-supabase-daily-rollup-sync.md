# TP-V2-120 Supabase Daily Rollup Sync

Version: V2
ID: TP-V2-120
Status: in_progress
Type: implementation
Depends on: TP-V2-119
Parallel with: none

## Goal

每天将 AI Usage 已汇总的日用量副本写入 SOFA Base，避免该项目因无活动暂停，同时不改变 AI Usage 用户入口。

## Context

AI Usage 的正式用户入口和唯一数据源仍是 Cloudflare Worker + D1。现有 Native Worker 已有每日 scheduled handler；本任务只在这个后台任务中增加 D1 到 Supabase 的单向副本。

## Scope

- 只读取 D1 的 `usage_daily_rollups` 最近 90 天。
- 写入 Supabase 专用 `aiusage_daily_rollups` 和 `aiusage_sync_runs` 表。
- 使用 Cloudflare Worker Secret 保存 Supabase 服务端凭据。
- 同步错误不得影响 AI Usage Web、移动端或 ingest 路径。
- 新增单元测试和 Ops 交接材料。

## Out of Scope

- 不切换 `aiusage.chunbai.com`、不改 D1 为主库。
- 不同步原始日志、prompt、response 或用户会话内容。
- 不同步小时明细，不改现有采集或用户查询。
- 不在本任务中发布生产。

## Red Test

- 先证明同步会对日汇总使用可重复覆盖写入，并记录成功结果。
- 先证明 Supabase 拒绝写入时不会伪造成功记录。

## Implementation

1. 新增独立同步模块，读取 D1 日汇总并批量写入 Supabase REST API。
2. 在每日 scheduled handler 中以隔离的失败处理调用同步。
3. 为 Supabase 专用表提供可审计 schema。
4. 准备 Ops secret 配置、schema 执行和发布后验证交接。

## Acceptance Criteria

- AI Usage 继续以 D1 为唯一正式数据源，用户入口无变化。
- 每日同步覆盖最近 90 天日汇总，重复运行不产生重复行。
- 每次成功同步都在 SOFA Base 留下结果记录。
- SOFA Base 故障只记录后台同步失败，不影响 AI Usage 用户使用。
- 不将任何真实 key 写入源码、测试、文档或 Git。

## Verification

```bash
npm run cf:native:test -- cloudflare/native-worker/test/supabase-sync.test.ts
npm run cf:native:test
git diff --check
```

## Handoff

- 报告副本表范围、测试结果和未覆盖的风险。
- 交接 Ops 创建 schema、设置 Worker Secret、部署 Native Worker 和发布后验证。
