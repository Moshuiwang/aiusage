# TP-V2-084 Watch Companion TestFlight Stability

Version: V2
ID: TP-V2-084
Status: draft
Type: implementation
Depends on: TP-V2-070
Parallel with: none

## Goal

Make the Apple Watch experience stable for the owner by turning the current watchOS summary app into an iPhone companion + watch face WidgetKit accessory flow that can be distributed through TestFlight.

## Context

The current watchOS app exists, but the user no longer sees it on Apple Watch. TP-V2-070 already delivered the baseline Watch summary app, WatchConnectivity handoff, Watch-local cache, and MobileSummary decode path. This task must treat that as the baseline and focus on stable companion install, watch face access, and TestFlight handoff.

Product direction is now documented in:

- `docs/product/watch-companion-testflight-prd.md`
- `docs/architecture/watch-companion-testflight.md`

This task must preserve the existing data truth chain. Watch must not become a new collection path, and this task must not introduce a second long-lived iPhone-to-Watch data contract unless the existing MobileSummary path cannot support the watchOS widget extension.

## Scope

- Adjust iOS/watchOS Xcode project structure so the Watch app is managed as part of the iPhone app experience.
- Add a watchOS WidgetKit extension embedded in `AIUsageWatchApp`.
- Support `.accessoryRectangular`, `.accessoryCircular`, and `.accessoryInline` for supported system watch faces.
- Add a shared Watch App Group cache that both `AIUsageWatchApp` and the watchOS WidgetKit extension can read.
- Reuse the existing MobileSummary WatchConnectivity/cache path by default; add a smaller display DTO only if the implementation proves it is needed for the widget extension.
- Add static/fixture tests that prove the target wiring, watchOS widget extension, accessory families, no-collection boundary, and the chosen Watch data contract.
- Document TestFlight build/install/update handoff for the owner.

## Out of Scope

- No App Store public launch.
- No custom third-party watch face.
- No new SQLite tables.
- No new server endpoint unless a separate API task package is approved.
- No Watch-side token storage.
- No Watch-side `ccusage`, SSH, provider runtime, raw `.claude` or `.codex` log access.
- No Cloudflare migration work.

## Red Test

- Add a failing test proving the iPhone app target owns or embeds the Watch companion relationship expected by the chosen Xcode structure.
- Add a failing test proving `AIUsageWatchApp` embeds a watchOS WidgetKit extension target.
- Add a failing test proving `AIUsageWatchApp` and the watchOS WidgetKit extension declare the same App Group entitlement for Watch-local shared cache.
- Add a failing test proving the Watch widget source exists and declares `.accessoryRectangular`, `.accessoryCircular`, and `.accessoryInline`.
- Add or extend a failing no-collection-boundary test proving Watch code does not import server, collector, pusher, storage, or provider runtime modules.
- Add or extend a failing test proving the watchOS widget extension reads from the shared App Group cache, not the Watch App private `.cachesDirectory`, server config, or bearer token state.
- If a Watch DTO is introduced, add a failing decode fixture test before implementation; otherwise extend the existing MobileSummary decode/cache tests.

## Implementation

1. Confirm the Apple-supported Xcode structure for companion Watch app + watchOS WidgetKit accessory in the current Xcode version.
2. Update `mobile/ios-xcode/project.yml` first, then regenerate/check `AIUsageMobile.xcodeproj`.
3. Preserve TP-V2-070's existing MobileSummary WatchConnectivity bridge unless a documented widget-only display DTO is required.
4. Add Watch App Group entitlement files/settings for `AIUsageWatchApp` and the watchOS WidgetKit extension.
5. Migrate or wrap `WatchSummaryStore` so Watch App and watchOS WidgetKit extension read the same shared App Group cache.
6. Add a watchOS WidgetKit extension embedded in the Watch app, with entries for `.accessoryRectangular`, `.accessoryCircular`, and `.accessoryInline`.
7. Prioritize Codex quota percentage, reset time, and stale state in the watch face surfaces.
8. Keep Watch App and widget fallback UI for stale/no summary states; keep the existing 2-hour stale threshold unless this task explicitly documents a product change.
9. Add TestFlight owner handoff notes with 90-day build expiry and renewal timing.

## Acceptance Criteria

- iPhone App, Watch App, and Watch WidgetKit accessory are part of one coherent installable product shape.
- `AIUsageWatchApp` is paired/embedded as the iPhone App's companion Watch app, and the Watch app embeds the watchOS WidgetKit extension.
- `AIUsageWatchApp` and the watchOS WidgetKit extension share the same Watch App Group cache.
- Apple Watch App can display cached summary without Xcode-only assumptions.
- Watch face editor can expose `AI Usage` entries for `.accessoryRectangular`, `.accessoryCircular`, and `.accessoryInline` on supported faces.
- Watch surfaces show stale state when data is old.
- Existing `/api/mobile/summary` remains the server data source; no DB or API migration is included.
- Existing MobileSummary-based Watch sync remains the baseline unless a documented display DTO is introduced with tests.
- Cloudflare worktree and files remain untouched.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
git diff --check
```

The automated test must fail before implementation if any of these are missing:

- iPhone App and Watch App companion relationship.
- Watch App embedding of a watchOS WidgetKit extension.
- Watch App and watchOS WidgetKit extension sharing the same App Group entitlement.
- Widget source declaring `.accessoryRectangular`, `.accessoryCircular`, and `.accessoryInline`.
- Widget/Watch code staying on shared Watch App Group cache and not reading Watch App private `.cachesDirectory`, server token, provider runtime, SQLite, SSH, or collector modules.

Manual verification, when signing and TestFlight credentials are available:

```text
1. Archive and upload the iPhone app build to TestFlight.
2. Install from TestFlight on the owner's iPhone.
3. Confirm Apple Watch install through the iPhone Watch app.
4. Confirm AI Usage appears in the Apple Watch app list.
5. Add AI Usage WidgetKit accessory to a supported system watch face.
6. Confirm stale state after summary freshness window is exceeded.
```

## Handoff

- Report changed Xcode targets and source files.
- Report automated test output.
- Report whether TestFlight upload/install was completed or what credential/device action is still needed.
- Report Apple Watch app list and watch face WidgetKit accessory status.
