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
  selected_rounds: 2
  branch_gate:
    current_branch: "codex/watch-refresh-best-practice"
    default_branch: "main"
    allowed: true
    reason: "Second pass after fixing confirmed P1 findings from round 1."
  actual_reviewer: claude
  actual_model: "opus"
  model_resolution:
    kind: local-claude-default
    value: "opus"
  depth_resolution:
    kind: cli_args
    value: ["--effort", "xhigh"]
    confidence: delegated
  scope: "working tree diff after implementation"
  rounds_completed: 2
  reasons:
    - "Round 1 found stale and WidgetKit reload defects."
    - "Implementation now adds BGAppRefreshTask, WidgetKit reload fixes, stale rendering, and tests."

## Reviewer Output

Request: `reviews/20260622-133816-watch-refresh-request-dirty-r2.md`

Claude confirmed all round-1 P1 findings are fixed and the iPhone background refresh implementation stays inside the stated product/security boundaries.

Remaining review items were P3 robustness and coverage gaps:

- Old Watch cache files without `trend` would fail to decode once after app upgrade.
- Stale summaries with no matching provider window would render `--` rather than `stale`.
- Raw-log path guards diverged between Watch app and Watch widget tests.
- Static tests cover source wiring rather than runtime behavior.

## Triage

findings:
  - id: R2-1
    reviewer_severity: P3
    confirmed_severity: P3
    file: "mobile/ios-xcode/Sources/AIUsageWatchApp/WatchSummaryStore.swift"
    line: 44
    source: introduced
    summary: "New required trend field can blank old Watch caches after upgrade."
    evidence: "A cache written before trend existed will fail to decode."
    action: fixed
  - id: R2-2
    reviewer_severity: P3
    confirmed_severity: P3
    file: "mobile/ios-xcode/Sources/AIUsageWatchWidgetExtension/AIUsageWatchWidget.swift"
    line: 33
    source: introduced
    summary: "Stale no-provider state renders as empty rather than stale."
    evidence: "The no-provider path did not pass the computed stale value into empty state."
    action: fixed
  - id: R2-3
    reviewer_severity: P3
    confirmed_severity: P3
    file: "tests/test_ios_xcode_integration.py"
    line: 290
    source: introduced
    summary: "Raw-log path guard differs between Watch app and widget tests."
    evidence: "The Watch app test did not forbid absolute `/.codex` and `/.claude` paths."
    action: fixed

## Fixes

- Defaulted missing Watch `trend` to an empty points list during decode.
- Preserved stale state on provider-empty quota rings.
- Aligned raw-log path forbidden tokens across Watch app and Watch widget tests.

## Verification

- `PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v`
- `git diff --check`
- iOS simulator build

## Remaining Risk

Runtime data sync still needs simulator/device smoke. Apple background refresh itself cannot be deterministically proven by unit tests; the product must rely on last-updated/stale UI for the no-wakeup case.
