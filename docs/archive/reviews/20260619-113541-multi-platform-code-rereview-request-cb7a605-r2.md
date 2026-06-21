# AI Review Request

## Scope

review_selection:
  selection_mode: auto
  risk_score: 10
  selected_target: diff
  selected_mode: local
  input_form: request_artifact
  selected_model_policy: highest
  selected_depth: deep
  selected_rounds: 1
  branch_gate:
    current_branch: "codex/multi-platform-ai-usage"
    default_branch: "main"
    allowed: true
    reason: "local read-only re-review on feature branch before commit"
  actual_reviewer: "codex-subagent"
  actual_model: "gpt-5.5"
  model_resolution:
    kind: "highest"
    value: "gpt-5.5"
  depth_resolution:
    kind: "provider default"
    value: ["medium"]
    confidence: "delegated"
  scope: "working tree against HEAD, including untracked files listed by git ls-files --others --exclude-standard"
  rounds_completed: 0
  reasons:
    - "second review after confirmed user-visible data correctness fixes"
    - "Claude Code hit session limit; Codex reviewer is the fallback"
    - "final pre-PR review"

Review the current working tree in `/Users/wangzhipeng/Documents/ai-usage-widget`.

## Prior Review Findings To Verify Closed

First final code review found these actionable issues:

1. Widget read the single app-group cache even when the App had last loaded `week`, `month`, or `all`, so a glance could show non-today totals as if they were current.
2. Watch received the same arbitrary period summary and did not show stale/last-updated state.
3. Web visible source cards only showed `groups.by_machine` with token usage, hiding failed/stale/never-seen sources with 0 tokens.
4. Web hero badge used an adjacent-trend temporary percent change that looked like a real period delta.

Fixes now in working tree:

- `MobileSummaryCache` accepts companion cache only when `period.id == "today"`.
- iPhone App uses `shareWithCompanionIfNeeded` so Widget/Watch are only updated from today summaries.
- Widget no longer falls back to the bundled `mobile-summary.json` for runtime display; it shows empty today if no eligible app-group cache exists.
- Widget state marks non-today summaries as `非今日缓存` and old today summaries as `缓存过期`.
- Watch rejects non-today contexts and non-today persisted cache, and displays updated/stale state based on `generated_at`.
- Web source cards merge usage cards with non-ok `source_status` rows and display status-only cards for 0-token failed/stale/never-seen sources.
- Web hero badge now shows `Live` or `No sync`, not a fake percent delta.

## Verification Run After Fixes

```text
PYTHONPATH=src python3 -m unittest discover -s tests -v
# Result: 228 tests passed

cd mobile/ios && swift test
# Result: 30 tests passed

cd clients/macos && swift test
# Result: 10 tests passed

xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination generic/platform=iOS -derivedDataPath /tmp/aiusage-dd-app build CODE_SIGNING_ALLOWED=NO
# Result: BUILD SUCCEEDED

xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileWidgetExtension -configuration Debug -destination generic/platform=iOS -derivedDataPath /tmp/aiusage-dd-widget build CODE_SIGNING_ALLOWED=NO
# Result: BUILD SUCCEEDED

xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageWatchApp -configuration Debug -destination generic/platform=watchOS -derivedDataPath /tmp/aiusage-dd-watch build CODE_SIGNING_ALLOWED=NO
# Result: BUILD SUCCEEDED

git diff --check
# Result: no output

Playwright/Chrome dashboard checks after login:
# Desktop: total 1.67B, delta Live, 2 source cards, 2 quota groups, 24 bars, no horizontal overflow
# Mobile 390px: total 1.67B, delta Live, 2 source cards, no horizontal overflow

agy --model gemini-3.5-flash targeted UX/safety check:
# Result: no blockers, no warnings, all four risks passed
```

## Review Instructions

Treat this as read-only review. Report only findings tied to this working tree scope, with severity, file/path, evidence, and user impact.

Specifically verify:

- The prior four findings are actually fixed.
- No new Widget/Watch path can still show non-today or stale data as current.
- The Web source cards remain usable and do not hide non-ok zero-usage sources.
- The Web hero badge no longer conveys fake precision.
- New tests are meaningful enough to prevent recurrence.
- No `.codex`, `tmp`, `.env`, token, SSH key, or raw usage log path is staged or likely to be staged.

If no actionable findings remain, say no actionable findings and list residual test gaps.

## Out Of Scope

- Historical issues outside changed files.
- Production data writes or deployment actions.
- Secrets, `.env`, SSH keys, raw local or remote usage logs.
- Broad product requests unrelated to this multi-platform design delivery.
