# Task Packages V2

Version: V2
Status: active

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

Codex hourly usage 方向已拆成 TP-V2-060 和 TP-V2-061。TP-V2-060 只新增 `MSWusage` Codex raw JSONL parser 和 CLI 合约，从本机 `~/.codex/sessions/**/*.jsonl` 的 `token_count.timestamp + last_token_usage` 生成更可信的 Codex 小时用量，并保证不输出原始日志路径或内容。TP-V2-061 再把该合约接入 device push / ingest / storage / snapshot，明确 Codex 小时换源为 `mswusage_codex_token_count`，不再回退到 `ccusage session.lastActivity`；Claude 小时仍优先使用去重后的 `ccusage blocks`。

移动端高保真改版 handoff 已形成：`docs/prototypes/ios-high-fidelity/HANDOFF.md` 是设计到 SwiftUI 的开发交接入口，TP-V2-062 是可执行实现任务包。

下一步候选：

1. TP-V2-060 MSWusage Codex parser contract：先固定本机 parser / CLI / fixture 合约，保证小时桶、cache 口径和无敏感路径输出。
2. TP-V2-061 MSWusage Codex hourly integration：TP-V2-060 完成后再做 push / ingest / storage / snapshot 集成，让 Codex 小时换源为 `mswusage_codex_token_count`。
3. TP-V2-062 iOS high fidelity app redesign：按高保真 handoff 把 SwiftUI App 对齐到当前 App 版玻璃界面。
4. 跨端客户端任务包：分别为 `clients/android`、`clients/macos`、`clients/windows` 新建任务包；macOS / Windows 先做轻量入口，Android 复用移动端摘要合同。
5. 移动端生产配置 UX：把 simulator env 配置演进成 App 内只读 server/token 设置、Keychain 保存和连接状态提示。
6. 真实命令 smoke：先跑 `collect-limits --doctor`，再只在本机 `config/limits.local.json` 明确存在时执行，不提交凭据或真实输出。
7. Antigravity real LS reader：围绕本地 Language Server 调用能力单独开任务包。
8. 提交 / PR 整理：继续收敛文档、harness 或发布交接。

## 任务列表

| ID | 文件 | 状态 | 依赖 | 可并行 |
| --- | --- | --- | --- | --- |
| TP-V2-001 | [TP-V2-001-http-ingest-contract.md](TP-V2-001-http-ingest-contract.md) | done | none | TP-V2-004 |
| TP-V2-002 | [TP-V2-002-ingest-auth-and-errors.md](TP-V2-002-ingest-auth-and-errors.md) | done | TP-V2-001 | none |
| TP-V2-003 | [TP-V2-003-ingest-idempotent-upsert.md](TP-V2-003-ingest-idempotent-upsert.md) | done | TP-V2-001 | TP-V2-006 |
| TP-V2-004 | [TP-V2-004-device-config-contract.md](TP-V2-004-device-config-contract.md) | done | none | TP-V2-001 |
| TP-V2-005 | [TP-V2-005-device-pusher-fake-http.md](TP-V2-005-device-pusher-fake-http.md) | done | TP-V2-004 | none |
| TP-V2-006 | [TP-V2-006-device-normalized-payload.md](TP-V2-006-device-normalized-payload.md) | done | TP-V2-001, TP-V2-005 | TP-V2-003 |
| TP-V2-007 | [TP-V2-007-server-sqlite-schema.md](TP-V2-007-server-sqlite-schema.md) | done | TP-V2-003 | none |
| TP-V2-008 | [TP-V2-008-server-snapshot-builder.md](TP-V2-008-server-snapshot-builder.md) | done | TP-V2-007 | none |
| TP-V2-009 | [TP-V2-009-source-staleness-health.md](TP-V2-009-source-staleness-health.md) | done | TP-V2-007 | TP-V2-008 |
| TP-V2-010 | [TP-V2-010-web-api-summary.md](TP-V2-010-web-api-summary.md) | done | TP-V2-008, TP-V2-009 | none |
| TP-V2-011 | [TP-V2-011-web-dashboard-baseline.md](TP-V2-011-web-dashboard-baseline.md) | done | TP-V2-010 | none |
| TP-V2-012 | [TP-V2-012-web-dashboard-failure-states.md](TP-V2-012-web-dashboard-failure-states.md) | done | TP-V2-011 | none |
| TP-V2-013 | [TP-V2-013-server-operations.md](TP-V2-013-server-operations.md) | done | TP-V2-010 | TP-V2-014 |
| TP-V2-014 | [TP-V2-014-device-schedulers.md](TP-V2-014-device-schedulers.md) | done | TP-V2-005 | TP-V2-013 |
| TP-V2-015 | [TP-V2-015-widget-optional-snapshot.md](TP-V2-015-widget-optional-snapshot.md) | done | TP-V2-008 | none |
| TP-V2-016 | [TP-V2-016-official-limits-contract.md](TP-V2-016-official-limits-contract.md) | done | TP-V2-010 | none |
| TP-V2-017 | [TP-V2-017-codex-official-provider.md](TP-V2-017-codex-official-provider.md) | done | TP-V2-016 | none |
| TP-V2-018 | [TP-V2-018-claude-official-provider.md](TP-V2-018-claude-official-provider.md) | done | TP-V2-016 | none |
| TP-V2-019 | [TP-V2-019-limit-windows-store.md](TP-V2-019-limit-windows-store.md) | done | TP-V2-016 | none |
| TP-V2-020 | [TP-V2-020-limits-snapshot-api.md](TP-V2-020-limits-snapshot-api.md) | done | TP-V2-017, TP-V2-018, TP-V2-019 | none |
| TP-V2-021 | [TP-V2-021-limits-presentation.md](TP-V2-021-limits-presentation.md) | done | TP-V2-020 | none |
| TP-V2-022 | [TP-V2-022-production-hardening-baseline.md](TP-V2-022-production-hardening-baseline.md) | done | TP-V2-013, TP-V2-014 | none |
| TP-V2-023 | [TP-V2-023-health-and-bounded-backups.md](TP-V2-023-health-and-bounded-backups.md) | done | TP-V2-022 | none |
| TP-V2-024 | [TP-V2-024-official-limits-runtime-wiring.md](TP-V2-024-official-limits-runtime-wiring.md) | done | TP-V2-021 | none |
| TP-V2-025 | [TP-V2-025-codex-wham-auth-adapter.md](TP-V2-025-codex-wham-auth-adapter.md) | done | TP-V2-024 | none |
| TP-V2-026 | [TP-V2-026-claude-oauth-auth-adapter.md](TP-V2-026-claude-oauth-auth-adapter.md) | done | TP-V2-024 | none |
| TP-V2-027 | [TP-V2-027-codex-app-server-rpc-adapter.md](TP-V2-027-codex-app-server-rpc-adapter.md) | done | TP-V2-024 | none |
| TP-V2-028 | [TP-V2-028-claude-cli-usage-adapter.md](TP-V2-028-claude-cli-usage-adapter.md) | done | TP-V2-024 | none |
| TP-V2-029 | [TP-V2-029-limits-config-contract.md](TP-V2-029-limits-config-contract.md) | done | TP-V2-024 | none |
| TP-V2-030 | [TP-V2-030-limits-dry-run.md](TP-V2-030-limits-dry-run.md) | done | TP-V2-029 | none |
| TP-V2-031 | [TP-V2-031-limits-scheduler-templates.md](TP-V2-031-limits-scheduler-templates.md) | done | TP-V2-030 | none |
| TP-V2-032 | [TP-V2-032-limits-smoke-handoff.md](TP-V2-032-limits-smoke-handoff.md) | done | TP-V2-031 | none |
| TP-V2-033 | [TP-V2-033-limits-config-check.md](TP-V2-033-limits-config-check.md) | done | TP-V2-029 | none |
| TP-V2-034 | [TP-V2-034-v2-index-status-reconcile.md](TP-V2-034-v2-index-status-reconcile.md) | done | none | none |
| TP-V2-035 | [TP-V2-035-v2-backlog-entry-cleanup.md](TP-V2-035-v2-backlog-entry-cleanup.md) | done | TP-V2-034 | none |
| TP-V2-036 | [TP-V2-036-antigravity-limits-fixture-parser.md](TP-V2-036-antigravity-limits-fixture-parser.md) | done | TP-V2-016 | none |
| TP-V2-037 | [TP-V2-037-limits-doctor-readiness.md](TP-V2-037-limits-doctor-readiness.md) | done | TP-V2-033 | none |
| TP-V2-039 | [TP-V2-039-limits-multi-account-cli.md](TP-V2-039-limits-multi-account-cli.md) | done | TP-V2-029, TP-V2-030, TP-V2-037 | none |
| TP-V2-040 | [TP-V2-040-claude-cli-limit-message-parser.md](TP-V2-040-claude-cli-limit-message-parser.md) | done | TP-V2-039 | none |
| TP-V2-041 | [TP-V2-041-limits-http-push.md](TP-V2-041-limits-http-push.md) | done | TP-V2-039, TP-V2-040 | Mobile app prototype work |
| TP-V2-042 | [TP-V2-042-limits-push-launchd-installer.md](TP-V2-042-limits-push-launchd-installer.md) | done | TP-V2-041 | Mobile app prototype work |
| TP-V2-043 | [TP-V2-043-mobile-summary-api-contract.md](TP-V2-043-mobile-summary-api-contract.md) | done | TP-V2-010, TP-V2-020, mobile app prototype approval | none |
| TP-V2-044 | [TP-V2-044-ios-swiftui-shell.md](TP-V2-044-ios-swiftui-shell.md) | done | TP-V2-043 | none |
| TP-V2-045 | [TP-V2-045-ios-widget-summary.md](TP-V2-045-ios-widget-summary.md) | done | TP-V2-044 | none |
| TP-V2-046 | [TP-V2-046-ios-xcode-app-extension-integration.md](TP-V2-046-ios-xcode-app-extension-integration.md) | done | TP-V2-044, TP-V2-045 | none |
| TP-V2-047 | [TP-V2-047-ios-signing-device-install.md](TP-V2-047-ios-signing-device-install.md) | done | TP-V2-046 | none |
| TP-V2-048 | [TP-V2-048-ios-app-icon-asset.md](TP-V2-048-ios-app-icon-asset.md) | done | TP-V2-046 | none |
| TP-V2-049 | [TP-V2-049-ios-swiftui-prototype-surface.md](TP-V2-049-ios-swiftui-prototype-surface.md) | done | TP-V2-044, TP-V2-046 | none |
| TP-V2-050 | [TP-V2-050-ios-swiftui-interactions-and-appearance.md](TP-V2-050-ios-swiftui-interactions-and-appearance.md) | done | TP-V2-049 | none |
| TP-V2-051 | [TP-V2-051-ios-live-mobile-summary-client.md](TP-V2-051-ios-live-mobile-summary-client.md) | done | TP-V2-043, TP-V2-050 | none |
| TP-V2-052 | [TP-V2-052-mobile-period-live-data-correctness.md](TP-V2-052-mobile-period-live-data-correctness.md) | done | TP-V2-043, TP-V2-051 | none |
| TP-V2-053 | [TP-V2-053-production-mobile-summary-deploy.md](TP-V2-053-production-mobile-summary-deploy.md) | done | TP-V2-043, TP-V2-052 | none |
| TP-V2-054 | [TP-V2-054-ios-period-loading-clear-and-number-animation.md](TP-V2-054-ios-period-loading-clear-and-number-animation.md) | done | TP-V2-052, TP-V2-053 | none |
| TP-V2-055 | [TP-V2-055-today-trend-axis-and-ios-drag-tooltip.md](TP-V2-055-today-trend-axis-and-ios-drag-tooltip.md) | done | TP-V2-054 | none |
| TP-V2-056 | [TP-V2-056-ios-breakdown-drilldown.md](TP-V2-056-ios-breakdown-drilldown.md) | done | TP-V2-055 | none |
| TP-V2-057 | [TP-V2-057-ios-trend-chart-dot-polish.md](TP-V2-057-ios-trend-chart-dot-polish.md) | done | TP-V2-055 | none |
| TP-V2-058 | [TP-V2-058-ios-trend-tooltip-overlay.md](TP-V2-058-ios-trend-tooltip-overlay.md) | done | TP-V2-055, TP-V2-057 | none |
| TP-V2-059 | [TP-V2-059-ios-production-server-fail-closed.md](TP-V2-059-ios-production-server-fail-closed.md) | done | TP-V2-051, TP-V2-053 | none |
| TP-V2-060 | [TP-V2-060-mswusage-codex-hourly.md](TP-V2-060-mswusage-codex-hourly.md) | ready | none | mobile UI polish |
| TP-V2-061 | [TP-V2-061-mswusage-codex-hourly-integration.md](TP-V2-061-mswusage-codex-hourly-integration.md) | ready | TP-V2-060 | mobile UI polish |
| TP-V2-062 | [TP-V2-062-ios-high-fidelity-app-redesign.md](TP-V2-062-ios-high-fidelity-app-redesign.md) | ready | TP-V2-059 | TP-V2-060, TP-V2-061 |
| TP-V2-063 | [TP-V2-063-cross-platform-client-directory-boundary.md](TP-V2-063-cross-platform-client-directory-boundary.md) | done | none | docs / architecture |

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
- Usage data agent：先执行 TP-V2-060，新增 MSWusage Codex raw JSONL parser 和 CLI 合约；完成后执行 TP-V2-061，把 Codex 小时换源接入 push / ingest / storage / snapshot。全程保持 `ccusage daily` baseline、Claude blocks 和生产凭据边界不变。
- Mobile App agent：执行 TP-V2-062，把 `docs/prototypes/ios-high-fidelity/HANDOFF.md` 落到 SwiftUI App；不要改移动端 API contract，不要提交生产 token。
- Cross-platform client agent：后续新增 Android、macOS、Windows 时，先从 `docs/architecture/client-platforms.md` 和 `clients/<platform>/README.md` 开任务包；不得复用 legacy macOS Widget 作为新产品 UI。
