# TP-V2-063 Cross-Platform Client Directory Boundary

Status: done

## Goal

把前端客户端从历史 `mobile` / `widget` 表述收敛为清晰的跨端目标目录：

- `clients/ios`
- `clients/android`
- `clients/macos`
- `clients/windows`
- `clients/web`
- `packages/client-contracts`
- `packages/design-tokens`

同时更新架构文档，明确 Web 是完整 dashboard，iOS / Android 是移动查看，macOS / Windows 是轻量入口。

## Context

当前 iPhone App 已经落地，但用户后续希望增加 macOS、Windows 和 Android。直接把每个平台做成独立产品会导致 usage、limits、source health 口径分裂。

本任务只做目录和文档边界，不移动现有 SwiftPM、Xcode 或 Web 静态资源。

## Scope

- 新增 `clients/` 和 `packages/` 目标目录说明。
- 新增 `docs/architecture/client-platforms.md`。
- 更新 README、产品 brief、架构文档、状态文档和 V2 索引。
- 明确现有 `mobile/ios`、`mobile/ios-xcode`、`src/ai_usage_widget/static` 处于迁移期保留状态。

## Out of Scope

- 不开发 Android App。
- 不开发 macOS 菜单栏。
- 不开发 Windows 托盘。
- 不移动现有 iOS 或 Web 文件。
- 不改变任何 API、SQLite schema 或生产配置。

## Red Test

文档任务不新增代码红测。验收以目录存在、文档引用一致、旧路线表述收敛为准。

## Implementation

- 新增跨端客户端目标目录。
- 新增共享合同和设计 token 目标目录。
- 把客户端方向从“只写 iPhone App + iOS Widget”扩展为 `clients/` 分层。
- 保留 legacy macOS Widget 历史兼容身份。

## Acceptance Criteria

- 后续 agent 能从 `clients/README.md` 判断各平台落点。
- 后续 Android、macOS、Windows 任务不会复用 legacy macOS Widget 路线。
- 后续客户端字段不足时，会先扩展 server read model 或 mobile summary DTO，而不是在平台侧另算。

## Verification

- `rg` 检查主要架构入口中的旧客户端路线表述。
- `git diff --check`。

## Handoff

下一步如果要真正开发某个平台：

- Android：新建任务包，目标落点 `clients/android`，先消费 `/api/mobile/summary`。
- macOS：新建任务包，目标落点 `clients/macos`，优先菜单栏轻入口。
- Windows：新建任务包，目标落点 `clients/windows`，优先托盘轻入口。
- Web 迁移：新建任务包，目标落点 `clients/web`，必须保护登录、静态资源路由和 `/api/summary`。
