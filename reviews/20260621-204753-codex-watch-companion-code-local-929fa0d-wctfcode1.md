# AI Code Review Report

## Selection

```yaml
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
  rounds_completed: 1
```

Request artifact: `reviews/20260621-204753-codex-watch-companion-code-request-929fa0d-wctfcode1.md`

## Reviewer Output

Claude reported 8 scoped findings:

1. High: Watch App bundle id was not a child of the iPhone App bundle id, risking TestFlight upload rejection.
2. Medium: first-run default `week` load would not push a `today` companion summary.
3. Medium: watch face refresh depended on the Watch App receiving application context; no complication user-info path existed.
4. Medium: circular accessory showed no-cache/stale as `0`, indistinguishable from a real fresh 0%.
5. Low: widget only displayed Codex official observed windows, with no fallback for users without Codex quota.
6. Low: tests did not guard the iPhone-to-Watch JSON decode contract.
7. Low: no-collection boundary test did not fully cover the widget extension source.
8. Low: `mobile-summary.json` was packaged into the Watch App but was not read.

## Triage

All 8 findings were confirmed as scoped and actionable.

## Fixes

- Changed Watch bundle ids to be children of the iPhone app id:
  - `com.wangzhipeng.aiusage.mobile.watch`
  - `com.wangzhipeng.aiusage.mobile.watch.widget`
- Added first-run `today` companion fetch so the Watch surfaces can receive a real cache even when the visible default period is `week`.
- Added `transferCurrentComplicationUserInfo` on the iPhone side and `didReceiveUserInfo` handling on the Watch side.
- Changed circular accessory stale/no-cache text to `--` instead of displaying `0`.
- Added a non-Codex fallback to show today total tokens when no observed Codex quota window exists.
- Strengthened tests for:
  - bundle id hierarchy,
  - complication user-info path,
  - widget no-collection boundary,
  - Watch decode key contract,
  - shared App Group cache,
  - removal of dead Watch App fixture resource.
- Removed `mobile-summary.json` from the Watch App target resources.
- Regenerated `AIUsageMobile.xcodeproj` with `xcodegen generate`.

## Verification

Ran:

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
git diff --check
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO -derivedDataPath /private/tmp/aiusage-watch-build-r2 build
```

Results:

- `tests.test_ios_xcode_integration`: 18 tests passed.
- `git diff --check`: passed.
- `xcodebuild`: `BUILD SUCCEEDED`; dependency graph still includes `AIUsageMobileApp -> AIUsageWatchApp -> AIUsageWatchWidgetExtension`.

## Remaining Risk

Real TestFlight upload/validation, Apple Watch install, watch face editor exposure, and cross-process App Group read/write remain manual verification items because they require signing and paired devices.
