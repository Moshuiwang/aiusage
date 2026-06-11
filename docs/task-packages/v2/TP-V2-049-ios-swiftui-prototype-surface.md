# TP-V2-049 iOS SwiftUI Prototype Surface

Version: V2
ID: TP-V2-049
Status: done
Type: implementation
Depends on: TP-V2-044, TP-V2-046
Parallel with: none

## Goal

Make the installed SwiftUI app pages visually match the approved mobile prototype structure instead of the current placeholder List screens.

## Context

The first physical install uses the SwiftUI shell from TP-V2-044, but the app interior is still a basic system `List` implementation and does not match the approved high-fidelity mobile prototype.

## Scope

- Update `AIUsageMobileRootView.swift` page structure and styling.
- Keep all data read-only from the existing `MobileSummary` fixture/model.
- Add period selector, home summary cards, trend chart, limit preview, sources, breakdown, and limits pages using SwiftUI.
- Keep App install/manual push out of this task.

## Out of Scope

- Do not install to the iPhone without explicit user instruction.
- Do not add live API networking or credentials.
- Do not redesign the approved information architecture.
- Do not change bundle identifiers or signing.

## Red Test

- Add static integration tests asserting the SwiftUI surface contains the approved prototype components and no longer uses top-level placeholder `List` screens.

## Implementation

- Replace placeholder List pages with custom SwiftUI card/section components.
- Use system colors/materials so light/dark mode follows iOS.
- Keep Home as the only tab with the large `AI Usage` title.
- Make secondary tabs content-first, without duplicated top title bars.

## Acceptance Criteria

- SwiftUI surface exposes `PeriodSelector`, `UsageTrendChart`, `MetricTile`, `LimitReminderRow`, and unified `查看明细` links.
- Home contains trend, limit preview, source health, and top sources sections.
- Sources, Breakdown, and Limits no longer have separate navigation title bars.
- Swift tests and iPhoneOS build pass.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
cd mobile/ios && swift test
cd mobile/ios-xcode && xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build
```

## Handoff

- SwiftUI pages were changed from placeholder `List` screens to prototype-shaped card sections.
- Verification passed:
  - `PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v`
  - `cd mobile/ios && swift test`
  - `cd mobile/ios-xcode && xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build`
- The app was not installed to the phone because the user explicitly asked not to push without further instruction.
