# AI Review Report

## Selection

```yaml
review_selection:
  selection_mode: user
  risk_score: 6
  selected_target: files:docs/product/watch-companion-testflight-prd.md,docs/architecture/watch-companion-testflight.md,docs/task-packages/v2/TP-V2-083-watch-companion-testflight.md
  selected_mode: local
  input_form: request_artifact
  selected_model_policy: highest
  selected_depth: standard
  selected_rounds: 1
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
  scope: re-review revised Watch/TestFlight planning docs plus minimal integration references
  rounds_completed: 1
  reasons:
    - user requested another Claude Review after fixes
    - verify previous findings are actually closed before implementation starts
    - docs define TestFlight install, Watch companion, watch face WidgetKit accessory, and data-boundary promises
```

Request artifact: `reviews/20260621-203156-codex-watch-companion-testflight-request-929fa0d-wctf02.md`

Reviewer command:

```bash
claude --model opus --effort xhigh -p "Read reviews/20260621-203156-codex-watch-companion-testflight-request-929fa0d-wctf02.md and return only scoped re-review findings tied to its scope. Treat it as read-only review. Use Chinese. First state whether previous findings are closed, partially closed, or still open. Then list any new actionable findings with severity, file/path, evidence, user impact, and suggested fix. If none, say no actionable findings and list residual manual verification gaps."
```

## Reviewer Output

Claude reported that all 5 previous findings are closed:

1. Watch face implementation path now requires an embedded watchOS WidgetKit extension.
2. Stale threshold is aligned to the current 2-hour Watch behavior.
3. Watch face family wording now uses concrete WidgetKit accessory families.
4. Task package verification is closed at the specification layer because red tests now cover companion relationship, watchOS widget extension, accessory families, local cache, and no Watch-side collection.
5. TP-V2-070 MobileSummary sync is now clearly marked as the baseline.

Claude found 1 new actionable issue:

- P2: the docs say the new watchOS WidgetKit extension reads watch-local cache, but do not specify an App Group/shared container. A Watch app and its widget extension are separate processes, and the current `WatchSummaryStore` writes to the Watch app's private caches directory.

## Triage

```yaml
findings:
  - id: R2-1
    reviewer_severity: P2
    confirmed_severity: P2
    file: docs/architecture/watch-companion-testflight.md
    line: 163
    source: introduced
    summary: watchOS widget extension shared-cache requirement is missing.
    evidence: docs say the watchOS WidgetKit accessory reads watch-local cache, but current WatchSummaryStore writes to .cachesDirectory in mobile/ios-xcode/Sources/AIUsageMobileWidgetExtension/AIUsageWatchApp.swift. mobile/ios-xcode/project.yml gives App Group entitlements to the iOS app and iOS widget only; AIUsageWatchApp has no entitlements and no AIUsageWatchWidgetExtension exists yet.
    action: accepted_risk
```

Confirmed supporting facts:

- `mobile/ios-xcode/Sources/AIUsageMobileWidgetExtension/AIUsageWatchApp.swift` uses `.cachesDirectory`.
- `mobile/ios-xcode/project.yml` has App Group entitlements for `AIUsageMobileApp` and `AIUsageMobileWidgetExtension`, but not for `AIUsageWatchApp`.
- `mobile/ios-xcode/Config/` has no Watch entitlement file.

## Fixes

No fixes were made in this review pass. The user asked for Claude Review only.

Recommended document fix:

- In PRD, architecture, and TP-V2-083, state that Watch App and the new watchOS WidgetKit extension need a shared App Group container for the Watch-local cache.
- Add red tests requiring both targets to declare the same watchOS App Group entitlement and requiring the widget extension to read the shared container rather than the Watch App private `.cachesDirectory`.
- Mention that the current `WatchSummaryStore` private-cache path must be migrated or wrapped for extension-safe shared-cache access.

## Verification

Ran:

```bash
git diff --check
```

Result: passed.

No code tests were run because this was a read-only document review.

## Remaining Risk

The revised docs are much stronger than round 1, but one user-visible risk remains: if implementation follows the current docs exactly, the Watch face accessory may appear in the editor but still show empty or fixture data because it cannot read the Watch App's private cache. This should be fixed in the docs before implementation starts.
