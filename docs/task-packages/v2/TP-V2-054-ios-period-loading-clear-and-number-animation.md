# TP-V2-054 iOS Period Loading Clear and Number Animation

Version: V2
ID: TP-V2-054
Status: done
Type: implementation
Depends on: TP-V2-052, TP-V2-053
Parallel with: none

## Goal

When the iOS App period selector changes, clear old period data immediately, then render the new live response with native numeric animation.

## Context

The simulator now reads production `/api/mobile/summary`. Tapping today / week / month / all currently highlights the new period while old summary numbers remain visible until the new request returns, causing a misleading flash.

## Scope

- Add a reusable empty mobile summary for a selected period.
- Update the live App container so loading state renders zeroed data for the newly selected period.
- Prevent older in-flight period requests from overwriting a newer selection.
- Add native iOS numeric text transition to summary numbers.

## Out of Scope

- Do not change production API schema.
- Do not install or push to the physical iPhone.
- Do not change credential storage.

## Red Test

- Add Swift package tests for `MobileSummary.empty(periodID:)`, proving selected period, totals, trend, sources, breakdown, and limits are zero/empty.

## Implementation

- Add `MobileSummary.empty(periodID:timezone:generatedAt:)` in mobile core.
- Use the empty summary in `LiveSummaryContainerView` when live config exists and when a new period request starts.
- Track the latest period request identity before applying async results.
- Use SwiftUI numeric text content transitions for total and metric values.

## Acceptance Criteria

- Tapping period selector immediately clears old numbers and trend rows.
- New response fills in real data after the request completes.
- Fast repeated period taps cannot apply stale older responses.
- Main total and Input / Output / Cache values animate when changing.

## Verification

```bash
cd mobile/ios && swift test
cd mobile/ios-xcode && xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'platform=iOS Simulator,name=iPhone 16 Pro' build
```

## Handoff

- Report changed files and verification commands.
- Include simulator-only validation evidence if run.

## Completion Notes

- Added `MobileSummary.empty(periodID:)` and a Swift package test for zeroed loading summary behavior.
- Updated the iOS App container to render a zeroed summary immediately on period selection, then apply the matching live response.
- Added request identity tracking so stale period responses cannot overwrite the newest selection.
- Added SwiftUI numeric text transitions to the hero total and Input / Output / Cache tiles.
- Installed and launched only on simulator `70729294-180A-4862-B2EA-56939BBB6277`; physical iPhone was not touched.
- Simulator screenshot: `tmp/ai-usage-simulator-period-clear-animation.png`.
