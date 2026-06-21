# TP-V2-068 iOS App High Fidelity And Icon

Version: V2
ID: TP-V2-068
Status: cancelled
Type: implementation
Depends on: none
Parallel with: none

## Goal

Bring the iOS App UI and icon into alignment with the latest design direction while preserving the existing live `MobileSummary` contract.

## Context

The App already has live `/api/mobile/summary` loading, period switching, and high-fidelity shell work. Current App Icon is known to be wrong.

Round 9 cancellation note: this old iOS high-fidelity direction is superseded by the completed TP-V2-073 to TP-V2-080 iOS delivery line.

## Scope

- Update `mobile/ios/Sources/AIUsageMobileCore/AIUsageMobileRootView.swift`.
- Update `mobile/ios/Sources/AIUsageMobileCore/MobileViewModel.swift` only for local display derivations.
- Update `mobile/ios-xcode/Resources/Assets.xcassets`.
- Update `tests/test_ios_xcode_integration.py` and Swift tests.

## Out of Scope

- Do not change `/api/mobile/summary` contract for this task.
- Do not commit production token, local xcconfig, or generated secrets.
- Do not install to physical iPhone unless using the guarded installer.

## Red Test

- Extend static tests to fail until the new App Icon asset and brand icon references exist.
- Extend Swift tests to prove existing `MobileSummary` still drives Home, Limits, Breakdown, and Sources.

## Implementation

1. Wire the new icon assets.
2. Align Home, Limits, Breakdown, and Sources visual treatment to the latest multi-platform design where compatible with existing iOS high-fidelity handoff.
3. Keep period switching live and service-timezone based.
4. Keep no-contract-change boundary.

## Acceptance Criteria

- iOS App icon uses the new dual-ring mark.
- Home and quota visuals match the design language.
- Period changes still request the selected period.
- No fixture values ship as production values.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration tests.test_mobile_prototype -v
cd mobile/ios && swift test
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'id=70729294-180A-4862-B2EA-56939BBB6277' build
git diff --check
```

## Handoff

- Attach simulator screenshots for Home, Limits, Breakdown, and Sources.
- State whether physical iPhone install was skipped or completed.
