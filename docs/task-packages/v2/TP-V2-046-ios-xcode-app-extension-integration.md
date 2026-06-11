# TP-V2-046 iOS Xcode App Extension Integration

Version: V2
ID: TP-V2-046
Status: done
Type: implementation
Depends on: TP-V2-044, TP-V2-045
Parallel with: none

## Goal

Create an Xcode-compatible iPhone App and WidgetKit extension integration that hosts the Swift Package views from TP-V2-044 and TP-V2-045.

## Context

The mobile Swift Package now has DTOs, view models, four App tabs, and small/medium widget content views. The remaining product gap is an Xcode project or generator config that can run the iPhone App and Widget extension on simulator/device without embedding credentials.

## Scope

- Add a dedicated iOS Xcode project or generator config under `mobile/ios-xcode` or a clearly named mobile path.
- Host `AIUsageMobileRootView` in the App target.
- Host the small and medium widget content views in a WidgetKit extension target.
- Use fixture data or a local mock client for previews/tests.
- Add a non-signing build/test command where possible.

## Out of Scope

- No production server token or credential storage.
- No App Store signing or provisioning profile work.
- No collector, SSH, `ccusage`, or official provider execution from iOS.
- No network sync polish beyond a mock or fixture loader.

## Red Test

- Add a build or project-generation test/check that fails before the Xcode integration exists.
- Add a fixture preview smoke check if the chosen project tooling supports it.

## Implementation

- Prefer reusing the Swift Package instead of duplicating DTO/view code.
- Use system SwiftUI lifecycle and WidgetKit families `.systemSmall` and `.systemMedium`.
- Keep Home as the only tab with a large title.
- Keep secondary tabs without redundant top chrome.

## Acceptance Criteria

- iPhone App target can build from fixture state.
- Widget extension target can build for small and medium families.
- No secrets or production config are checked in.
- Swift Package tests still pass.

## Verification

```bash
cd mobile/ios
swift test
```

Add the Xcode build command selected by the implementation.

## Handoff

- Report project path, schemes, build command, and any signing limitations.

## Result

- Project path: `mobile/ios-xcode/AIUsageMobile.xcodeproj`.
- Scheme: `AIUsageMobileApp`.
- App target: `AIUsageMobileApp`.
- Widget extension target: `AIUsageMobileWidgetExtension`.
- Verified unsigned iPhoneOS build with:

```bash
cd mobile/ios-xcode
xcodegen generate
xcodebuild -project AIUsageMobile.xcodeproj \
  -scheme AIUsageMobileApp \
  -configuration Debug \
  -destination 'generic/platform=iOS' \
  CODE_SIGNING_ALLOWED=NO \
  build
```

- Physical install is blocked by local signing state: Xcode reports no account for Team `HL6QDFKUFC` and no provisioning profiles for `com.wangzhipeng.aiusage.mobile` / `com.wangzhipeng.aiusage.mobile.widget`.
