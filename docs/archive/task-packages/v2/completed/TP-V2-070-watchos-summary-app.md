# TP-V2-070 watchOS Summary App

Version: V2
ID: TP-V2-070
Status: done
Type: implementation
Depends on: TP-V2-065
Parallel with: TP-V2-066, TP-V2-069

## Goal

Add an Apple Watch read-only summary app matching `watch-ui.html`.

## Context

Watch is in scope for this round. It must show a compact, read-only summary and must not introduce a new data pipeline.

## Scope

- Add watchOS target or Swift Package module under the existing iOS Xcode project.
- Add Watch summary view driven by `MobileSummary`-compatible cached data.
- Add tests/static checks for target presence and no collection logic.
- Support simulator build; support real Watch install if device and signing are ready.

## Out of Scope

- No Watch-side `ccusage`.
- No SSH.
- No direct SQLite.
- No prompt/response/log display.
- No notification or complication scope in this task.

## Red Test

- Add a failing integration/static test proving a watchOS target exists.
- Add a failing test preventing Watch code from importing collector/server modules or reading production secrets.

## Implementation

1. Add watchOS target in `mobile/ios-xcode/project.yml` and regenerate project if needed.
2. Add Watch summary SwiftUI view with total, delta/neutral badge, token breakdown, quota rings, and source rows.
3. Bind to fixture/cache summary data.
4. Build for watchOS simulator.
5. Attempt real-device install only when device, trust, Developer Mode, and signing are ready.

## Acceptance Criteria

- Watch simulator shows the design-package summary screen.
- Stale/cache state is visible when live data is unavailable.
- Watch code has no collection or provider runtime.
- Real Watch install result is reported if attempted.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageWatchApp -configuration Debug -destination 'platform=watchOS Simulator,name=Apple Watch Series 10 (46mm)' build
git diff --check
```

## Handoff

- Report Watch target and source paths.
- Attach simulator screenshot.
- State real-device install status and any required user action.
