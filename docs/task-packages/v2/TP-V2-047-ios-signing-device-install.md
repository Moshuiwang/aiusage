# TP-V2-047 iOS Signing Device Install

Version: V2
ID: TP-V2-047
Status: done
Type: implementation
Depends on: TP-V2-046
Parallel with: none

## Goal

Build a signed Debug app and install `AI Usage` on the paired iPhone.

## Context

TP-V2-046 created the Xcode project and verified the iPhoneOS build without code signing. The connected device is available, paired, and has Developer Mode enabled. The signing block was resolved by using the Personal Team available in Xcode.

## Scope

- Use `mobile/ios-xcode/AIUsageMobile.xcodeproj`.
- Build `AIUsageMobileApp` for the paired iPhone.
- Install the signed `.app` with `xcrun devicectl`.
- Launch the app if install succeeds.

## Out of Scope

- No production credentials.
- No App Store distribution.
- No collector or provider runtime inside iOS.

## Resolved Blocking Condition

Xcode initially had no usable Apple account/profile state for physical-device signing:

- `No Account for Team "HL6QDFKUFC"`.
- No iOS App Development provisioning profiles for:
  - `com.wangzhipeng.aiusage.mobile`
  - `com.wangzhipeng.aiusage.mobile.widget`
- `~/Library/MobileDevice/Provisioning Profiles` is empty.

Resolution:

- Xcode Apple Accounts showed a usable Personal Team.
- `project.yml` now uses `DEVELOPMENT_TEAM: FR6A4PZ6DS`, matching the Personal Team used by Xcode for provisioning.
- Xcode created/downloaded iOS Team Provisioning Profiles for the app and widget bundle IDs.

## Red Test

- Signed physical-device build initially failed:

```bash
cd mobile/ios-xcode
xcodebuild -project AIUsageMobile.xcodeproj \
  -scheme AIUsageMobileApp \
  -configuration Debug \
  -destination 'id=EEA2E255-8C7E-50FB-A951-A9DE9B7E26C6' \
  -allowProvisioningUpdates \
  build
```

## Implementation

- Sign in to Xcode with an Apple Developer account that can use Team `HL6QDFKUFC`, or update `DEVELOPMENT_TEAM` / bundle IDs to a usable team.
- Let Xcode create/download iOS Development provisioning profiles for the App and Widget extension.
- Re-run the build command.
- Install:

```bash
xcrun devicectl device install app \
  --device EEA2E255-8C7E-50FB-A951-A9DE9B7E26C6 \
  ~/Library/Developer/Xcode/DerivedData/AIUsageMobile-*/Build/Products/Debug-iphoneos/AIUsageMobileApp.app
```

## Acceptance Criteria

- Signed build succeeds for the paired iPhone.
- `devicectl device install app` succeeds.
- App appears on the iPhone as `AI Usage`.

## Verification

```bash
cd mobile/ios-xcode
xcodebuild -project AIUsageMobile.xcodeproj \
  -scheme AIUsageMobileApp \
  -configuration Debug \
  -destination 'id=EEA2E255-8C7E-50FB-A951-A9DE9B7E26C6' \
  -allowProvisioningUpdates \
  build
```

## Handoff

- Signed app path: `/Users/wangzhipeng/Library/Developer/Xcode/DerivedData/AIUsageMobile-gjmawcerlhhpacgqzrwyqgffpedk/Build/Products/Debug-iphoneos/AIUsageMobileApp.app`.
- Install result: `devicectl device install app` succeeded for `com.wangzhipeng.aiusage.mobile`.
- Launch result: initial post-signing launch succeeded; later launch after app-icon rebuild was denied because the iPhone was locked.
