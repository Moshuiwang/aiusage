# TP-V2-057 iOS Trend Chart Dot Polish

Version: V2
ID: TP-V2-057
Status: done
Type: implementation
Depends on: TP-V2-055
Parallel with: none

## Goal

Make the iOS home trend chart visually quieter by removing the repeated visible dots on every data point.

## Context

The current SwiftUI `UsageTrendChart` renders a visible circle for every trend bucket. On an iPhone-sized chart this creates a noisy and cheap-looking dotted line. The chart should behave like a common iOS analytic chart: line + subtle area by default, with a single indicator only while the user taps or drags.

## Scope

- Update `UsageTrendChart` visual rendering only.
- Preserve tap / drag selection and detail text.
- Add a regression check so the chart does not render a visible marker for every point again.

## Out of Scope

- Do not change API data or period semantics.
- Do not redesign the rest of Home.
- Do not install to physical iPhone.

## Red Test

- Add an integration assertion that `UsageTrendChart` has a single selected-point indicator and no per-point marker `ForEach`.

## Implementation

- Replace the per-point circle loop with a single `selectedPointIndicator`.
- Keep the full chart `DragGesture(minimumDistance: 0)` as the interaction surface.
- Clear the default selected point so the chart starts clean.

## Acceptance Criteria

- Trend chart no longer shows a circle on every point.
- Dragging / tapping the chart still reveals the selected bucket detail.
- Selected state uses one compact indicator instead of repeated point markers.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
cd mobile/ios && swift test
cd mobile/ios-xcode && xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'id=70729294-180A-4862-B2EA-56939BBB6277' build
```

## Handoff

- Report changed files, verification, and simulator screenshot if refreshed.

Completed. Simulator refreshed only; physical iPhone was not installed.

Simulator evidence:

- `tmp/ai-usage-simulator-home-trend-no-dots.png`
