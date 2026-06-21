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
  scope: second and final code review for TP-V2-083 Watch companion implementation
  rounds_completed: 2
```

Request artifact: `reviews/20260621-205750-codex-watch-companion-code-rereview-request-929fa0d-wctfcode2.md`

## Reviewer Output

Claude reported that the 8 round-1 findings were closed. It found 1 new actionable issue:

- High: `AIUsageWatchApp` was missing `WKCompanionAppBundleIdentifier`, which can block archive/upload validation or companion installation even though normal build passes.

## Triage

```yaml
findings:
  - id: R2-1
    reviewer_severity: High
    confirmed_severity: P1
    file: mobile/ios-xcode/project.yml
    source: introduced
    summary: Watch App Info.plist lacked WKCompanionAppBundleIdentifier.
    evidence: Watch App was embedded as a companion app but generated Info.plist had only WKApplication; no WKCompanionAppBundleIdentifier existed before the fix.
    action: fixed
```

## Fixes

- Added `WKCompanionAppBundleIdentifier: com.wangzhipeng.aiusage.mobile` to `AIUsageWatchApp` in `mobile/ios-xcode/project.yml`.
- Regenerated `AIUsageMobile.xcodeproj` and `Config/AIUsageWatchApp-Info.plist`.
- Added tests asserting the companion bundle id is present in the generated project configuration.

No third review round was run because the user capped AI Review at two rounds.

## Verification

Ran after fixing the round-2 finding:

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
git diff --check
rg -n "WKCompanionAppBundleIdentifier|com.wangzhipeng.aiusage.mobile.watch|com.wangzhipeng.aiusage.mobile.watch.widget" mobile/ios-xcode/project.yml mobile/ios-xcode/Config/AIUsageWatchApp-Info.plist mobile/ios-xcode/AIUsageMobile.xcodeproj/project.pbxproj tests/test_ios_xcode_integration.py
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO -derivedDataPath /private/tmp/aiusage-watch-build-final build
```

Results:

- `tests.test_ios_xcode_integration`: 18 tests passed.
- `git diff --check`: passed.
- `rg`: confirmed `WKCompanionAppBundleIdentifier` is generated and Watch bundle ids are under the iPhone bundle id.
- `xcodebuild`: `BUILD SUCCEEDED`.

## Remaining Risk

Manual verification is still required for:

- real archive + validation/upload,
- TestFlight install,
- iPhone Watch app companion installation,
- watch face editor exposure,
- real App Group cross-process read/write on a signed paired device,
- freshness/stale behavior after the 2-hour window.
