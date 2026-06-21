# TP-V2-075 iOS Claude 5h Quota Period Consistency

Version: V2
ID: TP-V2-075
Status: done
Type: implementation
Depends on: TP-V2-043, TP-V2-052
Parallel with: TP-V2-073, TP-V2-074

## Goal

Fix the iPhone App quota display bug where the Claude 5-hour quota ring is missing on Today but appears as the same 96% used ring on Week, Month, and All. Users should never see a stale or period-mismatched Claude 5h quota ring.

## Context

The user observed this on the physical iPhone App:

- Today view: Claude usage and quota section do not show the outer 5h ring.
- Week, Month, and All views: the outer Claude 5h ring appears and shows 96% used in all three views.
- This makes the quota section look inconsistent and misleading, because 5h is a rolling live quota window, not a week/month/all usage period.

Current code shape suggests the likely boundary:

- Server snapshot fetches `limit_windows` in `src/ai_usage_widget/snapshot_builder.py`.
- `build_mobile_summary()` in `src/ai_usage_widget/mobile_summary.py` passes `limits.windows` through to the mobile contract.
- The SwiftUI `QuotaRingsCard` in `mobile/ios/Sources/AIUsageMobileCore/AIUsageMobileRootView.swift` treats the short window as the outer ring and the weekly window as the inner ring.

Product rule for this task:

- Claude 5h quota is a current rolling quota.
- It must not be interpreted as Today/Week/Month/All usage.
- It can be shown across period tabs only when the server knows it is current and not expired.
- If it is expired or stale, it must be hidden consistently across Today, Week, Month, and All.
- If it is fresh, the App should make clear that it is the current 5h quota, not the selected usage period.

## Scope

- Fix the mobile quota window selection/freshness behavior for Claude 5h/session windows.
- Apply the same freshness rule to Today, Week, Month, and All mobile summary responses.
- Preserve different usage totals/trends for Today, Week, Month, and All.
- Preserve weekly Claude quota display when it is a valid current weekly quota.
- Update server/API tests and Swift/static tests so this bug cannot return.
- Verify the final user-facing App behavior on iPhone or simulator screenshots, with physical iPhone preferred.

## Out of Scope

- Do not change how Claude usage tokens are collected.
- Do not estimate official Claude quota from `ccusage daily`, `ccusage blocks`, or local history.
- Do not change Codex quota semantics unless shared helper behavior requires a clearly scoped freshness fix.
- Do not change AppIcon behavior; TP-V2-073 covers that.
- Do not change bottom navigation Liquid Glass styling; TP-V2-074 covers that.
- Do not modify production account files or commit secrets.
- Do not direct-read remote raw Claude/Codex log directories.

## Red Test

- Add a server/API test that inserts:
  - an expired Claude `session` or 5h window at 96% used;
  - a valid Claude `week` window;
  - mobile usage rows for Today/Week/Month/All.
- Request `/api/mobile/summary` for `period=today`, `period=week`, `period=month`, and `period=all`.
- Assert the expired Claude 5h/session window is absent from every period response.
- Assert usage totals still differ correctly by period.
- Assert the valid Claude weekly quota remains available where the quota section is shown.

Add the complementary fresh-window case:

- Insert a fresh Claude 5h/session window.
- Request the same four mobile periods.
- Assert the fresh 5h quota behavior is consistent across period tabs and clearly identified as current quota data.

Add Swift/static coverage:

- `QuotaRingsCard` or its helper must not infer an outer 5h ring from stale, missing, or failed provider rows.
- The visible label/copy must not imply that 5h is a week/month/all quota.

## Implementation

1. Locate where `limit_windows` are fetched and filtered for mobile summary responses.
2. Apply one freshness/expiry rule for short rolling quota windows across all mobile periods.
3. Keep selected-period usage aggregation unchanged.
4. Ensure mobile summary keeps enough metadata for the App to distinguish current rolling quota from selected usage period.
5. Update SwiftUI quota rendering only if the App currently needs better filtering or clearer copy.
6. Avoid fake fallback values: if Claude 5h is not fresh and observed, hide it instead of showing old 96%.

## Acceptance Criteria

- Today, Week, Month, and All no longer disagree on whether the stale Claude 5h quota exists.
- A stale or expired Claude 5h 96% ring does not appear in Week, Month, or All.
- If a fresh Claude 5h quota is available, the App shows it consistently and labels it as current 5h quota data.
- Today/Week/Month/All usage totals and trends still remain period-specific.
- The weekly Claude quota ring remains correct and is not removed as a side effect.
- The user can switch between Today, Week, Month, and All without seeing misleading quota jumps caused by stale 5h data.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_mobile_summary tests.test_web_server -v
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
cd mobile/ios && swift test
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination '<iPhone simulator or physical iPhone destination>' build
git diff --check
```

Visual check:

- Open the iPhone App.
- Switch Today, Week, Month, and All.
- Check Claude quota card.
- Pass only if stale 5h data is not visible and the current 5h quota behavior is consistent across the four period tabs.

## Handoff

- Report which layer changed: server mobile summary, snapshot limit filtering, SwiftUI rendering, or a combination.
- Report the exact test case that reproduces the old Today vs Week/Month/All inconsistency.
- Report screenshots or direct observations for Today, Week, Month, and All after the fix.
- State clearly whether the Claude 5h quota was hidden because it was stale or shown because it was fresh.

## Completion Notes

- Implemented on 2026-06-21.
- Expired short quota windows are filtered consistently across Today, Week, Month, and All.
- Production `/api/mobile/summary` no longer returns the stale Claude 5h `96%` window for current mobile periods.
- Verified locally and against production mobile summary API for all four periods.
