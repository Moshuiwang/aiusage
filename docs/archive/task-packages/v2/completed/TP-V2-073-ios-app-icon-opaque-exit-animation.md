# TP-V2-073 iOS App Icon Opaque Exit Animation

Version: V2
ID: TP-V2-073
Status: done
Type: implementation
Depends on: TP-V2-048, TP-V2-065
Parallel with: none

## Goal

Make the iPhone App icon behave like standard iOS apps during the home gesture exit animation: when the user swipes up and the app shrinks back into the home-screen icon, the icon must not flash a white backing, transparent corner, or pre-rounded mask artifact.

## Context

The current iOS App icon is visible on device, but the user observed a very short white-backed artifact during the swipe-up exit animation. Local inspection of `mobile/ios-xcode/Resources/Assets.xcassets/AppIcon.appiconset` shows the current PNG icons include transparent corners and pre-rounded artwork. That is not the desired iOS delivery model for this app.

Apple guidance points in the same direction:

- For iOS app icons, provide square artwork and let the system apply the rounded mask.
- Icon images should not include transparent regions.
- Do not bake a rounded-corner container into the iOS AppIcon PNGs.

References:

- Apple Human Interface Guidelines, App icons: https://developer.apple.com/design/human-interface-guidelines/app-icons
- Apple Technical Q&A QA1686, App Icons on iPhone, iPad and Apple Watch: https://developer.apple.com/library/archive/qa/qa1686/_index.html
- Apple WWDC25, Create icons with Icon Composer: https://developer.apple.com/videos/play/wwdc2025/361/

## Scope

- Update only iOS AppIcon generation and iOS AppIcon assets.
- Keep the dual-ring AI Usage brand mark.
- Generate every required iPhone AppIcon PNG as a fully opaque square image.
- Include every PNG referenced by the AppIcon asset set, including dark-appearance marketing artwork.
- Use a full-canvas background so no transparent edge or corner can appear during iOS launch, app switcher, or home gesture transitions.
- Add static tests that fail if any iOS AppIcon PNG has transparent or semi-transparent pixels.
- Add a handoff step requiring physical iPhone verification of the swipe-up exit animation.

## Out of Scope

- Do not redesign the iOS app screens.
- Do not change `/api/mobile/summary`, source data, quota math, or mobile networking.
- Do not change bundle identifier, signing ownership, entitlements, or production token handling.
- Do not modify macOS menu bar icons unless a later task explicitly splits that work.
- Do not treat simulator-only screenshots as final acceptance for this issue.

## Red Test

- Extend `tests/test_ios_xcode_integration.py` to fail until every PNG in `mobile/ios-xcode/Resources/Assets.xcassets/AppIcon.appiconset` is fully opaque.
- The test must glob every `*.png` in the appiconset, including `AppIcon-1024-dark.png`, and check at least:
  - `AppIcon-20@2x.png`
  - `AppIcon-20@3x.png`
  - `AppIcon-29@2x.png`
  - `AppIcon-29@3x.png`
  - `AppIcon-40@2x.png`
  - `AppIcon-40@3x.png`
  - `AppIcon-60@2x.png`
  - `AppIcon-60@3x.png`
  - `AppIcon-1024.png`
  - `AppIcon-1024-dark.png`
- The failure message should be product-readable: the icon must not have transparent corners because it can show a backing color during iOS system animations.

## Implementation

1. Update the icon generation path so iOS AppIcon PNGs render to a full square canvas with no alpha transparency.
2. Keep the brand mark centered and visually consistent with the current dual-ring design.
3. Remove pre-rounded transparent corners from generated iOS AppIcon PNGs.
4. Regenerate the AppIcon PNG set.
5. Keep `Contents.json` wired to `AppIcon` and preserve required iPhone icon sizes.
6. Build and install the app on the physical iPhone through the existing guarded signing/install flow.

## Acceptance Criteria

- The home-screen icon looks visually polished and consistent with the AI Usage brand.
- No iOS AppIcon PNG has transparent or semi-transparent pixels.
- The icon background fills the whole square canvas.
- iOS still applies its native rounded icon shape.
- On the physical iPhone, swiping up to exit the app shows the app shrinking cleanly into the icon with no visible white flash, transparent corner, or backing rectangle.
- App switcher and home-screen appearances remain visually consistent.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
cd mobile/ios-xcode && xcodegen generate
cd mobile/ios-xcode && xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination '<physical iPhone destination>' -allowProvisioningUpdates build
xcrun devicectl device install app --device '<physical iPhone id>' '<built app path>'
git diff --check
```

Manual iPhone check:

- Open AI Usage from the home screen.
- Swipe up to exit.
- Watch the shrink-to-icon animation.
- Repeat at least three times.
- Pass only if the icon animation has no white backing flash and no visible transparent-corner artifact.

## Handoff

- Report the changed AppIcon generation file and regenerated AppIcon PNG files.
- Report the static opacity test result.
- Report the physical iPhone install result.
- Report the manual swipe-up exit animation result in user-facing language.
- If the artifact remains after opaque AppIcon generation, stop and report it as a deeper iOS transition/rendering issue before expanding scope.

## Completion Notes

- Implemented on 2026-06-21.
- iOS AppIcon PNGs are regenerated as fully opaque square artwork, including dark marketing artwork.
- Verified with the targeted AppIcon opacity test and `git diff --check`.
- Built, installed, and launched the production-configured App on the physical iPhone through the guarded installer.
