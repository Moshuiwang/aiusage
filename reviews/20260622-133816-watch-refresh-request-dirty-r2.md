# AI Review Request

## Scope

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
  rounds_completed: 1
  reasons:
    - "Round 1 found stale and WidgetKit reload defects."
    - "Implementation now adds BGAppRefreshTask, WidgetKit reload fixes, stale rendering, and tests."

## Repo State

Branch: `codex/watch-refresh-best-practice`

Current diff stat:

```text
docs/architecture/database.md                      |  13 +
docs/architecture/interfaces.md                    |  30 ++
docs/architecture/watch-companion-testflight.md    |  27 +-
docs/product/watch-companion-testflight-prd.md     |  26 ++
docs/task-packages/v2/INDEX.md                     |   2 +
mobile/ios-xcode/Config/AIUsageMobileApp-Info.plist |   8 +
mobile/ios-xcode/Sources/AIUsageMobileApp/AIUsageMobileApp.swift | 35 ++
mobile/ios-xcode/Sources/AIUsageWatchApp/AIUsageWatchApp.swift | 4 +-
mobile/ios-xcode/Sources/AIUsageWatchApp/WatchSummaryStore.swift | 27 +-
mobile/ios-xcode/Sources/AIUsageWatchWidgetExtension/AIUsageWatchWidget.swift | 423 +++++++++++++++++----
mobile/ios-xcode/project.yml                       |   4 +
tests/test_ios_xcode_integration.py                |  81 +++-
```

Verification completed after implementation:

```text
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
git diff --check
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -destination 'platform=iOS Simulator,name=iPhone 17,OS=26.5' build CODE_SIGNING_ALLOWED=NO
```

All passed.

## Review Instructions

Treat this as read-only review. Report only findings tied to this scope. Include severity, file/path, evidence, and user impact. If there are no actionable findings, say so and list residual test gaps.

Focus on:

- Whether round 1 findings are actually fixed:
  - Watch sync reloads all current complication kinds.
  - Complications can show stale state instead of presenting old data as live.
  - Raw-log path guards still protect no raw provider directory leakage without blocking product provider names.
- Whether the new iPhone `BGAppRefreshTask` implementation respects product and security boundaries:
  - Uses only `period=today` for Watch refresh.
  - Uses existing iPhone token/config only.
  - Does not add Watch direct networking or Watch token storage.
  - Does not need API or SQLite migration.
- Whether the static tests cover the owner-visible failure modes well enough for this PR.

## Target Content

Use the current working tree diff and listed files in this repository. Do not inspect or output secrets, `.env`, access tokens, local production config, SSH keys, or raw provider logs.

## Out Of Scope

- Do not review unrelated repo files.
- Do not require a new Watch direct-networking client unless there is a clear Apple-platform reason.
- Do not require a SQLite migration unless the existing mobile summary cannot support the stated Watch UX.
- Do not change files.
