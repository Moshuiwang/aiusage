# TP-V2-050 iOS SwiftUI Interactions And Appearance

Version: V2
ID: TP-V2-050
Status: done
Type: implementation
Depends on: TP-V2-049
Parallel with: none

## Goal

Make the simulator SwiftUI app behave like the approved prototype instead of only matching the static page structure.

## Context

TP-V2-049 replaced placeholder `List` screens with prototype-shaped SwiftUI pages. The remaining gap is native interaction and appearance validation: period selection should be stateful, trend points should expose token details, detail links should carry the selected period, and simulator screenshots should cover light and dark appearance.

## Scope

- Update `AIUsageMobileRootView.swift` interaction state and visual details.
- Keep data read-only from the existing `MobileSummary` fixture/model.
- Add simulator-only tab launch support where useful for screenshots.
- Add static integration tests for the new native interaction structure.

## Out of Scope

- Do not install to the iPhone without explicit user instruction.
- Do not add live API networking or credentials.
- Do not change bundle identifiers or signing.
- Do not change the mobile summary server contract in this task.

## Red Test

- Extend `tests/test_ios_xcode_integration.py` to assert:
  - `PeriodSelector` is stateful and accepts selection callbacks.
  - `UsageTrendChart` exposes selected point detail text with input/output/cache/cache ratio.
  - Home detail links can route to Breakdown with the selected period.
  - The simulator app can launch with an initial tab for visual verification.

## Implementation

- Add selected period state in the root view.
- Let Home and Breakdown period selectors update the shared period state.
- Show trend-point details when a point is tapped.
- Keep Home as the only tab with the large `AI Usage` title.
- Use iOS system materials/colors and verify both light and dark simulator appearances.

## Acceptance Criteria

- Period selector changes are reflected across Home and Breakdown.
- Trend chart detail text includes bucket label, input, output, cache, and cache ratio.
- `查看明细` from Home opens Breakdown with the current period selection.
- Sources, Breakdown, and Limits stay content-first without duplicated top title bars.
- Light and dark simulator screenshots render nonblank pages.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
cd mobile/ios && swift test
cd mobile/ios-xcode && xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'id=70729294-180A-4862-B2EA-56939BBB6277' build
```

## Handoff

- SwiftUI root now owns shared `selectedPeriodID` state, and Home / Breakdown period selectors update the same selection.
- Home trend chart now exposes a selected point detail chip with bucket label, input, output, cache, and cache ratio.
- Home `查看明细` routes to Breakdown while preserving the selected period state.
- Breakdown rows now set `selectedRow` and render a `BreakdownDetailCard`; Date dimension detail title is `日期明细`.
- Simulator-only `AI_USAGE_INITIAL_TAB` launch support remains available for visual screenshots.
- Verification passed:
  - `PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v`
  - `cd mobile/ios && swift test`
  - `cd mobile/ios-xcode && xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'id=70729294-180A-4862-B2EA-56939BBB6277' build`
- Simulator screenshots captured:
  - `/Users/wangzhipeng/Documents/ai-usage-widget/tmp/ai-usage-simulator-home-light-v5.png`
  - `/Users/wangzhipeng/Documents/ai-usage-widget/tmp/ai-usage-simulator-home-dark-v5.png`
  - `/Users/wangzhipeng/Documents/ai-usage-widget/tmp/ai-usage-simulator-breakdown-dark-v5.png`
  - `/Users/wangzhipeng/Documents/ai-usage-widget/tmp/ai-usage-simulator-breakdown-light-v6.png`
- The app was installed only to the simulator. It was not pushed to the physical iPhone.
