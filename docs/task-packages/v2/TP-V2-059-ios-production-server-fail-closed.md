# TP-V2-059 iOS Production Server Fail Closed

Version: V2
ID: TP-V2-059
Status: done
Type: implementation
Depends on: TP-V2-051, TP-V2-053
Parallel with: none

## Goal

Make the iOS App fail closed when it is not using the production mobile summary server, instead of silently showing bundled fixture data.

## Context

Physical iPhone installs can be launched from the Home Screen without the simulator-only environment/defaults used during validation. In that case the App currently loads bundled `mobile-summary.json`, which can make stale fixture data look like real production data.

## Scope

- Update the iOS App entrypoint runtime config.
- Keep production base URL as the default server.
- Reject non-production server URLs unless an explicit development override is set.
- Stop using bundled fixture data as App runtime fallback.
- Show an explicit loading / configuration / failed state instead of stale sample data.

## Out of Scope

- Do not commit production tokens.
- Do not redesign the whole settings flow.
- Do not change server API shape.
- Do not change Widget fixture behavior in this package.

## Red Test

- Static iOS integration test asserts the App entrypoint does not call `MobileSummaryFixtureLoader.load()` or set `.fixture`.
- Static iOS integration test asserts a production URL default, non-production rejection, and explicit development override hook.

## Implementation

- Add a production default URL in `MobileSummaryRuntimeConfig`.
- Add server validation that accepts only `vpn2.chunbai.com` by default.
- Keep `AI_USAGE_ALLOW_NON_PROD_SERVER=1` as a development-only escape hatch.
- Initialize and reset the App with empty summaries rather than fixture summaries.
- Add a small status overlay for missing config or request failure.

## Acceptance Criteria

- Launching the App without production config no longer shows bundled fixture data.
- Non-production server URLs are rejected by default.
- Production server URL is the default base URL.
- API failure is visible as a status state instead of stale data.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
cd mobile/ios && swift test
cd mobile/ios-xcode && xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'id=70729294-180A-4862-B2EA-56939BBB6277' build
PYTHONPATH=src python3 -m unittest discover -s tests -v
git diff --check
```

Production / physical-device verification:

- Verified production `/api/mobile/summary?period=week` returned HTTP 200 with 7 trend points.
- Built physical iPhone Debug app using a temporary local xcconfig for production URL/token. The temporary file was removed after build and no token was written to git.
- Installed to `王志鹏 的 iPhone 16` (`com.wangzhipeng.aiusage.mobile`) and launched without runtime environment variables.

## Handoff

- Report changed files and verification.
- State clearly whether the App was installed to physical iPhone.
