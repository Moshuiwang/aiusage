# AI Review Report

## Selection

review_selection:
  selection_mode: auto
  risk_score: 10
  selected_target: diff
  selected_mode: local
  input_form: request_artifact
  selected_model_policy: highest
  selected_depth: deep
  selected_rounds: 2
  branch_gate:
    current_branch: "codex/multi-platform-ai-usage"
    default_branch: "main"
    allowed: true
    reason: "local read-only review on feature branch before commit"
  actual_reviewer: "codex-subagent"
  actual_model: "gpt-5.5"
  model_resolution:
    kind: "highest"
    value: "gpt-5.5"
  depth_resolution:
    kind: "delegated"
    value: ["medium"]
    confidence: "delegated"
  scope: "working tree against HEAD"
  rounds_completed: 2
  reasons:
    - "final pre-PR review"
    - "cross-platform UI and data correctness"
    - "Widget/Watch companion cache safety"
    - "production-facing dashboard surface"

## Reviewer Output

Request artifacts:

- `reviews/20260619-112412-multi-platform-code-request-cb7a605-fr3a7c.md`
- `reviews/20260619-113541-multi-platform-code-rereview-request-cb7a605-r2.md`

Claude Code was attempted first and returned a session limit error resetting at 12:40 Asia/Shanghai, so review continued with Codex subagents as the approved fallback. Antigravity/Gemini was used for the testing/design check pass.

## Triage

Confirmed findings:

findings:
  - id: R1
    reviewer_severity: High
    confirmed_severity: P1
    file: "mobile/ios-xcode/Sources/AIUsageMobileApp/AIUsageMobileApp.swift"
    source: introduced
    summary: "Widget/Watch companion cache could be overwritten by non-today summaries."
    evidence: "App wrote any loaded period into one app-group cache and Watch context."
    action: fixed
  - id: R2
    reviewer_severity: High
    confirmed_severity: P1
    file: "mobile/ios-xcode/Sources/AIUsageMobileWidgetExtension/AIUsageWatchApp.swift"
    source: introduced
    summary: "Watch could display stale data without clear updated/stale state."
    evidence: "Watch stored and displayed the last summary without stale classification."
    action: fixed
  - id: R3
    reviewer_severity: Medium
    confirmed_severity: P2
    file: "src/ai_usage_widget/static/dashboard.js"
    source: introduced
    summary: "Visible Web source cards could hide failed/stale/never-seen sources with zero usage."
    evidence: "Initial source cards used only positive-token machine groups; later re-review found status cards could still be sliced off."
    action: fixed
  - id: R4
    reviewer_severity: Medium
    confirmed_severity: P2
    file: "src/ai_usage_widget/static/dashboard.js"
    source: introduced
    summary: "Hero badge showed a trend-adjacent percent that looked like a real period delta."
    evidence: "Client computed percentage from recent non-zero chart points."
    action: fixed
  - id: R5
    reviewer_severity: Medium
    confirmed_severity: P2
    file: "mobile/ios/Sources/AIUsageMobileCore/WidgetSummary.swift"
    source: introduced
    summary: "Medium Widget did not show stale/non-today text or updated time."
    evidence: "Medium size showed only a colored dot beside the main value."
    action: fixed

## Fixes

- Added `MobileSummaryCache` companion rules: only `today` summaries can be written/read for Widget and Watch, and companion data older than two hours is stale.
- Changed the iPhone app to call `shareWithCompanionIfNeeded`, so browsing week/month/all in the App does not overwrite Widget/Watch glance data.
- Changed Watch to reject non-today application context and persisted cache, and to display updated/stale state from `generated_at`.
- Changed Widget state to expose period, updated time, stale, and non-today status text; medium Widget now renders the text instead of only a color dot.
- Changed Web source cards to merge usage cards with non-ok source status cards and reserve up to two visible slots for status cards.
- Replaced the fake hero percentage with a neutral `Live` / `No sync` badge.

## Verification

Passed after the final fixes:

```text
PYTHONPATH=src python3 -m unittest discover -s tests -v
cd mobile/ios && swift test
cd clients/macos && swift test
xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination generic/platform=iOS -derivedDataPath /tmp/aiusage-dd-app2 build CODE_SIGNING_ALLOWED=NO
xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileWidgetExtension -configuration Debug -destination generic/platform=iOS -derivedDataPath /tmp/aiusage-dd-widget2 build CODE_SIGNING_ALLOWED=NO
xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageWatchApp -configuration Debug -destination generic/platform=watchOS -derivedDataPath /tmp/aiusage-dd-watch2 build CODE_SIGNING_ALLOWED=NO
git diff --check
```

Additional UI/data checks:

- Playwright/Chrome desktop and mobile dashboard screenshots showed `Live`, quota rings, trend bars, source cards, and no horizontal overflow.
- Antigravity/Gemini targeted checks reported no blockers or warnings after the final source-card and medium-widget fixes.

## Remaining Risk

- Physical iPhone and Apple Watch installation was not completed because Xcode reported the devices offline/ineligible in the current environment. Code builds for iOS, Widget, and watchOS passed.
- Production deployment still needs the remote source sync and service restart step after commit/PR, using the existing `vpn2` deployment path.
