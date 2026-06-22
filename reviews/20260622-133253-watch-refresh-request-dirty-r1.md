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
  selected_rounds: 1
  branch_gate:
    current_branch: "codex/watch-refresh-best-practice"
    default_branch: "main"
    allowed: true
    reason: "User explicitly requested PR workflow for Watch refresh best practice."
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
  rounds_completed: 0
  reasons:
    - "Cross-client Watch refresh behavior touches mobile summary, WidgetKit, WatchConnectivity, and install validation."
    - "Security boundary: Watch must not become a second token-bearing client."

Review these files and the current working tree diff:

- `docs/task-packages/v2/TP-V2-085-watch-refresh-best-practice.md`
- `docs/task-packages/v2/INDEX.md`
- `docs/product/watch-companion-testflight-prd.md`
- `docs/architecture/watch-companion-testflight.md`
- `docs/architecture/interfaces.md`
- `docs/architecture/database.md`
- `mobile/ios-xcode/Sources/AIUsageWatchApp/WatchSummaryStore.swift`
- `mobile/ios-xcode/Sources/AIUsageWatchWidgetExtension/AIUsageWatchWidget.swift`
- `tests/test_ios_xcode_integration.py`

## Repo State

Branch: `codex/watch-refresh-best-practice`

Current diff stat:

```text
docs/architecture/database.md                      |  13 +
docs/architecture/interfaces.md                    |  30 ++
docs/architecture/watch-companion-testflight.md    |  27 +-
docs/product/watch-companion-testflight-prd.md     |  26 ++
docs/task-packages/v2/INDEX.md                     |   2 +
mobile/ios-xcode/Sources/AIUsageWatchApp/WatchSummaryStore.swift        |  27 +-
mobile/ios-xcode/Sources/AIUsageWatchWidgetExtension/AIUsageWatchWidget.swift | 405 +++++++++++++++++----
tests/test_ios_xcode_integration.py                |  28 +-
```

Latest relevant verification before this review:

```text
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
git diff --check
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -destination 'platform=iOS Simulator,name=iPhone 17,OS=26.5' build CODE_SIGNING_ALLOWED=NO
```

All three passed before adding the new refresh docs. Implementation of BGAppRefreshTask has not started yet.

## Review Instructions

Treat this as read-only review. Report only findings tied to this scope. Include severity, file/path, evidence, and user impact. If there are no actionable findings, say so and list residual test gaps.

Focus on:

- Whether the product/architecture docs match Apple's practical refresh model for WidgetKit, Background App Refresh, and WatchConnectivity.
- Whether the docs correctly avoid promising realtime Watch data.
- Whether the docs keep the security boundary: no Watch-side token, no Watch-side direct server networking, no Watch-side provider/SQLite/raw-log access.
- Whether the restored Watch complications meet the product intent: two default addable circles, one Codex and one Claude Code, each using two rings and center account name.
- Whether the implementation plan should require any API or SQLite migration that is currently missing.
- Whether there is a likely gap in WidgetKit timeline reload for the restored complication kinds.

## Target Content

Use the current working tree diff and listed files in this repository. Do not inspect or output secrets, `.env`, access tokens, local production config, SSH keys, or raw provider logs.

## Out Of Scope

- Do not review unrelated repo files.
- Do not require a new Watch direct-networking client unless there is a clear Apple-platform reason.
- Do not require a SQLite migration unless the existing mobile summary cannot support the stated Watch UX.
- Do not change files.
