# TP-V2-102 macOS Period Cache Refresh

Version: V2
ID: TP-V2-102
Status: done
Type: implementation
Depends on: TP-V2-064
Parallel with: none

## Goal

让 macOS 菜单栏 popover 切换“今天 / 本周 / 本月 / 全部”时先显示本地缓存，再按需后台刷新，避免每次切 Tab 都阻塞等待线上请求。

## Context

当前 macOS 菜单栏只保存一份 `last-summary.json`，切换周期会立即请求 `/api/mobile/summary?period=...`。线上响应已优化，但用户体验仍不应依赖每次线上秒回。客户端应像仪表盘：先展示最近可用数据，后台更新。

## Scope

- 只修改 `clients/macos` 菜单栏客户端。
- 为 `today`、`week`、`month`、`all` 分别保存本地 summary cache。
- 切换到有缓存的周期时立即显示缓存。
- 缓存仍新鲜时不自动请求线上。
- 缓存过期时后台刷新，刷新中不清空当前页面。
- 手动刷新按钮仍强制请求线上。
- 刷新失败时保留当前缓存，并显示轻提示。

## Out of Scope

- 不改 `/api/mobile/summary` 接口。
- 不改 Cloudflare Worker、D1、VPN2 或服务端数据口径。
- 不改 iPhone、Watch、Web。
- 不新增跨端缓存规范。
- 不提交或输出 token、本地配置、原始 usage 日志。

## Red Test

- 新增 macOS ViewModel 测试：切换到新鲜缓存周期时立即显示缓存且不发起线上请求。
- 新增 macOS ViewModel 测试：切换到过期缓存周期时先显示缓存，再后台刷新成功后替换。
- 新增 macOS ViewModel 测试：后台刷新失败时继续显示缓存。

## Implementation

1. 在 `RuntimePaths` / `SummaryCache` 中增加按 period 的缓存路径和读写能力，保留旧 `last-summary.json` 兼容。
2. 扩展 `MenuBarAppModel`，维护按 period 的缓存和最近加载时间。
3. 区分自动刷新与手动刷新：自动刷新遵守缓存新鲜度，手动刷新强制请求。
4. 更新 `StatusBarController` 和 popover 切换逻辑，切 Tab 时不阻塞内容展示。

## Acceptance Criteria

- 已有缓存的 Tab 切换必须立即展示对应数据。
- 新鲜缓存命中时不自动请求线上。
- 过期缓存只触发后台刷新，不把 UI 变成空白加载态。
- 手动刷新仍能强制更新当前 Tab。
- 失败态不覆盖旧数据。

## Verification

```bash
swift test --package-path clients/macos
```

## Handoff

- 汇报改动文件。
- 汇报测试结果。
- 如安装本机菜单栏 App，汇报安装方式和用户可见验收结果。
