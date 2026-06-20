# TP-V2-074 iOS Navigation Liquid Glass Icons

Version: V2
ID: TP-V2-074
Status: done
Type: implementation
Depends on: TP-V2-062, TP-V2-068
Parallel with: TP-V2-073

## Goal

Make the iPhone App navigation icons feel like real Liquid Glass controls, not flat SF Symbol buttons sitting on a frosted capsule. The bottom navigation should read as a native iOS 26-style floating navigation layer with light, depth, refraction, and responsive selected states.

## Context

The user observed that the current navigation icons still do not look like Liquid Glass. Local inspection shows the app uses a custom bottom navigation surface in `mobile/ios/Sources/AIUsageMobileCore/AIUsageMobileRootView.swift`:

- `PeriodTabBar` uses `.background(.regularMaterial, in: Capsule())`.
- `FloatingTabButton` renders each icon with `Image(systemName: tab.systemImage)`.
- The selected item uses `Capsule().fill(Color.blue)` and white foreground, which reads as a flat blue selected pill rather than a glass control.

This task covers the visible navigation icon treatment, not the home-screen AppIcon.

Apple guidance points toward treating navigation and controls as a distinct Liquid Glass layer:

- Liquid Glass is intended for controls and navigation elements.
- Tab bars on iPhone float above content in the new design.
- Toolbar and navigation items sit on Liquid Glass surfaces that adapt to what is underneath.
- Symbols and text on Liquid Glass can use color, but the control should still preserve glass depth and legibility.

References:

- Apple Human Interface Guidelines, Materials: https://developer.apple.com/design/human-interface-guidelines/materials
- Apple Human Interface Guidelines, Tab bars: https://developer.apple.com/design/human-interface-guidelines/tab-bars
- Apple Human Interface Guidelines, Toolbars: https://developer.apple.com/design/human-interface-guidelines/toolbars
- Apple WWDC25, Meet Liquid Glass: https://developer.apple.com/videos/play/wwdc2025/219/
- Apple WWDC25, Build a SwiftUI app with the new design: https://developer.apple.com/videos/play/wwdc2025/323/
- Apple WWDC25, What is new in SwiftUI: https://developer.apple.com/videos/play/wwdc2025/256/

## Scope

- Update the bottom navigation visual treatment in `AIUsageMobileRootView.swift`.
- Preserve the four existing sections: Home, Limits, Breakdown, Sources.
- Preserve the current navigation behavior and selected tab state.
- Make selected and unselected icons visually part of a Liquid Glass navigation layer.
- Use native Liquid Glass APIs where the deployed Xcode/iOS target supports them; otherwise use the closest native SwiftUI material treatment without faking a heavy web-glass effect.
- Add static tests that prevent the selected navigation item from regressing to a flat blue pill.
- Add simulator and physical iPhone visual verification focused on the bottom navigation icons.

## Out of Scope

- Do not change `/api/mobile/summary`, period switching, quota math, source data, or breakdown behavior.
- Do not change the home-screen AppIcon; that is covered by TP-V2-073.
- Do not redesign every card or screen in this task.
- Do not replace real app navigation with fixture-only prototype UI.
- Do not add production token, local `.xcconfig`, screenshots containing secrets, or generated private files.
- Do not require App Store submission or TestFlight for this visual fix.

## Red Test

- Extend `tests/test_ios_xcode_integration.py` to fail until the iOS navigation treatment exposes a dedicated glass navigation icon/control component.
- The test should cover:
  - `PeriodTabBar` or its replacement still exists.
  - A named component such as `LiquidGlassTabButton`, `LiquidGlassNavigationIcon`, or equivalent exists.
  - The selected navigation state no longer relies on `Capsule().fill(Color.blue)` as its primary visual treatment.
  - The navigation bar still contains Home / Limits / Breakdown / Sources in that order.
  - The quota/limits tab keeps a gauge-style icon and does not regress to bottle/drop imagery.

## Implementation

1. Read the current `PeriodTabBar` and `FloatingTabButton` implementation.
2. Replace the flat selected icon pill with a glass-forward selected state that has depth, edge highlight, adaptive tint, and readable icon contrast.
3. Keep the bottom navigation floating above content and visually separated without becoming a heavy card.
4. Keep icon hit targets comfortable for thumb use.
5. Ensure selected tab text and icons do not jump or overlap during transitions.
6. Keep the visual result coherent in light mode and dark mode.

## Acceptance Criteria

- The bottom navigation looks like a native floating Liquid Glass navigation layer.
- Selected icons no longer look like flat white symbols on a blue capsule.
- Unselected icons remain readable and feel embedded in the same glass surface.
- Switching tabs feels polished: no layout jump, clipped text, or harsh color flash.
- Home / Limits / Breakdown / Sources remain ordered and usable.
- The bottom navigation does not cover important content on iPhone-sized screens.
- The result is acceptable on a physical iPhone, not only in a simulator screenshot.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
cd mobile/ios && swift test
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination '<iPhone simulator or physical iPhone destination>' build
git diff --check
```

Visual check:

- Capture simulator screenshots for Home, Limits, Breakdown, and Sources with the bottom navigation visible.
- Install or run on a physical iPhone when available.
- Tap through all four navigation icons.
- Pass only if the selected and unselected states both read as Liquid Glass controls rather than flat colored pills.

## Handoff

- Report the changed SwiftUI file and test file.
- Attach or reference screenshots for all four navigation states.
- State whether physical iPhone verification was completed.
- In user-facing language, describe whether the navigation icons now have the expected Liquid Glass feel.
- If Liquid Glass APIs are unavailable for the deployment target, report that explicitly and document the closest visual fallback used.

## Completion Notes

- Implemented on 2026-06-21.
- Bottom navigation uses a translucent selection surface and icon-first treatment instead of a solid filled capsule.
- Verified with the targeted navigation static test, full Swift package tests, and physical iPhone install.
