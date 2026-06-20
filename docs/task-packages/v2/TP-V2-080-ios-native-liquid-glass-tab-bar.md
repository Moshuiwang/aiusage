# TP-V2-080 iOS Native Liquid Glass Tab Bar

Version: V2
ID: TP-V2-080
Status: done
Type: implementation
Depends on: TP-V2-074
Parallel with: TP-V2-079

## Goal

Replace the current custom frosted period switcher with a true native iOS Liquid Glass-style bottom navigation experience for Today / Week / Month / All.

## Context

The current iPhone bottom period switcher is visually glass-like, but it is not the same experience as Apple's latest Liquid Glass tab and toolbar patterns:

- `PeriodTabBar` is a custom `HStack` over `.regularMaterial` inside a `Capsule`.
- `LiquidGlassTabButton` and `LiquidGlassSelectionSurface` add material, gradient, border, and shadow to approximate glass.
- The whole control is manually overlaid in a `ZStack(alignment: .bottom)`.
- It does not use a native `TabView`, system tab bar minimize behavior, or system search/toolbar integration.

The visible problem for users: the control has improved polish, but it still reads as a custom floating pill instead of the system Liquid Glass layer seen in Mail, App Store, Phone, TV, and other Apple apps.

Apple's current guidance points to these product-level behaviors:

- Navigation and actions should live in a floating UI layer above content.
- Tab bars should let content remain the star and can minimize on scroll on iPhone.
- Search or primary bottom actions should use system toolbar/tab patterns so keyboard and focus transitions feel native.
- Brand color should move into the content layer; the tab/navigation layer should stay familiar, legible, and restrained.
- Use standard SwiftUI/UIKit components where available; custom Liquid Glass should be reserved for truly app-specific controls.

References:

- Apple Human Interface Guidelines, Tab bars: https://developer.apple.com/design/human-interface-guidelines/tab-bars
- Apple Human Interface Guidelines, Materials: https://developer.apple.com/design/human-interface-guidelines/materials
- Apple Adopting Liquid Glass: https://developer.apple.com/documentation/TechnologyOverviews/adopting-liquid-glass
- Apple WWDC25, Build a SwiftUI app with the new design: https://developer.apple.com/videos/play/wwdc2025/323/
- Apple WWDC26, Design intuitive search experiences: https://developer.apple.com/videos/play/wwdc2026/292/
- Apple WWDC26, Communicate your brand identity on iOS: https://developer.apple.com/videos/play/wwdc2026/251/

## Scope

- Update the iOS app bottom period navigation only.
- Preserve the four existing period destinations: Today, Week, Month, All.
- Preserve existing period data behavior: selecting a period still requests and displays the corresponding live `MobileSummary`.
- Replace or substantially restructure the current custom `PeriodTabBar` overlay if native `TabView` / tab APIs can provide the right experience.
- Use native iOS 26 / iOS 27 Liquid Glass APIs when the local Xcode and deployment target support them.
- If native Liquid Glass APIs are unavailable, implement the closest native SwiftUI fallback and report the gap clearly.
- Add tests that prevent the UI from silently staying as a custom `.regularMaterial` capsule while being labeled "Liquid Glass".
- Verify behavior in simulator and, when available, on the physical iPhone.

## Out of Scope

- Do not change `/api/mobile/summary`, quota math, source aggregation, trend charts, or account labels.
- Do not redesign cards, charts, source rows, quota cards, AppIcon, Widget, Watch, macOS, Web, or server.
- Do not add a new search feature unless it is strictly required to adopt the native tab/toolbar structure.
- Do not fake Liquid Glass by adding heavier CSS-like blur, decorative gradients, or more shadows to the existing custom pill.
- Do not submit to App Store or TestFlight as part of this task.
- Do not commit tokens, local `.xcconfig`, screenshots with secrets, or generated private data.

## Red Test

- Add or update iOS integration tests so they fail while the bottom period navigation remains only a custom material capsule:
  - detect and fail on `.background(.regularMaterial, in: Capsule())` as the primary period navigation surface;
  - detect and fail on the root view relying on `ZStack(alignment: .bottom)` plus a manually overlaid `PeriodTabBar` as the final navigation approach, unless the implementation documents why native APIs are unavailable;
  - require a native period navigation component name such as `NativeLiquidGlassPeriodTabs`, `PeriodTabView`, or equivalent;
  - require a capability/fallback marker that states whether native Liquid Glass tab APIs are active or a SwiftUI material fallback is being used.
- Keep existing tests that protect:
  - Today / Week / Month / All order;
  - period selection behavior;
  - gauge-style quota icon;
  - no regression to a flat blue selected pill.

## Implementation

1. Read `AIUsageMobileRootView`, `PeriodTab`, `PeriodTabBar`, `LiquidGlassTabButton`, and `LiquidGlassSelectionSurface`.
2. Check the local Xcode SDK and deployment target before choosing implementation:
   - if SwiftUI `TabView`, `Tab`, `tabBarMinimizeBehavior`, `tabViewBottomAccessory`, `glassEffect`, or related APIs are available, prefer them;
   - if they are not available, keep the fallback honest and avoid naming it as true native Liquid Glass.
3. Choose the product structure:
   - preferred: make Today / Week / Month / All real native tabs or a native tab-backed period navigation layer;
   - fallback: keep a custom period switcher only if native tab structure would break the current single-screen data model, and document the gap.
4. Move content so it visually extends behind the bottom navigation layer without hiding important metrics.
5. Add scroll-aware behavior where supported:
   - bottom navigation should minimize, recede, or become less intrusive while the user scrolls through data;
   - it should return clearly when the user reverses direction or needs to switch periods.
6. Keep selected state readable but restrained:
   - no heavy brand-color fill;
   - no decorative color-only glass;
   - selected period should feel like part of the same floating system layer.
7. Ensure Dynamic Type, dark mode, and small iPhone widths remain readable.
8. Run targeted tests, Swift tests, and visual checks.

## Acceptance Criteria

- The bottom period navigation no longer reads as a custom frosted capsule.
- The experience feels like a native iOS Liquid Glass navigation layer floating over content.
- Today / Week / Month / All remain one-tap reachable and keep their current data behavior.
- Content remains visually primary; navigation does not feel like a heavy card or permanent footer.
- Scrolling through dense usage content gives more room to content, either through native minimization or a documented fallback behavior.
- Selected and unselected states are legible in light and dark mode.
- There is no text overlap, clipped tab label, or harsh color flash when switching periods.
- Tests explicitly distinguish true native Liquid Glass adoption from a material-only approximation.
- The handoff states plainly whether the final result is native Liquid Glass or the closest supported fallback.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
cd mobile/ios && swift test
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination '<iPhone simulator or physical iPhone destination>' build
git diff --check
```

Visual check:

- Capture screenshots for Today, Week, Month, and All with the bottom navigation visible.
- Scroll each period screen and confirm the bottom navigation does not dominate the content.
- Tap through all four period destinations and confirm the transition feels native and stable.
- Check light mode and dark mode.
- Install or run on the physical iPhone when available.
- Pass only if the user-facing result is materially closer to Apple's Mail/App Store-style Liquid Glass navigation than the previous custom frosted capsule.

## Handoff

- Report the changed SwiftUI files and test files.
- State whether native iOS Liquid Glass APIs were used.
- If a fallback was used, state exactly what is missing from the native Apple behavior.
- Provide simulator screenshots for all four period states.
- State whether physical iPhone verification was completed.
- Explain in product language whether the bottom navigation now feels like real Liquid Glass or still a fallback.

## Completion Notes

- Implemented on 2026-06-21.
- The bottom period switcher no longer uses the custom `.regularMaterial` capsule overlay.
- `AIUsageMobileRootView` now uses a native SwiftUI `TabView(selection:)` through `NativeLiquidGlassPeriodTabs`.
- On iOS 26+, the app opts into `tabBarMinimizeBehavior(.onScrollDown)` so the system tab bar can recede while scrolling.
- On iOS 17-25, the fallback is still native `TabView`, but without the iOS 26 Liquid Glass minimization API.
- Verified with targeted iOS static tests, Swift package tests, unsigned iPhoneOS build, and guarded physical iPhone install.
