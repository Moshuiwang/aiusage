# AI Review Report

## Selection

review_selection:
  selection_mode: auto
  risk_score: 7
  selected_target: diff
  selected_mode: local
  input_form: request_artifact
  selected_model_policy: highest
  selected_depth: standard
  selected_rounds: 1
  branch_gate:
    current_branch: "codex/watch-refresh-best-practice"
    default_branch: "main"
    allowed: true
    reason: "User requested PR workflow for Apple Watch refresh best practice."
  actual_reviewer: claude
  actual_model: "opus"
  model_resolution:
    kind: local-claude-default
    value: "opus"
  depth_resolution:
    kind: cli_args
    value: ["--effort", "xhigh"]
    confidence: delegated
  scope: "working tree diff before implementation"
  rounds_completed: 1
  reasons:
    - "Cross-client Watch refresh behavior touches mobile summary, WidgetKit, WatchConnectivity, and install validation."
    - "Security boundary: Watch must not become a second token-bearing client."

## Reviewer Output

Request: `reviews/20260622-133253-watch-refresh-request-dirty-r1.md`

Claude reported two high-severity issues and one low-severity test coverage concern:

- F1: WatchConnectivity receipt still reloads deleted widget kind `AIUsageWatchWidget`; the new Codex, Claude, and Today complication kinds will not reload immediately.
- F2: Complications never compute stale state, so old data can look current.
- F3: Security guard changed `.codex` / `.claude` to `~/.codex` / `~/.claude`; this avoids false positives for provider names but weakens raw-log-path detection.

Claude also confirmed no new HTTP endpoint or SQLite migration is required.

## Triage

findings:
  - id: R1
    reviewer_severity: High
    confirmed_severity: P1
    file: "mobile/ios-xcode/Sources/AIUsageWatchApp/AIUsageWatchApp.swift"
    line: 69
    source: introduced
    summary: "Watch sync reloads an obsolete WidgetKit kind."
    evidence: "The restored complication widgets use three explicit kinds, but the reload path still targets AIUsageWatchWidget."
    action: fixed
  - id: R2
    reviewer_severity: High
    confirmed_severity: P1
    file: "mobile/ios-xcode/Sources/AIUsageWatchWidgetExtension/AIUsageWatchWidget.swift"
    line: 33
    source: introduced
    summary: "Complications do not surface stale state."
    evidence: "QuotaRingState hardcodes isStale=false and TodayChartState has no stale field."
    action: fixed
  - id: R3
    reviewer_severity: Low
    confirmed_severity: P3
    file: "tests/test_ios_xcode_integration.py"
    line: 287
    source: introduced
    summary: "Raw-log directory guard became narrower."
    evidence: "Bare provider names are now product enum values, but absolute raw-log paths should still be blocked."
    action: fixed

## Fixes

- Add static tests for the new WidgetKit reload kinds.
- Add static tests for complication stale rendering.
- Restore raw-log path coverage without blocking legitimate `codex` and `claude` provider names.

## Verification

Pending after implementation:

- `PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v`
- `git diff --check`
- iOS simulator build

## Remaining Risk

The background refresh implementation is still pending at this report point. It needs separate tests and build verification before PR.
