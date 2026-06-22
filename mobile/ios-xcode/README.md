# AI Usage iOS Xcode

This project is generated with XcodeGen and hosts the reusable Swift Package in `mobile/ios`.

## Generate

```bash
cd mobile/ios-xcode
xcodegen generate
```

## Build

```bash
xcodebuild -project AIUsageMobile.xcodeproj \
  -scheme AIUsageMobileApp \
  -destination 'generic/platform=iOS' \
  -configuration Debug build
```

The normal build does not include production credentials. For a physical iPhone install, use the guarded installer below.

## Physical Device Install

Use the guarded installer instead of hand-written `xcodebuild` / `devicectl` commands:

```bash
python3 mobile/ios-xcode/install_device_with_live_config.py --preflight-only
python3 mobile/ios-xcode/install_device_with_live_config.py
```

The guarded installer:

- reads the production token from `AI_USAGE_INGEST_TOKEN` or `--token-file`;
- verifies `https://aiusage.chunbai.com/api/mobile/summary?period=all` before building;
- writes a temporary 0600 xcconfig with the escaped production URL;
- refuses to install unless the built App `Info.plist` has the exact production URL and a non-empty token;
- removes the temporary xcconfig after install.

Manual build command for signing diagnostics only:

```bash
cd mobile/ios-xcode
xcodebuild -project AIUsageMobile.xcodeproj \
  -scheme AIUsageMobileApp \
  -configuration Debug \
  -destination 'id=EEA2E255-8C7E-50FB-A951-A9DE9B7E26C6' \
  -allowProvisioningUpdates \
  build
```
