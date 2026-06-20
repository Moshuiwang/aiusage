# AI Review Request

## Scope

```yaml
review_selection:
  selection_mode: user
  risk_score: 10
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
  model_resolution:
    kind: local-claude-default
    value: "opus"
  depth_resolution:
    kind: cli_args
    value: ["--effort", "xhigh"]
    confidence: exact
  scope: "current uncommitted working tree, including untracked files"
  rounds_completed: 0
  reasons:
    - "iOS app UX changes"
    - "mobile API contract changes"
    - "production deployment path touched during validation"
    - "account label and plan label safety"
```

Review the current uncommitted working tree in `/Users/wangzhipeng/Documents/ai-usage-widget`.

Treat this as read-only review. Do not modify files, stage files, commit, run deploy commands, read `.env`, print tokens, or access private raw usage logs.

## Repo State

Current branch: `codex/ios-tp-v2-073-078`

Default branch: `origin/main`

Dirty state:

```text
 M docs/task-packages/v2/INDEX.md
 M mobile/ios-xcode/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon-1024-dark.png
 M mobile/ios-xcode/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon-1024.png
 M mobile/ios-xcode/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon-20@2x.png
 M mobile/ios-xcode/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon-20@3x.png
 M mobile/ios-xcode/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon-29@2x.png
 M mobile/ios-xcode/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon-29@3x.png
 M mobile/ios-xcode/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon-40@2x.png
 M mobile/ios-xcode/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon-40@3x.png
 M mobile/ios-xcode/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon-60@2x.png
 M mobile/ios-xcode/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon-60@3x.png
 M mobile/ios/Sources/AIUsageMobileCore/AIUsageMobileRootView.swift
 M mobile/ios/Sources/AIUsageMobileCore/MobileSummary.swift
 M mobile/ios/Sources/AIUsageMobileCore/MobileViewModel.swift
 M mobile/ios/Tests/AIUsageMobileCoreTests/MobileSummaryTests.swift
 M packages/design-tokens/generate_ai_usage_icon.py
 M src/ai_usage_widget/mobile_summary.py
 M src/ai_usage_widget/snapshot_builder.py
 M tests/test_ios_xcode_integration.py
 M tests/test_mobile_summary.py
 M tests/test_snapshot_builder.py
 M tests/test_web_server.py
?? docs/task-packages/v2/TP-V2-073-ios-app-icon-opaque-exit-animation.md
?? docs/task-packages/v2/TP-V2-074-ios-navigation-liquid-glass-icons.md
?? docs/task-packages/v2/TP-V2-075-ios-claude-5h-quota-period-consistency.md
?? docs/task-packages/v2/TP-V2-076-ios-quota-card-account-label.md
?? docs/task-packages/v2/TP-V2-077-ios-quota-5h-zero-state-layout.md
?? docs/task-packages/v2/TP-V2-078-ios-sources-current-period-and-updated-date.md
?? docs/task-packages/v2/assets/
?? reviews/20260621-002840-codex-ios-tp-v2-073-078-request-dirty-docs1.md
?? reviews/20260621-010108-codex-ios-tp-v2-073-078-request-dirty-cdr001.md
```

Diff stat:

```text
 docs/task-packages/v2/INDEX.md                     |  12 +
 .../AppIcon.appiconset/AppIcon-1024-dark.png       | Bin 149164 -> 89873 bytes
 .../AppIcon.appiconset/AppIcon-1024.png            | Bin 105382 -> 89873 bytes
 .../AppIcon.appiconset/AppIcon-20@2x.png           | Bin 3509 -> 2243 bytes
 .../AppIcon.appiconset/AppIcon-20@3x.png           | Bin 6004 -> 3703 bytes
 .../AppIcon.appiconset/AppIcon-29@2x.png           | Bin 5782 -> 3536 bytes
 .../AppIcon.appiconset/AppIcon-29@3x.png           | Bin 9562 -> 5709 bytes
 .../AppIcon.appiconset/AppIcon-40@2x.png           | Bin 8566 -> 5181 bytes
 .../AppIcon.appiconset/AppIcon-40@3x.png           | Bin 13803 -> 8211 bytes
 .../AppIcon.appiconset/AppIcon-60@2x.png           | Bin 13803 -> 8211 bytes
 .../AppIcon.appiconset/AppIcon-60@3x.png           | Bin 22099 -> 13069 bytes
 .../AIUsageMobileCore/AIUsageMobileRootView.swift  | 157 +++++++--
 .../Sources/AIUsageMobileCore/MobileSummary.swift  |  36 +++
 .../AIUsageMobileCore/MobileViewModel.swift        | 153 +++++++--
 .../MobileSummaryTests.swift                       | 119 +++++++
 packages/design-tokens/generate_ai_usage_icon.py   |  16 +-
 src/ai_usage_widget/mobile_summary.py              | 209 +++++++++++-
 src/ai_usage_widget/snapshot_builder.py            |  33 +-
 tests/test_ios_xcode_integration.py                | 110 +++++++
 tests/test_mobile_summary.py                       | 360 +++++++++++++++++++++
 tests/test_snapshot_builder.py                     |  54 ++++
 tests/test_web_server.py                           |   2 +-
 22 files changed, 1199 insertions(+), 62 deletions(-)
```

Recent verification already run by the implementation agent:

```text
cd mobile/ios && swift test
Result: 37 tests passed.

PYTHONPATH=src python3 -m unittest tests.test_mobile_summary tests.test_snapshot_builder.TestSnapshotBuilder.test_build_snapshot_includes_known_ai_accounts_without_hourly_facts tests.test_snapshot_builder.TestSnapshotBuilder.test_build_snapshot_includes_account_hourly_summary_without_changing_daily_total tests.test_web_server.TestWebServerSummary -v
Result: 31 tests passed.

PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration.IOSXcodeIntegrationTests.test_ios_app_icons_are_fully_opaque_square_artwork tests.test_ios_xcode_integration.IOSXcodeIntegrationTests.test_bottom_navigation_uses_liquid_glass_icon_treatment -v
Result: 2 tests passed.

git diff --check
Result: passed.

Production mobile summary smoke:
- Today returned 1 non-zero source.
- Week returned 6 non-zero sources.
- Month and All returned 10 non-zero sources.
- Claude and Codex quota windows returned account labels and plan labels.

Physical iPhone install:
- Guarded installer verified production `/api/mobile/summary?period=all`.
- Built app package verified production base URL and non-empty token without printing token.
- App installed and launched on the physical iPhone.
```

## Review Instructions

Return only actionable findings tied to the current uncommitted working tree.

Prioritize:

1. User-visible iPhone regressions in quota card layout, 5h reset behavior, source list behavior, navigation, or app icon assets.
2. Mobile API contract regressions that would make the iPhone display wrong data.
3. Account label safety issues, especially accidental exposure of tokens, auth paths, local OS usernames as AI account labels, or misleading plan labels.
4. Production safety risks introduced by changed server-side snapshot/mobile summary logic.
5. Missing or weak tests only when they cover a realistic user-visible failure.

For each finding, include severity, file/path, line evidence where possible, and user impact.

If there are no actionable findings, say that clearly and list residual risks or test gaps.

## Target Content

Inspect the working tree directly with read-only commands such as:

```bash
git diff -- docs/task-packages/v2/INDEX.md mobile/ios/Sources/AIUsageMobileCore/AIUsageMobileRootView.swift mobile/ios/Sources/AIUsageMobileCore/MobileSummary.swift mobile/ios/Sources/AIUsageMobileCore/MobileViewModel.swift mobile/ios/Tests/AIUsageMobileCoreTests/MobileSummaryTests.swift packages/design-tokens/generate_ai_usage_icon.py src/ai_usage_widget/mobile_summary.py src/ai_usage_widget/snapshot_builder.py tests/test_ios_xcode_integration.py tests/test_mobile_summary.py tests/test_snapshot_builder.py tests/test_web_server.py
git diff --name-only
find docs/task-packages/v2 -maxdepth 2 -name 'TP-V2-07*.md' -o -path 'docs/task-packages/v2/assets/*'
```

Also inspect untracked task-package docs and SVG assets under `docs/task-packages/v2/`.

Do not inspect or output secrets, `.env`, production token files, raw `~/.claude`, raw `~/.codex`, or private usage logs.

## Out Of Scope

- Historical whole-repo issues not introduced or made reachable by this diff.
- Cosmetic preferences without a clear iPhone user impact.
- Production credential values.
- Running deployment, install, staging, commit, or file modification commands.
