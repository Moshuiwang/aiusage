# TP-V2-058 iOS Trend Tooltip Overlay

Version: V2
ID: TP-V2-058
Status: done
Type: implementation
Depends on: TP-V2-055, TP-V2-057
Parallel with: none

## Goal

Fix the iOS home trend chart tooltip so it displays as a normal in-chart tooltip during touch and drag.

## Context

After the trend chart dot polish, the details are still rendered as a separate text strip below the chart. On device this does not behave like a normal chart tooltip, and the gesture can feel unreliable inside the Home scroll view.

## Scope

- Update `UsageTrendChart` tooltip rendering.
- Keep the quiet line + area chart without repeated point dots.
- Show selected bucket details in a compact in-chart tooltip bubble.
- Keep the selected vertical rule and single point indicator.
- Improve touch / drag reliability inside the scroll view.

## Out of Scope

- Do not change API data.
- Do not redesign the Home page outside the trend chart.
- Do not install to physical iPhone unless explicitly requested.

## Red Test

- Integration test asserts the chart includes `TrendTooltipBubble` and a clamped tooltip x-position helper.
- Integration test asserts the old below-chart `trendDetailText` strip is removed.

## Implementation

- Add a `TrendTooltipBubble` view.
- Position it inside the chart and clamp it within chart bounds.
- Use high-priority local drag gesture for selection.

## Acceptance Criteria

- Touching or dragging the chart shows one in-chart tooltip.
- Tooltip includes bucket label, Input, Output, Cache, and cache ratio.
- The chart still has no repeated point markers.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
cd mobile/ios && swift test
cd mobile/ios-xcode && xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'id=70729294-180A-4862-B2EA-56939BBB6277' build
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Simulator screenshot:

- `tmp/ai-usage-simulator-home-tooltip-click-1555-610.png`

## Handoff

- Report changed files, verification, and simulator screenshot if refreshed.
