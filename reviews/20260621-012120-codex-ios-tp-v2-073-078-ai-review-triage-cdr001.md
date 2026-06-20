# AI Review Report

## Selection

```yaml
review_selection:
  selection_mode: user
  selected_target: diff
  selected_mode: local
  input_form: request_artifact
  selected_model_policy: highest
  selected_depth: deep
  selected_rounds: 1
  branch_gate:
    current_branch: "codex/ios-tp-v2-073-078"
    default_branch: "origin/main"
    allowed: true
    reason: "local read-only review of explicit uncommitted working-tree diff"
  actual_reviewer: claude
  actual_model: "opus"
  depth_resolution:
    kind: cli_args
    value: ["--effort", "xhigh"]
    confidence: exact
  scope: "current uncommitted working tree, including untracked files"
  rounds_completed: 1
```

Request artifact: `reviews/20260621-010108-codex-ios-tp-v2-073-078-request-dirty-cdr001.md`

Raw reviewer output: `reviews/20260621-010108-codex-ios-tp-v2-073-078-claude-opus-xhigh-raw-cdr001.txt`

Second pass was attempted but Claude Code returned a session-limit error. Per updated skill behavior, no wrapper fallback was used.

## Triage

```yaml
findings:
  - id: R1
    reviewer_severity: Medium
    confirmed_severity: P2
    file: "tests/test_web_server.py"
    source: introduced
    summary: "Fixed reset_at made mobile summary test fail after 2026-06-22"
    action: fixed
  - id: R2
    reviewer_severity: Low-Medium
    confirmed_severity: P2
    file: "src/ai_usage_widget/mobile_summary.py, mobile/ios/Sources/AIUsageMobileCore/MobileViewModel.swift"
    source: introduced
    summary: "0-token failed sources were hidden from the health badge"
    action: fixed
  - id: R3
    reviewer_severity: Low
    confirmed_severity: P3
    file: "src/ai_usage_widget/mobile_summary.py"
    source: introduced
    summary: "by_os_user could still show 0-token users"
    action: fixed
  - id: R4
    reviewer_severity: Low
    confirmed_severity: P3
    file: "src/ai_usage_widget/mobile_summary.py"
    source: introduced
    summary: "Unknown safe plan labels preserved internal separators"
    action: fixed
  - id: R5
    reviewer_severity: Low
    confirmed_severity: accepted_risk
    file: "packages/design-tokens/generate_ai_usage_icon.py"
    source: introduced
    summary: "Light and dark 1024 app icons are currently identical"
    action: accepted_risk
```

## Fixes

- Replaced the fixed future `reset_at` in the web server test with a runtime future reset so the test remains stable after 2026-06-22.
- Kept the iPhone Sources list period-scoped, while preserving failed 0-token sources in the mobile payload for health status.
- Updated iOS health text to count failed sources from the full source status payload, not only current-period visible sources.
- Filtered 0-token OS users out of the mobile `by_os_user` breakdown.
- Humanized safe unknown plan labels so internal separators like `_` do not appear in the quota card.
- Left identical light/dark 1024 icons as an intentional TP-V2-073 tradeoff: opaque single-brand artwork is preferred for the iOS exit animation issue.

## Verification

```text
PYTHONPATH=src python3 -m unittest tests.test_mobile_summary tests.test_snapshot_builder.TestSnapshotBuilder.test_build_snapshot_includes_known_ai_accounts_without_hourly_facts tests.test_snapshot_builder.TestSnapshotBuilder.test_build_snapshot_includes_account_hourly_summary_without_changing_daily_total tests.test_web_server.TestWebServerSummary -v
Result: 34 tests passed.

cd mobile/ios && swift test
Result: 38 tests passed.

PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration.IOSXcodeIntegrationTests.test_ios_app_icons_are_fully_opaque_square_artwork tests.test_ios_xcode_integration.IOSXcodeIntegrationTests.test_bottom_navigation_uses_liquid_glass_icon_treatment -v
Result: 2 tests passed.

git diff --check
Result: passed.
```

Production follow-up:

- Deployed updated `src/ai_usage_widget/mobile_summary.py` to `vpn2`.
- Restarted `ai-usage-server`; service reported active.
- Verified production mobile summary for today, week, month, and all.
- Rebuilt, installed, and launched the iPhone App with the guarded installer.

## Remaining Risk

- The source list remains period-scoped by design. Failed zero-token sources now influence health text but are not shown as period usage rows.
- Light and dark 1024 app icons intentionally remain the same opaque brand artwork unless a later design task asks for distinct dark-mode marketing artwork.
