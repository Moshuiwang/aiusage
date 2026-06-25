# TP-V2-100 Watch Sync Diagnostics and Version Verification

Version: V2
ID: TP-V2-100
Status: done
Type: implementation
Depends on: TP-V2-085
Parallel with: TP-V2-098

## Goal

Make iPhone -> Apple Watch freshness failures diagnosable without launching the iPhone App during verification.

After this task, a read-only device check should answer:

- whether the installed iPhone and Watch apps match the current source version/build;
- whether the latest iPhone summary refresh was foreground, pull-to-refresh, background app refresh, or another trigger;
- whether iPhone cache write succeeded;
- whether WatchConnectivity was unavailable, inactive, unsupported, encode failed, updateApplicationContext failed, or complication transfer failed;
- whether the Watch actually received and wrote the same summary `generated_at`.

## Context

Current source already contains partial diagnostics:

- iPhone writes `last-mobile-runtime-diagnostic.json`.
- iPhone diagnostic includes `cacheWriteStatus`, `cacheWrittenAt`, `cacheSummaryGeneratedAt`, and `watchPushStatus`.
- iPhone writes `last-mobile-summary.json` to the iPhone App Group.
- Watch writes `last-watch-summary.json` and `last-watch-cache-receipt.json`.

Current gaps from the 2026-06-25 read-only physical-device check:

- iPhone had fresh today data and `cacheWriteStatus=ok`.
- iPhone diagnostic showed `watchPushStatus=failed`, but did not include a safe failure reason.
- Watch cache was older than iPhone cache, proving the Watch face could show stale quota rings.
- Diagnostic did not record whether the successful iPhone request came from foreground load, pull-to-refresh, companion ensure, or `BGAppRefreshTask`.
- Device build/version was visible via `devicectl`, but no diagnostic tied the installed build to source/build metadata.

This task is intentionally narrower than TP-V2-097. It does not fix server/D1 parity or quota read-model selection.

## Scope

- iPhone diagnostic schema:
  - add safe `trigger` or `refreshSource` field for foreground initial load, pull-to-refresh, companion ensure, background app refresh, and settings-triggered refresh if applicable;
  - add safe `appVersion` and `buildNumber` fields from the installed app bundle;
  - replace generic `watchPushStatus=failed` with a structured safe status and reason.
- WatchConnectivity bridge:
  - distinguish unsupported, session unavailable, activation state not activated, encode failure, update application context failure, and complication user info transfer attempt/result where the API can report synchronously;
  - do not log token, raw summary payload, server URL with credentials, or raw provider response.
- Watch receipt:
  - keep recording `summaryGeneratedAt`, `receivedAt`, `cacheWriteStatus`, `cacheWrittenAt`, and `delivery`;
  - add app version/build metadata if available on watchOS.
- Verification tooling or manual commands:
  - document and/or script the read-only `devicectl device copy from` path for iPhone App container, iPhone App Group, and Watch App Group;
  - compare source/build metadata, iPhone diagnostic, iPhone summary, Watch receipt, and Watch summary without launching the app.
  - if `devicectl` cannot read a required App Group container on the physical device, report that as a verification blocker instead of claiming freshness diagnosis complete.

## Out of Scope

- Do not make Watch a direct server client.
- Do not add Watch-side token, server URL, URLSession fetch, provider runtime, SSH, SQLite, or raw `.claude` / `.codex` access.
- Do not implement APNs silent refresh.
- Do not change Watch UI layout or circular complication design.
- Do not change Cloudflare Worker, D1 schema, origin read model, or quota selection logic.
- Do not claim BGAppRefresh is reliable or realtime.

## Red Test

- Swift iOS unit test: `MobileRuntimeDiagnostic` encodes and decodes `refreshSource`, `appVersion`, `buildNumber`, `watchPushStatus`, and safe `watchPushReason`.
- Swift iOS unit/static test: background app refresh writes diagnostic with `refreshSource=background_app_refresh`.
- Swift iOS unit/static test: foreground companion share path writes a non-background refresh source.
- Swift iOS unit/static test: `WatchSummaryBridge.push` returns distinct safe statuses for at least session unavailable, inactive activation state, encode failure, and update application context failure.
- Swift Watch unit/static test: Watch receipt includes cache write evidence and build metadata without token or raw payload.
- Optional Python/static test: repository verification docs or helper include read-only `devicectl` container copy commands for:
  - `appDataContainer` `com.wangzhipeng.aiusage.mobile`
  - `appGroupDataContainer` `group.com.wangzhipeng.aiusage`
  - `appGroupDataContainer` `group.com.wangzhipeng.aiusage.watch`

## Implementation

1. Extend `MobileRuntimeDiagnostic` with refresh source, app version/build, and safe Watch push reason fields.
2. Update every iPhone diagnostic write path to pass a refresh source:
   - initial foreground load;
   - manual refresh;
   - companion today ensure;
   - background app refresh;
   - settings save / connection test refresh if it writes production summary.
3. Replace `WatchSummaryBridge.push(_:) -> String` with a small value object or stable status string plus safe reason.
4. Preserve existing `watchPushStatus` compatibility if needed, but add enough detail for diagnosis.
5. Extend Watch cache receipt with version/build metadata where feasible.
6. Add or update tests before implementation changes.
7. Add read-only physical-device verification commands to the task handoff or a small repo-local verification note if tests need a stable command reference.

## Acceptance Criteria

- A read-only physical-device check can tell whether the installed apps are old compared with the current built version.
- A diagnostic with `watchPushStatus=failed` also states a safe reason.
- A diagnostic can tell whether the iPhone refresh came from background refresh or a foreground/manual path.
- Watch receipt proves whether the Watch wrote the same `summaryGeneratedAt` as the iPhone summary.
- No diagnostic contains bearer token, raw usage logs, raw provider response, or full sensitive request headers.
- Existing iPhone summary cache and Watch cache behavior continues to work.
- If physical-device App Group files cannot be copied read-only, the report names the exact unreadable container and leaves device-data verification incomplete.

## Verification

```bash
swift test --package-path mobile/ios
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -v
git diff --check
```

Manual read-only verification on physical devices:

```bash
xcrun devicectl list devices
xcrun devicectl device info apps --device <iphone-device-id>
xcrun devicectl device info apps --device <watch-device-id>
xcrun devicectl device copy from --device <iphone-device-id> --domain-type appDataContainer --domain-identifier com.wangzhipeng.aiusage.mobile --source / --destination tmp/device-containers/iphone-app
xcrun devicectl device copy from --device <iphone-device-id> --domain-type appGroupDataContainer --domain-identifier group.com.wangzhipeng.aiusage --source / --destination tmp/device-containers/iphone-group
xcrun devicectl device copy from --device <watch-device-id> --domain-type appGroupDataContainer --domain-identifier group.com.wangzhipeng.aiusage.watch --source / --destination tmp/device-containers/watch-group
```

The manual check must not launch the iPhone App unless the report explicitly says it is switching from read-only diagnosis to active refresh verification.

## Handoff

Report:

- changed files;
- tests run and results;
- installed iPhone and Watch app version/build from `devicectl`;
- iPhone diagnostic refresh source and Watch push status/reason;
- iPhone summary `generated_at`;
- Watch receipt and Watch summary `generated_at`;
- whether the Watch cache matches the iPhone summary;
- any remaining device-read or signing blocker.
