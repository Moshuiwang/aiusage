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
  scope: second and final code review for TP-V2-083 Watch companion implementation
  rounds_completed: 1
  reasons:
    - user requested maximum two AI Review rounds after implementation
    - first code review found eight actionable findings and fixes have been applied

This is round 2, the final allowed review round. Review only the scoped TP-V2-083 changes and the fixes from round 1. Do not review Cloudflare files.

Round 1 report:

- `reviews/20260621-204753-codex-watch-companion-code-local-929fa0d-wctfcode1.md`

Round 1 findings that should be checked for closure:

1. Watch bundle ids must be children of the iPhone app id.
2. First-run default `week` load must still prepare a `today` companion summary.
3. Watch face refresh should have a complication user-info path, not only application context.
4. Circular accessory must distinguish stale/no-cache from real fresh 0%.
5. Non-Codex/no observed Codex users should get a useful fallback.
6. Tests should guard the iPhone-to-Watch JSON decode contract.
7. Widget source should receive the same no-collection boundary coverage.
8. Unused `mobile-summary.json` should not be packaged in the Watch App target.

## Repo State

Current branch: `codex/watch-companion-testflight`
HEAD: `929fa0d`

Verification after fixes:

```text
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
# Ran 18 tests, OK

git diff --check
# passed

xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO -derivedDataPath /private/tmp/aiusage-watch-build-r2 build
# BUILD SUCCEEDED
```

Key current facts:

- `project.yml` uses:
  - iPhone: `com.wangzhipeng.aiusage.mobile`
  - Watch App: `com.wangzhipeng.aiusage.mobile.watch`
  - Watch Widget: `com.wangzhipeng.aiusage.mobile.watch.widget`
- Watch App and Watch Widget share `group.com.wangzhipeng.aiusage.watch`.
- `AIUsageMobileApp.swift` has `ensureTodayCompanionSummary` and calls `transferCurrentComplicationUserInfo`.
- `AIUsageWatchApp.swift` handles `didReceiveUserInfo`.
- `AIUsageWatchWidget.swift` uses `WatchSummaryDisplay.circularText(from:)`.
- `WatchSummaryDisplay.quotaText` falls back to `TokenFormat.compact(summary.period.totalTokens)`.
- `project.yml` no longer packages `Resources/mobile-summary.json` in `AIUsageWatchApp`.

## Review Instructions

Treat this as read-only review. Do not modify files.

First state whether the 8 round-1 findings are closed, partially closed, or still open. Then list any new actionable findings. Include severity, file/path, evidence, user impact, and suggested fix.

Prioritize only issues that can block or materially degrade the owner experience:

- TestFlight upload/install acceptance.
- Watch companion install/embedding.
- Watch face WidgetKit accessory exposure and refresh.
- Real cache sharing between Watch App and Widget extension.
- Stale/no-cache correctness.
- Watch-side no-token/no-server/no-collection boundary.
- Tests passing while the user experience is still broken.

Do not request broad refactors or style-only changes. Ignore Cloudflare and unrelated existing repo issues.

If there are no actionable findings, say no actionable findings and list residual manual verification gaps.

## Out Of Scope

- Cloudflare migration files or docs.
- Full repo architecture review.
- Production deployment.
- TestFlight upload and real device install, except as residual manual verification.
- Secrets, credentials, `.env`, raw usage logs, raw `.claude`, raw `.codex`, SSH keys, or production account files.
