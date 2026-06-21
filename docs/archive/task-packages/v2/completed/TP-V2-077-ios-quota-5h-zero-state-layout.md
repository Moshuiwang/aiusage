# TP-V2-077 iOS Quota 5h Zero State Layout

Version: V2
ID: TP-V2-077
Status: done
Type: implementation
Depends on: TP-V2-075
Parallel with: none

## Goal

Keep the Claude quota card visually balanced when 5h usage is 0%. The 5h row should still appear as `5h 0% 已重置` instead of disappearing and making the Claude card shorter than the Codex card.

## Context

The user observed the current iPhone App behavior:

- In Today, Claude has no usage.
- The Claude 5h quota is effectively reset to 0%.
- Because there is no next reset time, the App drops the 5h percentage and reset row.
- The Claude quota sub-card becomes shorter than the Codex sub-card, which makes the `已用额度` card look broken.

Current SwiftUI shape:

- `ProviderQuotaCard` draws an outer ring from `fiveHourWindow?.usedPercent ?? 0`.
- The 5h text row is only rendered inside `if let w = fiveHourWindow`.
- `remainingTimeText(resetAt:)` already returns `已重置` for expired reset times, but there is no row when the window is absent.

Product rule:

- If a provider has a quota card, the 5h row should have stable space.
- If the 5h value is known to be reset or zero, show `5h 0% 已重置`.
- If the 5h value is genuinely unknown, use a muted placeholder that keeps the same height without pretending to have quota data.
- Claude and Codex quota sub-cards should have matching height in the same row.

## Scope

- Update iOS quota card rendering for 5h zero/reset states.
- Preserve the distinction between observed `0%` and unknown/missing data.
- Keep the outer ring visible at 0% with the neutral track.
- Keep card heights aligned across Claude and Codex.
- Add Swift/static tests to prevent the 5h row from disappearing.

## Out of Scope

- Do not change server collection behavior.
- Do not estimate missing quota.
- Do not force a fake reset time when the backend does not know one.
- Do not change account label behavior; TP-V2-076 covers that.
- Do not change stale 96% filtering; TP-V2-075 covers that.

## Red Test

- Add Swift/static coverage proving the 5h row is rendered even when 5h used percent is 0.
- Add coverage for absent `reset_at` or already-reset `reset_at`, expecting user-facing `已重置`.
- Add coverage that unknown 5h data uses a non-misleading placeholder and keeps layout height.
- Add visual/static coverage that `ProviderQuotaCard` keeps consistent vertical structure for Claude and Codex.

## Implementation

1. Introduce a display state for 5h quota rows: observed, reset-zero, unknown.
2. Render the 5h row for reset-zero state as `5h 0% 已重置`.
3. Keep unknown state visually muted and non-misleading.
4. Reserve the same row height in every provider quota card.
5. Ensure 0% outer ring still displays the neutral track and does not collapse.
6. Keep the weekly/7d row unchanged.

## Acceptance Criteria

- Claude Today card with no 5h usage shows `5h 0% 已重置`.
- Claude and Codex quota sub-cards have matching height in the `已用额度` row.
- The 5h outer ring remains visible as a 0% state instead of disappearing.
- The UI does not show fake reset times.
- Unknown data is clearly different from observed 0%.
- The card looks balanced on the physical iPhone.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
cd mobile/ios && swift test
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination '<iPhone simulator or physical iPhone destination>' build
git diff --check
```

Visual check:

- Open Today in the iPhone App.
- Inspect the Claude and Codex quota sub-cards.
- Pass only if Claude shows a stable 5h row and the two sub-cards are the same visual height.

## Handoff

- Report the 5h display state used for Claude Today.
- Include screenshot or direct observation of the balanced quota card.
- State whether the result was verified on physical iPhone or simulator.

## Completion Notes

- Implemented on 2026-06-21.
- The quota card always keeps the 5h row so Claude and Codex cards remain balanced.
- When a 5h window is reset or unavailable, the UI keeps a stable row instead of collapsing the card.
- Verified with Swift view-model tests and mobile summary tests.
