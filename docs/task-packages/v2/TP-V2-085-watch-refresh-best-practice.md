# TP-V2-085 Watch Refresh Best Practice

Version: V2
ID: TP-V2-085
Status: in_progress
Type: implementation
Depends on: TP-V2-084
Parallel with: none

## Goal

Make the iPhone App and Apple Watch companion stay fresh using Apple-recommended refresh paths: iPhone owns server access, Watch receives compact current summaries through WatchConnectivity, and watchOS WidgetKit complications read Watch-local shared cache.

The owner-facing completion target is:

- The iPhone App is installed on the owner's iPhone.
- The Apple Watch App is installed on the paired Apple Watch.
- The Watch face exposes the accepted Codex, Claude, and Today complications.
- iPhone App, Watch App, and Watch complications show current, matching production summary data or clearly marked stale data.

## Context

Apple's WidgetKit model expects widgets and watch complications to render from timelines and be refreshed by system-managed reload opportunities, not by continuously polling. Apple's WatchConnectivity guidance recommends sending small current-state snapshots to the counterpart app with `updateApplicationContext`, and using complication-specific background transfer for complication data.

This task must preserve the accepted Watch face UI from the prior verified build while moving the refresh model to the stable companion path:

```text
iPhone background/app refresh
-> /api/mobile/summary?period=today
-> iPhone App Group cache
-> WatchConnectivity current summary transfer
-> Watch App Group cache
-> WidgetKit reload timeline
-> Watch face complications
```

## Scope

- Document product and architecture behavior for Apple Watch refresh.
- Keep Watch as a companion surface, not a separate credential-bearing client.
- Add iPhone background app refresh scheduling for the today mobile summary.
- Push the refreshed summary to Watch through the existing WatchConnectivity bridge.
- Keep the Watch face UI aligned with the verified Codex / Claude double-ring complications and Today bar-chart complication.
- Add static and build tests proving refresh, WidgetKit, and no-Watch-network boundaries.
- Verify simulator build and, when signing/device state allows, install to the owner's iPhone and paired Apple Watch.
- Create a PR after tests and installation verification or with an explicit device/signing blocker.

## Out of Scope

- No SQLite schema migration.
- No new server endpoint unless tests prove `/api/mobile/summary` cannot support Watch refresh.
- No Watch-side Bearer token, server URL, direct URLSession API fetch, `ccusage`, SSH, provider runtime, or raw `.claude` / `.codex` access.
- No public App Store launch.
- No Cloudflare migration work.

## Red Test

- Add a static test proving iPhone App registers a background app refresh task for Watch summary refresh.
- Add a static test proving iPhone App schedules the refresh task on app launch and after successful summary refresh.
- Add a static test proving the background refresh path loads `period=today`, writes the companion cache, and pushes through `WatchSummaryBridge`.
- Extend Watch static tests proving the accepted Codex, Claude, and Today complications remain present.
- Extend boundary tests proving Watch widget code still has no server token, URLSession, SSH, SQLite, provider runtime, or raw log access.
- Add or extend simulator/build verification for iPhone App plus embedded Watch App and Watch Widget extension.

## Implementation

1. Update product, architecture, interface, and database docs before implementation.
2. Run one AI review over the docs and planned implementation scope.
3. Implement iPhone background app refresh using `BGAppRefreshTask` or the SwiftUI equivalent available in the current Xcode/iOS target.
4. Keep the refresh task small: fetch only `today`, write companion cache, push WatchConnectivity, schedule the next refresh.
5. Keep WidgetKit timeline reload driven by Watch receiving a fresh summary.
6. Run automated tests and Xcode simulator build.
7. Run one follow-up AI review if implementation changes behavior beyond the reviewed docs.
8. Install on iPhone and Apple Watch if signing/device state allows; otherwise record exact blocker.
9. Commit, push, and open PR.

## Acceptance Criteria

- iPhone refresh can update Watch data without the user opening the iPhone App every time.
- Watch still shows stale state when no fresh summary has arrived.
- Watch complications match the accepted double-ring and Today chart UI.
- Watch does not own server credentials or direct data collection.
- No API or SQLite migration is included unless explicitly documented and reviewed.
- Simulator/build verification succeeds.
- PR includes docs, tests, implementation, and verification evidence.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
git diff --check
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -destination 'platform=iOS Simulator,name=iPhone 17,OS=26.5' build CODE_SIGNING_ALLOWED=NO
```

Manual verification, when signing and device state allow:

```text
1. Install AI Usage on the owner's iPhone.
2. Confirm the Watch companion installs on the paired Apple Watch.
3. Open the iPhone App once to seed current production summary.
4. Confirm Watch App displays matching current summary.
5. Add AI Usage Codex, AI Usage Claude, and AI Usage Today complications to a supported face.
6. Confirm Watch complications match iPhone data and show stale state after freshness expiry.
```

## Handoff

- Report changed docs and implementation files.
- Report AI review rounds and triaged findings.
- Report automated tests and Xcode build result.
- Report iPhone/Watch install status and data verification evidence.
- Report PR URL.
