# TP-V2-048 iOS App Icon Asset

Version: V2
ID: TP-V2-048
Status: done
Type: implementation
Depends on: TP-V2-046
Parallel with: none

## Goal

Give the physical iPhone build a real, polished app icon that matches the AI Usage mobile app tone.

## Context

The first signed device install works, but the iOS home-screen icon is blank because the Xcode project has no AppIcon asset catalog wired into the app target.

## Scope

- Add an iOS `AppIcon.appiconset` under the Xcode project's resources.
- Generate a production-shaped icon image and required app icon sizes.
- Wire the app target to `ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon`.
- Keep Widget extension behavior unchanged.

## Out of Scope

- Do not redesign the app screens.
- Do not add live data networking.
- Do not change bundle identifiers or signing ownership.

## Red Test

- Add an iOS Xcode integration test that fails until the AppIcon asset catalog exists and is referenced by `project.yml`.

## Implementation

- Create `Resources/Assets.xcassets/AppIcon.appiconset`.
- Generate 1024px and required iPhone app icon PNGs.
- Include the asset catalog in the app target resources.
- Regenerate the Xcode project with XcodeGen.

## Acceptance Criteria

- `project.yml` points the app target at `AppIcon`.
- The generated `AppIcon.appiconset` contains a valid 1024x1024 PNG.
- The project builds for the connected iPhone with signing.
- The app installs on device.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
cd mobile/ios-xcode && xcodegen generate
cd mobile/ios-xcode && xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'id=EEA2E255-8C7E-50FB-A951-A9DE9B7E26C6' -allowProvisioningUpdates build
xcrun devicectl device install app --device EEA2E255-8C7E-50FB-A951-A9DE9B7E26C6 <built app path>
```

## Handoff

- Generated icon asset root: `/Users/wangzhipeng/Documents/ai-usage-widget/mobile/ios-xcode/Resources/Assets.xcassets/AppIcon.appiconset`.
- Primary icon: `AppIcon-1024.png`, plus iPhone 20/29/40/60 pt scaled PNGs.
- Build result: signed iPhone build succeeded with `--app-icon AppIcon`.
- Install result: `devicectl device install app` succeeded for `com.wangzhipeng.aiusage.mobile`.
- Launch caveat: final automatic launch was denied because the iPhone was locked; unlock the phone and open `AI Usage` manually if needed.
