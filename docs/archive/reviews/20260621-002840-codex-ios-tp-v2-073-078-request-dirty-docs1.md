# AI Review Request

## Scope

Target: plan/task packages for implementing TP-V2-073 through TP-V2-078 in `/Users/wangzhipeng/Documents/ai-usage-widget`.

Branch: `codex/ios-tp-v2-073-078`

Mode: local Claude read-only review

Selected depth: deep / high cost (`claude --model opus --effort xhigh`)

Selected reviewer: Claude Code

## Repo State

Current changed docs:

- `docs/task-packages/v2/INDEX.md`
- `docs/task-packages/v2/TP-V2-073-ios-app-icon-opaque-exit-animation.md`
- `docs/task-packages/v2/TP-V2-074-ios-navigation-liquid-glass-icons.md`
- `docs/task-packages/v2/TP-V2-075-ios-claude-5h-quota-period-consistency.md`
- `docs/task-packages/v2/TP-V2-076-ios-quota-card-account-label.md`
- `docs/task-packages/v2/TP-V2-077-ios-quota-5h-zero-state-layout.md`
- `docs/task-packages/v2/TP-V2-078-ios-sources-current-period-and-updated-date.md`
- `docs/task-packages/v2/assets/TP-V2-076-ios-quota-card-account-label.svg`

No implementation has been started for this review round.

## Review Instructions

Read-only review. Do not modify files. Do not read or output tokens, `.env`, auth files, raw Claude/Codex logs, or private account data.

Review only whether the task packages are sufficient, coherent, and executable for this goal:

- fix iOS AppIcon exit animation artifact;
- improve bottom navigation Liquid Glass icon treatment;
- fix Claude 5h quota stale/period inconsistency;
- show AI account label and plan label on quota cards;
- keep 5h zero/reset layout stable;
- make iOS Sources card show all and only non-zero contributors for each selected period;
- make source update times include date context;
- build, verify, and install to iPhone.

Return only scoped findings with severity, path, evidence, and user impact. If there are no actionable findings, say no actionable findings and list residual test gaps.

## Target Files

Please inspect these task-package files directly:

- `docs/task-packages/README.md`
- `docs/task-packages/RULES.md`
- `docs/task-packages/v2/INDEX.md`
- `docs/task-packages/v2/TP-V2-073-ios-app-icon-opaque-exit-animation.md`
- `docs/task-packages/v2/TP-V2-074-ios-navigation-liquid-glass-icons.md`
- `docs/task-packages/v2/TP-V2-075-ios-claude-5h-quota-period-consistency.md`
- `docs/task-packages/v2/TP-V2-076-ios-quota-card-account-label.md`
- `docs/task-packages/v2/TP-V2-077-ios-quota-5h-zero-state-layout.md`
- `docs/task-packages/v2/TP-V2-078-ios-sources-current-period-and-updated-date.md`

Useful implementation context, if needed:

- `src/ai_usage_widget/mobile_summary.py`
- `src/ai_usage_widget/snapshot_builder.py`
- `mobile/ios/Sources/AIUsageMobileCore/MobileSummary.swift`
- `mobile/ios/Sources/AIUsageMobileCore/MobileViewModel.swift`
- `mobile/ios/Sources/AIUsageMobileCore/AIUsageMobileRootView.swift`
- `tests/test_mobile_summary.py`
- `tests/test_ios_xcode_integration.py`
- `mobile/ios/Tests/AIUsageMobileCoreTests/MobileSummaryTests.swift`

## Out Of Scope

- Whole-repo historical cleanup.
- Production deploy.
- Reading secrets, tokens, auth files, raw usage logs, or private config files.
- Recommending changes outside TP-V2-073 through TP-V2-078 unless they block execution.
