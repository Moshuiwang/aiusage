# Task Packages V2

Version: V2
Status: active

归档规则：`done` 任务包移入 `docs/archive/task-packages/v2/completed/`，当前目录只保留 `ready` / `in_progress` 任务包和索引。

## 方向

V2 替代 V1 的 SSH pull / Widget-first 路线。

新方向是个人 HTTP push 架构：

```text
Device pusher -> HTTP ingest server -> SQLite canonical store -> Web dashboard / mobile summary -> clients
```

macOS Widget 已退出后续产品路线；既有 TP-V2-015 只代表历史兼容 baseline，不再作为后续展示目标。后续客户端按 `clients/` 分层：`clients/ios` 承接 iPhone App / iOS Widget，`clients/android` 承接 Android App / Widget，`clients/macos` 承接菜单栏或轻量桌面入口，`clients/windows` 承接托盘或轻量桌面入口，`clients/web` 承接 Web dashboard 目标落点。

## 当前执行状态

已完成 ingest contract、终端 pusher、store/snapshot、Web dashboard、historical Widget optional snapshot、official limits provider MVP、production hardening baseline、scheduler templates、smoke handoff、config check、limits doctor readiness、索引状态对齐、Antigravity limits fixture parser baseline、limits HTTP push、limits push LaunchAgent installer 和跨端客户端目录边界。

当前移动端落地链路已新增任务包。TP-V2-043 mobile summary API contract、TP-V2-044 SwiftUI shell、TP-V2-045 iOS Widget summary、TP-V2-046 Xcode iOS App / Widget extension integration、TP-V2-047 physical iPhone signing / install、TP-V2-048 iOS App Icon asset、TP-V2-049 SwiftUI prototype surface、TP-V2-050 SwiftUI interactions / appearance、TP-V2-051 iOS live mobile summary client、TP-V2-052 mobile period live data correctness、TP-V2-053 production deploy、TP-V2-054 loading clear / number animation、TP-V2-055 today trend / drag tooltip、TP-V2-056 breakdown drilldown 均已完成。模拟器 App 的 today / week / month / all 切换会重新请求对应 live 数据，并同步高亮、标题、范围和数值；明细页点击机器后会按该机器来源重新聚合二级维度。后续 Android、macOS、Windows 也复用这个 mobile summary 合同，不在平台侧另算口径。

Codex hourly usage 方向已完成 TP-V2-060 和 TP-V2-061。TP-V2-060 新增 `MSWusage` Codex raw JSONL parser 和 CLI 合约，从本机 `~/.codex/sessions/**/*.jsonl` 的 `token_count.timestamp + last_token_usage` 生成更可信的 Codex 小时用量，并保证不输出原始日志路径或内容。TP-V2-061 已把该合约接入 device push / ingest / storage / snapshot，明确 Codex 小时换源为 `mswusage_codex_token_count`，不再回退到 `ccusage session.lastActivity`；Claude 小时仍优先使用去重后的 `ccusage blocks`。

移动端高保真改版 handoff 已归档到 `docs/archive/prototypes/ios-high-fidelity/HANDOFF.md`。TP-V2-062 已撤销：iOS 高保真实际由 TP-V2-073~080 完成，旧 handoff 路线不再执行，任务包归档到 `docs/archive/task-packages/v2/cancelled/`。

最新多端设计包已形成产品、架构、数据库和接口文档，并完成两轮 AI Review。Round 9 已对该链路做 backlog 对账：TP-V2-065、TP-V2-066、TP-V2-069、TP-V2-070 按现有代码和测试收口为 done；TP-V2-067 macOS 菜单栏高保真已撤销，当前菜单栏 UI 被接受；TP-V2-068 旧 iOS 高保真方向已撤销，由 TP-V2-073 到 TP-V2-080 的 iOS 体验线取代。后续只保留 TP-V2-071 跨端验收和 TP-V2-072 最终 review / PR / deploy。

下一步候选：

1. TP-V2-071 Multi Platform Data And Design Verification：用 API/DB/screenshot/Anti Gravity 验收 Web、iOS 073~080 线、iOS Widget、watchOS。
2. TP-V2-072 Final Review PR Deploy：最终 AI Review、提交、Push、PR 和必要部署。

## 任务列表

| ID | 文件 | 状态 | 依赖 | 可并行 |
| --- | --- | --- | --- | --- |
| TP-V2-001 | [TP-V2-001-http-ingest-contract.md](../../archive/task-packages/v2/completed/TP-V2-001-http-ingest-contract.md) | done | none | TP-V2-004 |
| TP-V2-002 | [TP-V2-002-ingest-auth-and-errors.md](../../archive/task-packages/v2/completed/TP-V2-002-ingest-auth-and-errors.md) | done | TP-V2-001 | none |
| TP-V2-003 | [TP-V2-003-ingest-idempotent-upsert.md](../../archive/task-packages/v2/completed/TP-V2-003-ingest-idempotent-upsert.md) | done | TP-V2-001 | TP-V2-006 |
| TP-V2-004 | [TP-V2-004-device-config-contract.md](../../archive/task-packages/v2/completed/TP-V2-004-device-config-contract.md) | done | none | TP-V2-001 |
| TP-V2-005 | [TP-V2-005-device-pusher-fake-http.md](../../archive/task-packages/v2/completed/TP-V2-005-device-pusher-fake-http.md) | done | TP-V2-004 | none |
| TP-V2-006 | [TP-V2-006-device-normalized-payload.md](../../archive/task-packages/v2/completed/TP-V2-006-device-normalized-payload.md) | done | TP-V2-001, TP-V2-005 | TP-V2-003 |
| TP-V2-007 | [TP-V2-007-server-sqlite-schema.md](../../archive/task-packages/v2/completed/TP-V2-007-server-sqlite-schema.md) | done | TP-V2-003 | none |
| TP-V2-008 | [TP-V2-008-server-snapshot-builder.md](../../archive/task-packages/v2/completed/TP-V2-008-server-snapshot-builder.md) | done | TP-V2-007 | none |
| TP-V2-009 | [TP-V2-009-source-staleness-health.md](../../archive/task-packages/v2/completed/TP-V2-009-source-staleness-health.md) | done | TP-V2-007 | TP-V2-008 |
| TP-V2-010 | [TP-V2-010-web-api-summary.md](../../archive/task-packages/v2/completed/TP-V2-010-web-api-summary.md) | done | TP-V2-008, TP-V2-009 | none |
| TP-V2-011 | [TP-V2-011-web-dashboard-baseline.md](../../archive/task-packages/v2/completed/TP-V2-011-web-dashboard-baseline.md) | done | TP-V2-010 | none |
| TP-V2-012 | [TP-V2-012-web-dashboard-failure-states.md](../../archive/task-packages/v2/completed/TP-V2-012-web-dashboard-failure-states.md) | done | TP-V2-011 | none |
| TP-V2-013 | [TP-V2-013-server-operations.md](../../archive/task-packages/v2/completed/TP-V2-013-server-operations.md) | done | TP-V2-010 | TP-V2-014 |
| TP-V2-014 | [TP-V2-014-device-schedulers.md](../../archive/task-packages/v2/completed/TP-V2-014-device-schedulers.md) | done | TP-V2-005 | TP-V2-013 |
| TP-V2-015 | [TP-V2-015-widget-optional-snapshot.md](../../archive/task-packages/v2/completed/TP-V2-015-widget-optional-snapshot.md) | done | TP-V2-008 | none |
| TP-V2-016 | [TP-V2-016-official-limits-contract.md](../../archive/task-packages/v2/completed/TP-V2-016-official-limits-contract.md) | done | TP-V2-010 | none |
| TP-V2-017 | [TP-V2-017-codex-official-provider.md](../../archive/task-packages/v2/completed/TP-V2-017-codex-official-provider.md) | done | TP-V2-016 | none |
| TP-V2-018 | [TP-V2-018-claude-official-provider.md](../../archive/task-packages/v2/completed/TP-V2-018-claude-official-provider.md) | done | TP-V2-016 | none |
| TP-V2-019 | [TP-V2-019-limit-windows-store.md](../../archive/task-packages/v2/completed/TP-V2-019-limit-windows-store.md) | done | TP-V2-016 | none |
| TP-V2-020 | [TP-V2-020-limits-snapshot-api.md](../../archive/task-packages/v2/completed/TP-V2-020-limits-snapshot-api.md) | done | TP-V2-017, TP-V2-018, TP-V2-019 | none |
| TP-V2-021 | [TP-V2-021-limits-presentation.md](../../archive/task-packages/v2/completed/TP-V2-021-limits-presentation.md) | done | TP-V2-020 | none |
| TP-V2-022 | [TP-V2-022-production-hardening-baseline.md](../../archive/task-packages/v2/completed/TP-V2-022-production-hardening-baseline.md) | done | TP-V2-013, TP-V2-014 | none |
| TP-V2-023 | [TP-V2-023-health-and-bounded-backups.md](../../archive/task-packages/v2/completed/TP-V2-023-health-and-bounded-backups.md) | done | TP-V2-022 | none |
| TP-V2-024 | [TP-V2-024-official-limits-runtime-wiring.md](../../archive/task-packages/v2/completed/TP-V2-024-official-limits-runtime-wiring.md) | done | TP-V2-021 | none |
| TP-V2-025 | [TP-V2-025-codex-wham-auth-adapter.md](../../archive/task-packages/v2/completed/TP-V2-025-codex-wham-auth-adapter.md) | done | TP-V2-024 | none |
| TP-V2-026 | [TP-V2-026-claude-oauth-auth-adapter.md](../../archive/task-packages/v2/completed/TP-V2-026-claude-oauth-auth-adapter.md) | done | TP-V2-024 | none |
| TP-V2-027 | [TP-V2-027-codex-app-server-rpc-adapter.md](../../archive/task-packages/v2/completed/TP-V2-027-codex-app-server-rpc-adapter.md) | done | TP-V2-024 | none |
| TP-V2-028 | [TP-V2-028-claude-cli-usage-adapter.md](../../archive/task-packages/v2/completed/TP-V2-028-claude-cli-usage-adapter.md) | done | TP-V2-024 | none |
| TP-V2-029 | [TP-V2-029-limits-config-contract.md](../../archive/task-packages/v2/completed/TP-V2-029-limits-config-contract.md) | done | TP-V2-024 | none |
| TP-V2-030 | [TP-V2-030-limits-dry-run.md](../../archive/task-packages/v2/completed/TP-V2-030-limits-dry-run.md) | done | TP-V2-029 | none |
| TP-V2-031 | [TP-V2-031-limits-scheduler-templates.md](../../archive/task-packages/v2/completed/TP-V2-031-limits-scheduler-templates.md) | done | TP-V2-030 | none |
| TP-V2-032 | [TP-V2-032-limits-smoke-handoff.md](../../archive/task-packages/v2/completed/TP-V2-032-limits-smoke-handoff.md) | done | TP-V2-031 | none |
| TP-V2-033 | [TP-V2-033-limits-config-check.md](../../archive/task-packages/v2/completed/TP-V2-033-limits-config-check.md) | done | TP-V2-029 | none |
| TP-V2-034 | [TP-V2-034-v2-index-status-reconcile.md](../../archive/task-packages/v2/completed/TP-V2-034-v2-index-status-reconcile.md) | done | none | none |
| TP-V2-035 | [TP-V2-035-v2-backlog-entry-cleanup.md](../../archive/task-packages/v2/completed/TP-V2-035-v2-backlog-entry-cleanup.md) | done | TP-V2-034 | none |
| TP-V2-036 | [TP-V2-036-antigravity-limits-fixture-parser.md](../../archive/task-packages/v2/completed/TP-V2-036-antigravity-limits-fixture-parser.md) | done | TP-V2-016 | none |
| TP-V2-037 | [TP-V2-037-limits-doctor-readiness.md](../../archive/task-packages/v2/completed/TP-V2-037-limits-doctor-readiness.md) | done | TP-V2-033 | none |
| TP-V2-039 | [TP-V2-039-limits-multi-account-cli.md](../../archive/task-packages/v2/completed/TP-V2-039-limits-multi-account-cli.md) | done | TP-V2-029, TP-V2-030, TP-V2-037 | none |
| TP-V2-040 | [TP-V2-040-claude-cli-limit-message-parser.md](../../archive/task-packages/v2/completed/TP-V2-040-claude-cli-limit-message-parser.md) | done | TP-V2-039 | none |
| TP-V2-041 | [TP-V2-041-limits-http-push.md](../../archive/task-packages/v2/completed/TP-V2-041-limits-http-push.md) | done | TP-V2-039, TP-V2-040 | Mobile app prototype work |
| TP-V2-042 | [TP-V2-042-limits-push-launchd-installer.md](../../archive/task-packages/v2/completed/TP-V2-042-limits-push-launchd-installer.md) | done | TP-V2-041 | Mobile app prototype work |
| TP-V2-043 | [TP-V2-043-mobile-summary-api-contract.md](../../archive/task-packages/v2/completed/TP-V2-043-mobile-summary-api-contract.md) | done | TP-V2-010, TP-V2-020, mobile app prototype approval | none |
| TP-V2-044 | [TP-V2-044-ios-swiftui-shell.md](../../archive/task-packages/v2/completed/TP-V2-044-ios-swiftui-shell.md) | done | TP-V2-043 | none |
| TP-V2-045 | [TP-V2-045-ios-widget-summary.md](../../archive/task-packages/v2/completed/TP-V2-045-ios-widget-summary.md) | done | TP-V2-044 | none |
| TP-V2-046 | [TP-V2-046-ios-xcode-app-extension-integration.md](../../archive/task-packages/v2/completed/TP-V2-046-ios-xcode-app-extension-integration.md) | done | TP-V2-044, TP-V2-045 | none |
| TP-V2-047 | [TP-V2-047-ios-signing-device-install.md](../../archive/task-packages/v2/completed/TP-V2-047-ios-signing-device-install.md) | done | TP-V2-046 | none |
| TP-V2-048 | [TP-V2-048-ios-app-icon-asset.md](../../archive/task-packages/v2/completed/TP-V2-048-ios-app-icon-asset.md) | done | TP-V2-046 | none |
| TP-V2-049 | [TP-V2-049-ios-swiftui-prototype-surface.md](../../archive/task-packages/v2/completed/TP-V2-049-ios-swiftui-prototype-surface.md) | done | TP-V2-044, TP-V2-046 | none |
| TP-V2-050 | [TP-V2-050-ios-swiftui-interactions-and-appearance.md](../../archive/task-packages/v2/completed/TP-V2-050-ios-swiftui-interactions-and-appearance.md) | done | TP-V2-049 | none |
| TP-V2-051 | [TP-V2-051-ios-live-mobile-summary-client.md](../../archive/task-packages/v2/completed/TP-V2-051-ios-live-mobile-summary-client.md) | done | TP-V2-043, TP-V2-050 | none |
| TP-V2-052 | [TP-V2-052-mobile-period-live-data-correctness.md](../../archive/task-packages/v2/completed/TP-V2-052-mobile-period-live-data-correctness.md) | done | TP-V2-043, TP-V2-051 | none |
| TP-V2-053 | [TP-V2-053-production-mobile-summary-deploy.md](../../archive/task-packages/v2/completed/TP-V2-053-production-mobile-summary-deploy.md) | done | TP-V2-043, TP-V2-052 | none |
| TP-V2-054 | [TP-V2-054-ios-period-loading-clear-and-number-animation.md](../../archive/task-packages/v2/completed/TP-V2-054-ios-period-loading-clear-and-number-animation.md) | done | TP-V2-052, TP-V2-053 | none |
| TP-V2-055 | [TP-V2-055-today-trend-axis-and-ios-drag-tooltip.md](../../archive/task-packages/v2/completed/TP-V2-055-today-trend-axis-and-ios-drag-tooltip.md) | done | TP-V2-054 | none |
| TP-V2-056 | [TP-V2-056-ios-breakdown-drilldown.md](../../archive/task-packages/v2/completed/TP-V2-056-ios-breakdown-drilldown.md) | done | TP-V2-055 | none |
| TP-V2-057 | [TP-V2-057-ios-trend-chart-dot-polish.md](../../archive/task-packages/v2/completed/TP-V2-057-ios-trend-chart-dot-polish.md) | done | TP-V2-055 | none |
| TP-V2-058 | [TP-V2-058-ios-trend-tooltip-overlay.md](../../archive/task-packages/v2/completed/TP-V2-058-ios-trend-tooltip-overlay.md) | done | TP-V2-055, TP-V2-057 | none |
| TP-V2-059 | [TP-V2-059-ios-production-server-fail-closed.md](../../archive/task-packages/v2/completed/TP-V2-059-ios-production-server-fail-closed.md) | done | TP-V2-051, TP-V2-053 | none |
| TP-V2-060 | [TP-V2-060-mswusage-codex-hourly.md](../../archive/task-packages/v2/completed/TP-V2-060-mswusage-codex-hourly.md) | done | none | mobile UI polish |
| TP-V2-061 | [TP-V2-061-mswusage-codex-hourly-integration.md](../../archive/task-packages/v2/completed/TP-V2-061-mswusage-codex-hourly-integration.md) | done | TP-V2-060 | mobile UI polish |
| TP-V2-062 | [TP-V2-062-ios-high-fidelity-app-redesign.md](../../archive/task-packages/v2/cancelled/TP-V2-062-ios-high-fidelity-app-redesign.md) | cancelled | — | superseded by TP-V2-073~080 |
| TP-V2-063 | [TP-V2-063-cross-platform-client-directory-boundary.md](../../archive/task-packages/v2/completed/TP-V2-063-cross-platform-client-directory-boundary.md) | done | none | docs / architecture |
| TP-V2-064 | [TP-V2-064-macos-menu-bar-client.md](../../archive/task-packages/v2/completed/TP-V2-064-macos-menu-bar-client.md) | done | TP-V2-043 | TP-V2-060, TP-V2-061 |
| TP-V2-065 | [TP-V2-065-multi-platform-design-assets.md](../../archive/task-packages/v2/completed/TP-V2-065-multi-platform-design-assets.md) | done | multi-platform design docs AI review | TP-V2-066 |
| TP-V2-066 | [TP-V2-066-web-dashboard-high-fidelity.md](../../archive/task-packages/v2/completed/TP-V2-066-web-dashboard-high-fidelity.md) | done | TP-V2-065 | TP-V2-069 |
| TP-V2-067 | [TP-V2-067-macos-menu-bar-high-fidelity.md](../../archive/task-packages/v2/cancelled/TP-V2-067-macos-menu-bar-high-fidelity.md) | cancelled | — | accepted current menu bar UI |
| TP-V2-068 | [TP-V2-068-ios-app-high-fidelity-and-icon.md](../../archive/task-packages/v2/cancelled/TP-V2-068-ios-app-high-fidelity-and-icon.md) | cancelled | — | superseded by TP-V2-073~080 |
| TP-V2-069 | [TP-V2-069-ios-widget-high-fidelity.md](../../archive/task-packages/v2/completed/TP-V2-069-ios-widget-high-fidelity.md) | done | TP-V2-045, TP-V2-046, TP-V2-065 | TP-V2-066 |
| TP-V2-070 | [TP-V2-070-watchos-summary-app.md](../../archive/task-packages/v2/completed/TP-V2-070-watchos-summary-app.md) | done | TP-V2-065 | TP-V2-066, TP-V2-069 |
| TP-V2-071 | [TP-V2-071-multi-platform-data-design-verification.md](TP-V2-071-multi-platform-data-design-verification.md) | ready | TP-V2-066, TP-V2-069, TP-V2-070, TP-V2-073, TP-V2-074, TP-V2-075, TP-V2-076, TP-V2-077, TP-V2-078, TP-V2-079, TP-V2-080 | none |
| TP-V2-072 | [TP-V2-072-final-review-pr-deploy.md](TP-V2-072-final-review-pr-deploy.md) | ready | TP-V2-071 | none |
| TP-V2-073 | [TP-V2-073-ios-app-icon-opaque-exit-animation.md](../../archive/task-packages/v2/completed/TP-V2-073-ios-app-icon-opaque-exit-animation.md) | done | TP-V2-048, TP-V2-065 | none |
| TP-V2-074 | [TP-V2-074-ios-navigation-liquid-glass-icons.md](../../archive/task-packages/v2/completed/TP-V2-074-ios-navigation-liquid-glass-icons.md) | done | none | TP-V2-073 |
| TP-V2-075 | [TP-V2-075-ios-claude-5h-quota-period-consistency.md](../../archive/task-packages/v2/completed/TP-V2-075-ios-claude-5h-quota-period-consistency.md) | done | TP-V2-043, TP-V2-052 | TP-V2-073, TP-V2-074 |
| TP-V2-076 | [TP-V2-076-ios-quota-card-account-label.md](../../archive/task-packages/v2/completed/TP-V2-076-ios-quota-card-account-label.md) | done | TP-V2-043 | none |
| TP-V2-077 | [TP-V2-077-ios-quota-5h-zero-state-layout.md](../../archive/task-packages/v2/completed/TP-V2-077-ios-quota-5h-zero-state-layout.md) | done | TP-V2-075 | none |
| TP-V2-078 | [TP-V2-078-ios-sources-current-period-and-updated-date.md](../../archive/task-packages/v2/completed/TP-V2-078-ios-sources-current-period-and-updated-date.md) | done | TP-V2-043, TP-V2-052 | TP-V2-076, TP-V2-077 |
| TP-V2-079 | [TP-V2-079-ios-source-row-layout-usage-and-update-time.md](../../archive/task-packages/v2/completed/TP-V2-079-ios-source-row-layout-usage-and-update-time.md) | done | TP-V2-078 | none |
| TP-V2-080 | [TP-V2-080-ios-native-liquid-glass-tab-bar.md](../../archive/task-packages/v2/completed/TP-V2-080-ios-native-liquid-glass-tab-bar.md) | done | TP-V2-074 | TP-V2-079 |
| TP-V2-081 | [TP-V2-081-directory-doc-governance.md](TP-V2-081-directory-doc-governance.md) | in_progress | architecture governance approval | none |
| TP-V2-082 | [TP-V2-082-test-baseline-backlog-reconcile.md](../../archive/task-packages/v2/completed/TP-V2-082-test-baseline-backlog-reconcile.md) | done | Round 9 approval | none |
| TP-V2-083 | [TP-V2-083-cloudflare-entrypoint-migration.md](TP-V2-083-cloudflare-entrypoint-migration.md) | in_progress | Cloudflare resources created | none |
| TP-V2-084 | [TP-V2-084-watch-companion-testflight.md](TP-V2-084-watch-companion-testflight.md) | draft | TP-V2-070, PRD/architecture approval | none |
| TP-V2-085 | [TP-V2-085-watch-refresh-best-practice.md](TP-V2-085-watch-refresh-best-practice.md) | in_progress | TP-V2-084 | none |

## subagent 分配建议

- Server agent：历史范围 TP-V2-001 到 TP-V2-003、TP-V2-007 到 TP-V2-010、TP-V2-013 已完成。
- Device pusher agent：历史范围 TP-V2-004 到 TP-V2-006、TP-V2-014 已完成。
- Web UI agent：历史范围 TP-V2-010 到 TP-V2-012 已完成；后续 Web 目标落点是 `clients/web`，现有生产资源暂留 `src/ai_usage_widget/static`。
- Widget agent：历史范围 TP-V2-015 已完成；后续不要继续推进 macOS Widget，移动端展示改由 Mobile App / iOS Widget agent 承接。
- Limits provider agent：历史范围 TP-V2-016 到 TP-V2-033 已完成。
- Limits provider agent：TP-V2-039 已完成 multi-account CLI runtime。
- Limits provider agent：TP-V2-040 已完成 Claude CLI limit message parser。
- Limits provider agent：TP-V2-041 已完成本机官方额度到生产的 HTTP push 链路。
- Limits provider agent：TP-V2-042 已完成本机 limits push 的 macOS LaunchAgent installer。
- Antigravity provider agent：TP-V2-036 已完成离线 fixture parser；真实 Language Server reader 另开任务。
- Mobile App agent：先执行 TP-V2-043，固定移动端只读 API contract；之后执行 TP-V2-044 SwiftUI shell。后续 Android 也复用该 contract。
- iOS Widget agent：TP-V2-045 已完成可复用摘要模型和小/中号内容视图；下一步另开 Xcode extension 集成任务，不复用 legacy macOS Widget 作为新产品 UI。
- iOS Xcode agent：TP-V2-046 已把 Swift Package 接入 iPhone App 和 WidgetKit extension target；TP-V2-047 已完成签名和物理 iPhone 安装；TP-V2-048 已接入真实 AppIcon asset；TP-V2-049 已把 SwiftUI 内部页面改成原型结构，未按本轮安装到手机。
- Docs / QA agent：检查 V2 链接、验收记录和文档一致性，不改实现。
- Usage data agent：TP-V2-060 / TP-V2-061 已完成，Codex 小时换源接入 push / ingest / storage / snapshot。全程保持 `ccusage daily` baseline、Claude blocks 和生产凭据边界不变。
- Cross-platform client agent：后续新增 Android、macOS、Windows 时，先从 `docs/project-map.md` 的客户端目录边界和 `clients/<platform>/README.md` 开任务包；不得复用 legacy macOS Widget 作为新产品 UI。
- macOS Client agent：TP-V2-064 新增菜单栏轻入口，只读 `/api/mobile/summary`，不执行采集，不读取 SQLite，不复用 legacy macOS Widget。
- Design Assets agent：TP-V2-065 已完成，统一 App Icon 和跨端品牌图形。
- Web UI agent：TP-V2-066 已完成，Web Dashboard 保持 `/api/summary` 数据准确。
- macOS Client agent：TP-V2-067 已撤销；当前菜单栏 UI 被接受，不再追旧高保真 popover。
- Mobile App agent：TP-V2-068 已撤销；旧 iOS 高保真方向由 TP-V2-073 到 TP-V2-080 取代。
- iOS Widget agent：TP-V2-069 已完成 Small / Medium / Large Widget。
- Watch agent：TP-V2-070 已完成 watchOS 只读摘要 App；真机验收作为 manual 跟进，不阻塞 done。
- QA / Anti Gravity agent：执行 TP-V2-071，使用 `agy --model gemini-3.5-flash` 验收 Web、iOS 073~080 线、iOS Widget、watchOS。
- Release agent：执行 TP-V2-072，做最终 AI Review、提交、PR 和必要部署。
- Mobile App agent：执行 TP-V2-073，修正 iOS AppIcon 透明角和预圆角问题，并以物理 iPhone 上滑退出动画不露底作为最终验收。
- Mobile App agent：执行 TP-V2-074，修正 iOS 底部导航图标的液态玻璃质感，以真机视觉为最终验收。
- Mobile App / Server agent：执行 TP-V2-075，修正 Claude 5h 额度在 Today / Week / Month / All 之间不一致和疑似 stale 96% 外圈问题。
- Mobile App / Server agent：执行 TP-V2-076，在 iOS 已用额度卡片中展示安全的 Claude / Codex 账号标签。
- Mobile App agent：执行 TP-V2-077，修正 Claude 5h 为 0% 或已重置时行信息消失导致卡片高度不一致的问题。
- Mobile App / Server agent：执行 TP-V2-078，修正 iOS Today 来源区展示 0 用量旧来源和更新时间缺日期上下文的问题。
- Mobile App agent：执行 TP-V2-079，修正 iOS 来源行布局为第一行用户名+用量、第二行机器名+更新时间，并防止长文本遮挡右侧字段。
- Mobile App agent：执行 TP-V2-080，把 iOS 底部周期切换从自定义毛玻璃胶囊升级为苹果推荐的原生 Liquid Glass Tab Bar / TabView 体验；如果当前 SDK 不支持，必须明确报告 fallback。
- Docs / QA agent：执行 TP-V2-081，做目录与文档治理，只收敛入口、索引、归档和文档漂移检查，不改产品代码、API、SQLite schema 或客户端物理目录。
- Docs / QA agent：TP-V2-082 已完成测试基线和 backlog 对账，删除废弃方向测试，保留真实 backlog。
- Watch agent：执行 TP-V2-085，按 Apple 推荐路径实现 iPhone 后台刷新、WatchConnectivity、Watch App Group cache 和 WidgetKit complication 刷新闭环，最终以 iPhone 和 Apple Watch 安装后数据正常为验收目标。
