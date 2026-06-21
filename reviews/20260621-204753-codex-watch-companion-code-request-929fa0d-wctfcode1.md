# AI Code Review Request

## Scope

review_selection:
  selection_mode: user
  risk_score: 9
  selected_target: diff
  selected_mode: local
  input_form: request_artifact
  selected_model_policy: highest
  selected_depth: deep
  selected_rounds: 2
  branch_gate:
    current_branch: codex/watch-companion-testflight
    default_branch: main
    allowed: true
    reason: local read-only review on non-default branch
  actual_reviewer: claude
  actual_model: opus
  model_resolution:
    kind: local-claude-default
    value: opus
  depth_resolution:
    kind: cli_args
    value: ["--effort", "xhigh"]
    confidence: exact
  scope: TP-V2-083 Watch companion TestFlight and watch face WidgetKit implementation
  rounds_completed: 0
  reasons:
    - user requested AI Review after implementation, maximum two rounds
    - implementation touches TestFlight install structure, watchOS widget extension, App Group cache, and Xcode project wiring

Review only the current TP-V2-083 implementation and supporting docs/tests. Do not review or comment on Cloudflare files.

Primary files:

- `docs/product/watch-companion-testflight-prd.md`
- `docs/architecture/watch-companion-testflight.md`
- `docs/task-packages/v2/TP-V2-083-watch-companion-testflight.md`
- `mobile/ios-xcode/project.yml`
- `mobile/ios-xcode/AIUsageMobile.xcodeproj/project.pbxproj`
- `mobile/ios-xcode/Config/AIUsageWatchApp.entitlements`
- `mobile/ios-xcode/Config/AIUsageWatchWidgetExtension-Info.plist`
- `mobile/ios-xcode/Config/AIUsageWatchWidgetExtension.entitlements`
- `mobile/ios-xcode/Sources/AIUsageWatchApp/AIUsageWatchApp.swift`
- `mobile/ios-xcode/Sources/AIUsageWatchApp/AIUsageWatchSummaryView.swift`
- `mobile/ios-xcode/Sources/AIUsageWatchApp/WatchSummaryStore.swift`
- `mobile/ios-xcode/Sources/AIUsageWatchWidgetExtension/AIUsageWatchWidget.swift`
- `tests/test_ios_xcode_integration.py`

## Repo State

Current branch: `codex/watch-companion-testflight`
HEAD: `929fa0d`

```text
## codex/watch-companion-testflight...origin/main
 M docs/architecture/architecture.md
 M docs/product-brief.md
 M docs/task-packages/v2/INDEX.md
 M mobile/ios-xcode/AIUsageMobile.xcodeproj/project.pbxproj
 D mobile/ios-xcode/Sources/AIUsageMobileWidgetExtension/AIUsageWatchApp.swift
 M mobile/ios-xcode/project.yml
 M tests/test_ios_xcode_integration.py
?? docs/architecture/watch-companion-testflight.md
?? docs/product/
?? docs/task-packages/v2/TP-V2-083-watch-companion-testflight.md
?? mobile/ios-xcode/Config/AIUsageWatchApp.entitlements
?? mobile/ios-xcode/Config/AIUsageWatchWidgetExtension-Info.plist
?? mobile/ios-xcode/Config/AIUsageWatchWidgetExtension.entitlements
?? mobile/ios-xcode/Sources/AIUsageWatchApp/
?? mobile/ios-xcode/Sources/AIUsageWatchWidgetExtension/
?? reviews/
```

Implementation summary:

- iPhone app now embeds `AIUsageWatchApp`.
- Watch app now embeds `AIUsageWatchWidgetExtension`.
- Watch App and Watch Widget extension share `group.com.wangzhipeng.aiusage.watch`.
- Watch code moved out of the iOS widget extension source directory into `Sources/AIUsageWatchApp`.
- `WatchSummaryStore` now reads/writes the shared App Group container and rejects non-`today` summaries.
- New watchOS WidgetKit extension supports `.accessoryRectangular`, `.accessoryCircular`, and `.accessoryInline`.
- Watch app reloads the watch widget timeline after receiving a fresh summary.

Verification already run:

```text
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
# Ran 17 tests, OK

git diff --check
# passed

xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO -derivedDataPath /private/tmp/aiusage-watch-build build
# BUILD SUCCEEDED
# Target dependency graph included AIUsageMobileApp -> AIUsageWatchApp -> AIUsageWatchWidgetExtension
# Build copied AIUsageWatchApp.app into AIUsageMobileApp.app/Watch
```

## Review Instructions

Treat this as read-only review. Do not modify files.

Return findings first, scoped to this change. Include severity, file/path, evidence, user impact, and suggested fix.

Prioritize:

- Whether TestFlight/iPhone install shape is likely to include the Watch companion.
- Whether the watchOS WidgetKit extension is embedded correctly and can appear in the watch face editor.
- Whether the Watch app and watch widget can actually share real cached data.
- Whether the widget can accidentally show fixture/empty data as success.
- Whether Watch code violates data boundaries by reading server token, URL, SQLite, raw logs, SSH, provider runtime, or collector code.
- Whether tests are too weak and could pass while the user still cannot install/use the Watch face entry.

Do not request broad refactors or style-only changes. Ignore Cloudflare and unrelated existing repo issues.

If there are no actionable findings, say no actionable findings and list residual manual verification gaps.

## Out Of Scope

- Cloudflare migration files or docs.
- Full repo architecture review.
- Production deployment.
- TestFlight upload and real device install, except as residual manual verification.
- Secrets, credentials, `.env`, raw usage logs, raw `.claude`, raw `.codex`, SSH keys, or production account files.
