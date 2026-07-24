# TP-V2-116 Summary Read Cache

Version: V2
ID: TP-V2-116
Status: done
Type: implementation
Depends on: TP-V2-088, TP-V2-093
Parallel with: none

## Goal

让同一位已登录用户在一分钟内重复打开看板或移动摘要时复用安全的读取结果，减少 D1 重复读取，同时保持数据含义不变。

## Context

GitHub Issue #43。当前公开入口代理到 Native Worker；缓存仅在 Native Worker 的成功读取响应中生效。

## Scope

- 仅缓存 `GET /api/summary` 与 `GET /api/mobile/summary` 的 200 JSON 响应。
- 缓存键包含完整查询条件和认证会话的不可逆摘要。
- 缓存有效期 60 秒，响应明确标注私有、短时缓存语义。
- 未登录、失败、写入与其他路径绝不缓存。

## Out of Scope

- 不新增 KV、D1、DNS、Route、Worker 入口或 D1 schema。
- 不改变任一接口字段、来源状态、权限或鉴权逻辑。
- 不部署生产或修改生产账户文件。

## Red Test

- 先证明同一认证会话的相同摘要请求在 60 秒内只构建一次。
- 先证明不同认证会话、不同查询条件和未认证请求不共享缓存。
- 先证明失败响应不进入缓存。

## Implementation

1. 在认证成功后为两个摘要读取路径生成不含明文 token 的私有缓存键。
2. 命中时返回已有成功 JSON；未命中时构建、写入短时缓存并返回。
3. 保持鉴权失败和所有异常响应不缓存。

## Acceptance Criteria

- 看板和移动摘要仍显示非空、正确的来源状态。
- 不同用户或不同筛选条件绝不共享数据。
- 新写入的数据最多约 60 秒后可见。
- 后续生产观察可用 D1 Query Insights 对比读取量。

## Verification

```bash
npm run cf:native:test -- --run
```

## Handoff

- 回报改动、测试结果、未部署说明和生产观察所需的 D1 Query Insights 对比。
