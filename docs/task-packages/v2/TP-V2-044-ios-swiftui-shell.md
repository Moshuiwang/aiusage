# TP-V2-044 iOS SwiftUI Shell

Version: V2
ID: TP-V2-044
Status: done
Type: implementation
Depends on: TP-V2-043
Parallel with: none

## Goal

Create the first iPhone SwiftUI shell that decodes the mobile summary contract and renders the approved Home / Sources / Breakdown / Limits navigation structure.

## Context

The Web prototype has confirmed the information architecture. TP-V2-043 provides the DTO boundary that the native App should decode. The first SwiftUI slice should focus on structure, system appearance, and contract decoding rather than production networking polish.

## Scope

- Add a minimal iOS client workspace or Swift Package under a dedicated mobile directory.
- Define Swift DTOs for `/api/mobile/summary`.
- Add fixture decode tests using a checked-in non-sensitive mobile summary fixture.
- Render four tabs: Home, Sources, Breakdown, Limits.
- Use system light/dark appearance and standard SwiftUI controls/materials.

## Out of Scope

- No App Store signing.
- No production server credentials.
- No WidgetKit extension yet.
- No background push/collector logic in the App.
- No team/multi-tenant account system.

## Red Test

- Add a Swift test that decodes a fixture generated from `/api/mobile/summary`.
- Add a view-model test that maps period, trend, sources, breakdown, and limits into display-ready state.

## Implementation

- Keep the App read-only.
- Use semantic SwiftUI colors/materials and respect system dark/light mode.
- Keep the title only on Home; secondary tabs should avoid redundant top chrome.
- Map missing limits to explicit degraded states.

## Acceptance Criteria

- Swift tests pass locally.
- App shell builds without requiring real production credentials.
- Fixture contract matches TP-V2-043 output.

## Verification

```bash
cd mobile/ios
swift test
```

## Handoff

- Report generated project path, Swift tests, and any Xcode/manual run steps.
