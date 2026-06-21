# TP-V2-051 iOS Live Mobile Summary Client

Version: V2
ID: TP-V2-051
Status: done
Type: implementation
Depends on: TP-V2-043, TP-V2-050
Parallel with: none

## Goal

Let the iOS simulator App load read-only live data from `/api/mobile/summary` instead of only rendering the bundled fixture.

## Context

The mobile API contract exists and is authenticated. The SwiftUI App currently loads `mobile-summary.json` from the App bundle via `MobileSummaryFixtureLoader`, so simulator screenshots do not prove the App can read current server data.

## Scope

- Add a testable Swift `MobileSummaryAPIClient` in `AIUsageMobileCore`.
- Support bearer auth and `period` query construction.
- Update the Xcode App entrypoint to load live summary when API base URL / token are supplied through environment variables.
- Keep bundled fixture fallback for previews/offline simulator use.
- Add ATS local-network allowance for local HTTP server access where needed.

## Out of Scope

- Do not install to the physical iPhone without explicit user instruction.
- Do not commit API tokens, SSH keys, or local server config.
- Do not add write endpoints or device collection credentials to the App.
- Do not redesign authentication UX in this task.

## Red Test

- Add Swift tests for request URL, bearer header, period query, HTTP status handling, and JSON decode.
- Add static Xcode integration checks that the App entrypoint no longer hardcodes fixture-only loading and supports `AI_USAGE_API_BASE_URL` / `AI_USAGE_API_TOKEN`.

## Implementation

- Implement API config and client under `mobile/ios/Sources/AIUsageMobileCore`.
- Add async loading state in the App target.
- Read simulator environment variables:
  - `AI_USAGE_API_BASE_URL`
  - `AI_USAGE_API_TOKEN`
  - optional `AI_USAGE_PERIOD`
- Fallback to bundled fixture when config is absent or live load fails.

## Acceptance Criteria

- Simulator can render live `/api/mobile/summary` data when URL/token are supplied.
- Missing/invalid config keeps the current fixture fallback, so previews and offline simulator still work.
- No secrets are committed.
- Swift tests, Python static integration tests, and simulator build pass.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
cd mobile/ios && swift test
cd mobile/ios-xcode && xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'id=70729294-180A-4862-B2EA-56939BBB6277' build
```

## Handoff

- Added `MobileSummaryAPIClient` under `mobile/ios/Sources/AIUsageMobileCore` with bearer auth, `period` query support, HTTP status validation, and JSON decode.
- Updated the Xcode App entrypoint to load live data when simulator environment variables are present:
  - `AI_USAGE_API_BASE_URL`
  - `AI_USAGE_API_TOKEN`
  - optional `AI_USAGE_PERIOD`
- Kept bundled fixture fallback for previews, missing config, and failed live loads.
- Added local-network ATS allowance for simulator local HTTP access.
- Fixed the trend detail selection so it refreshes when live trend points replace fixture points.
- Verified the simulator against the local authenticated API server at `http://127.0.0.1:8781/api/mobile/summary?period=week`; screenshot: `tmp/ai-usage-simulator-home-live-v2.png`.
- Physical iPhone was not updated or reinstalled in this task.
