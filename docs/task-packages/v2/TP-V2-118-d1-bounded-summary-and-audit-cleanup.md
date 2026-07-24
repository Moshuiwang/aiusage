# TP-V2-118 D1 Bounded Summary And Audit Cleanup

Version: V2
ID: TP-V2-118
Status: done
Type: implementation
Depends on: TP-V2-116
Parallel with: none

## Goal

在数据真实、完整、可追溯的前提下，消除摘要读取和审计清理的无效全历史扫描，保护用户持续查看网页和 iPhone App 的能力。

## Context

GitHub Issue #46。正式 Native Worker 的摘要缓存未命中时会读取完整的小时事实历史后再筛选；审计清理对时间字段套函数，无法稳定利用索引。

## Scope

- 仅改 Native Worker 的摘要小时事实查询和审计表清理。
- 在 SQL 中限定当前展示周期的时间边界，并保留现有时区和筛选结果。
- 增加审计表必要索引，清理改为可利用索引、可恢复的有界操作。
- 用 D1/Worker 测试固定相同输入下的展示结果与读取范围。

## Out of Scope

- 不改变接口字段、页面、App、Widget、登录态、采集载荷或额度逻辑。
- 不引入预汇总表；该体验由 TP-V2-119 处理。
- 不部署、迁移远程 D1 或修改生产资源。

## Red Test

- 先证明周期摘要查询必须含时间范围，且结果与既有聚合一致。
- 先证明审计清理的查询不再对 `collected_at` 使用日期函数，并按边界删除对应记录。

## Implementation

1. 用测试覆盖跨时区日期边界、长历史和既有筛选结果。
2. 在数据库查询层应用精确的小时范围，保留应用层日期判断作为兼容保护。
3. 新增最小索引与迁移，按原始时间值执行审计清理。
4. 跑 Native Worker 全量测试与 TypeScript 检查。

## Acceptance Criteria

- 用户在网页或 iPhone App 看到的今天、本周、本月、全部和筛选结果不变。
- 缓存未命中时只读取当前展示期所需的小时事实。
- 审计清理不再产生“删除少量记录却读取千万级行”的模式。
- 新上报数据仍按既有短延迟可见。

## Verification

```bash
npm run cf:native:test -- --run
npx tsc --noEmit
```

## Handoff

- 回报测试、迁移和本地 D1 验证结果。
- 生产发布前由 Ops 使用 D1 15 分钟指标和实际用户入口复核。
