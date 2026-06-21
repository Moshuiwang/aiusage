# AI Review Report

## Selection

```yaml
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
    current_branch: main
    default_branch: main
    allowed: true
    reason: local read-only review with explicit scoped artifact
  actual_reviewer: claude
  actual_model: opus
  model_resolution:
    kind: local-claude-default
    value: opus
  depth_resolution:
    kind: cli_args
    value: ["--effort", "xhigh"]
    confidence: exact
  scope: macOS menu bar client files only
  rounds_completed: 2
  reasons:
    - new macOS client and installer
    - token/config/runtime path boundary
    - production API read smoke
```

## Reviewer Output

Request artifact: `reviews/20260618-093335-main-request-dirty-macos64.md`

Round 1 found one low severity correctness issue: rapid period switching could allow an older request to overwrite a newer selected period. It also listed non-blocking test gaps.

Round 2 found no actionable correctness findings after the sequencing fix. It noted that stale in-flight requests are ignored rather than cancelled, which is acceptable for this low-frequency menu bar client.

## Triage

```yaml
findings:
  - id: R1
    reviewer_severity: LOW
    confirmed_severity: P2
    file: clients/macos/Sources/AIUsageMenuBarApp/MenuBarAppModel.swift
    source: introduced
    summary: Rapid period switching could show or cache stale period data.
    evidence: refresh launched independent tasks and applied whichever response returned last.
    action: fixed
```

## Fixes

- Added `refreshSequence` gating in `MenuBarAppModel` so only the latest request can update summary, error state, loading state, or cache.
- Added `AIUsageMenuBarAppTests` for stale success and stale failure paths.
- Replaced fixed-delay test waiting with condition-based waits.

## Verification

```bash
cd clients/macos && swift test
cd clients/macos && swift build -c release
python3 -m unittest discover -s clients/macos/Tests -p 'test_*.py' -v
python3 clients/macos/scripts/install_menu_bar_app.py --server-url https://vpn2.chunbai.com:8443 --dry-run
git diff --check -- .gitignore clients/macos docs/task-packages/v2/INDEX.md docs/task-packages/v2/TP-V2-064-macos-menu-bar-client.md
```

Manual/local smoke:

- Installed app to `~/Applications/AI Usage Menu Bar.app`.
- Verified runtime path is under `~/Library/Application Support/ai-usage-widget/macos-menu-bar`.
- Verified installed app bundle has executable and `LSUIElement=true`.
- Launched app and confirmed `AIUsageMenuBar` process was running.
- Verified `/api/mobile/summary` returned HTTP 200 for today, week, month, and all using local configured token.

## Remaining Risk

- Auto-upgrade is intentionally out of scope.
- The app ignores stale in-flight requests instead of cancelling them; current refresh frequency and user-triggered switching make this acceptable.
- Visual verification is limited to native launch/process smoke in this run; no screenshot automation was used for the menu bar popover.
