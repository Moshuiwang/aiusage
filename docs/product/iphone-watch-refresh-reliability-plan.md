# iPhone and Watch Refresh Reliability Plan

## Purpose

This document records the current refresh facts for the iPhone and Apple Watch experience, the product risk, and the recommended one-shot implementation plan.

It is a planning document only. It does not mean the implementation has been started or completed.

## Scope and Timing

This plan has two delivery stages with different timing.

Stage 1, local freshness evidence and iPhone-to-Watch companion refresh, is client-side iOS work and is migration-independent. TP-V2-085 and TP-V2-100 intentionally pull this stage forward so device verification can explain where freshness stops.

Stage 2, APNs silent refresh, remains deferred until the Cloudflare Worker Native migration is complete and VPN2 has been moved to cold backup.

Reason: the APNs silent-refresh trigger must be built on the final Cloudflare Worker Native backend, not on the VPN2 Python server that is being retired. Building the server-side push trigger on VPN2 now would be throwaway work that has to be rebuilt after cutover.

The two stages have different migration dependencies:

- Stage 1 (local freshness evidence / observability) is client-side iOS work and is migration-independent. It is now being pulled earlier through TP-V2-085 and TP-V2-100 to aid device-refresh verification.
- Stage 2 (APNs silent refresh trigger) has a hard dependency on the canonical backend and must target the Cloudflare Worker, after cutover.

## Current Verified Facts

### Server freshness

- `/api/mobile/summary?period=today` is generated on request from the server SQLite read model.
- It is not a static file that only refreshes every 30 minutes.
- In the 2026-06-24 check, two consecutive mobile API requests returned different `generated_at` values a few seconds apart, proving the mobile API response is rebuilt per request.
- The Mac pusher currently runs every 300 seconds, or about every 5 minutes.
- Recent pusher logs showed accepted usage and limits pushes around:
  - `2026-06-24 00:30:45 +08:00`
  - `2026-06-24 00:36:05 +08:00`
  - `2026-06-24 00:41:27 +08:00`
  - `2026-06-24 00:46:51 +08:00`
- Production `/api/health` showed `latest.json` updated at `2026-06-24 00:49:37 +08:00`.

Product conclusion: the server is fresh enough for this use case. The main gap is not server snapshot generation; it is whether iPhone wakes up and pulls the fresh server state.

### iPhone and Watch freshness

The 2026-06-24 device check was intentionally read-only:

- The iPhone App was not launched by the check.
- The fact-check helper was not run because it launches the iPhone App and would pollute background-refresh evidence.
- Existing device containers and API state were inspected.

Observed device facts:

- iPhone runtime diagnostic last successful request:
  - `recordedAt`: `2026-06-23T15:49:42Z`
  - local time: `2026-06-23 23:49:42 +08:00`
  - request URL: `https://aiusage.chunbai.com/api/mobile/summary?period=today`
  - status: `success`
  - period: `today`
- WatchConnectivity application context file had the same modification time:
  - `2026-06-23 23:49:42 +08:00`
- At check time, `2026-06-24 00:46:51 +08:00`, that evidence was about 57 minutes old.
- During the same window, the server mobile API already returned newer data around `2026-06-24 00:47` and `00:51`.
- The iPhone App Group did not expose a readable `last-mobile-summary.json` during the check.
- The installed iPhone diagnostic did not include `cacheWriteStatus` or `watchPushStatus`, so it could not prove whether the iPhone App Group cache write or Watch push succeeded.

Product conclusion: the current device evidence does not support saying that iPhone is reliably refreshing in the background. Watch likely shows the last successful iPhone sync until it becomes stale.

## Current User Experience Risk

The current experience can mislead the user in two ways:

- Watch may show old data while the server already has newer data.
- We cannot reliably prove whether a missing Watch update was caused by iOS not waking the app, API failure, cache write failure, WatchConnectivity failure, or Watch cache failure.

This is a product trust issue. The user should either see fresh data or see an honest stale state with a clear last update time.

## Why BGAppRefresh Alone Is Not Enough

The app already has a background refresh mechanism, but iOS does not treat it as a fixed timer. A 30-minute `earliestBeginDate` means the system may start no earlier than that time; it does not mean the system will run the task every 30 minutes.

This explains the observed behavior: the server can be fresh, while the iPhone and Watch remain behind.

## APNs Feasibility

APNs is feasible before public App Store release. Development installs, Ad Hoc builds, and TestFlight builds can use APNs when signing, entitlements, APNs environment, and provider authentication are configured correctly.

However, APNs background notifications are still not realtime guarantees. Apple treats background notifications as low priority and may delay or throttle them. APNs is better than passively waiting for `BGAppRefreshTask`, but it should be positioned as a stronger freshness trigger, not a promise of instant delivery.

Environment caveat: APNs has two separate environments. Development and direct-device debug builds use the sandbox host (`api.sandbox.push.apple.com`); TestFlight and App Store builds use the production host (`api.push.apple.com`). The `aps-environment` entitlement and the provider's target host must match the build type. A mismatch causes pushes to be silently dropped with no client-visible error, which is hard to diagnose after the fact. The provider must select the correct environment per build.

References:

- [Apple: Pushing background updates to your app](https://developer.apple.com/documentation/usernotifications/pushing-background-updates-to-your-app)
- [Apple: APS Environment Entitlement](https://developer.apple.com/documentation/bundleresources/entitlements/aps-environment)
- [Apple: Sending notification requests to APNs](https://developer.apple.com/documentation/usernotifications/sending-notification-requests-to-apns)

## Recommended Delivery (Two Migration-Sequenced Stages)

Implement this as a post-migration delivery, split into two stages by migration dependency (see Scope and Timing), keeping the work internally staged so each failure mode is diagnosable. Stage 1 is client-side and migration-independent; Stage 2 (APNs) is built on the Cloudflare Worker after cutover.

### 1. Make local freshness evidence reliable

Goal: every successful iPhone refresh leaves readable evidence.

Required behavior:

- iPhone writes `last-mobile-summary.json` to the iPhone App Group after a successful `today` summary request.
- iPhone writes `last-mobile-runtime-diagnostic.json` with:
  - request status
  - request URL without token
  - period
  - summary `generated_at`
  - local recorded time
  - App Group cache write status
  - App Group cache write time
  - Watch push status
  - safe error code when write or push fails
- Watch writes `last-watch-summary.json` to the Watch App Group when it receives a valid `today` summary.
- Watch writes `last-watch-cache-receipt.json` with:
  - received time
  - summary `generated_at`
  - cache write status
  - delivery type
  - safe error code when write fails
- The read-only fact-check path must not launch the iPhone App by default.

User-facing outcome:

- We can say exactly where freshness stopped: server, iPhone request, iPhone cache, Watch push, Watch cache, or Watch UI.

Verification read-path requirement (must be defined before this stage is considered done):

- Writing the evidence files is not sufficient. We must also define how verification actually reads `last-*.json` off a physical iPhone and Apple Watch. iOS sandboxing prevents a Mac-side script from freely reading another app's App Group container; it typically requires pulling the container via Xcode / `devicectl`, or having the app expose the values through its own diagnostic surface.
- This is exactly the blocker the 2026-06-24 check hit ("App Group did not expose a readable file"). If the read path is not solved, the evidence is written but still unprovable.

### 2. Add APNs silent refresh trigger

Goal: when server data changes, iPhone gets a stronger prompt to refresh and sync Watch.

Required behavior:

- iPhone registers for remote notifications and obtains an APNs device token.
- iPhone sends a safe device registration to the server.
- Server stores device tokens without exposing them in diagnostics or logs.
- After accepted pusher ingest or accepted limits ingest, server schedules a background push to registered iPhones.
- Push payload is silent/background only and contains no token or raw usage data.
- iPhone receives the background notification, requests `/api/mobile/summary?period=today`, writes the iPhone cache, and pushes WatchConnectivity.
- Server applies throttling, recommended initial rule:
  - at most one APNs background refresh per device every 5 minutes
  - coalesce usage and limits writes within the same window
  - no push when the generated read model has no meaningful freshness change

Backend placement and requirements (post-migration):

- The "server" here is the Cloudflare Worker Native backend after cutover, not the VPN2 Python server.
- The Worker needs the APNs provider key (`.p8`) plus key/team identifiers stored as Worker secrets, never exposed in logs, diagnostics, or responses.
- The device-token store should live in D1 or KV; confirm the added reads/writes stay within the D1/Worker free-tier budget.
- The Worker sends the background push over the APNs HTTP/2 provider API using a provider JWT signed from the `.p8` key.

User-facing outcome:

- Watch freshness is no longer dependent only on opportunistic iOS background refresh.
- The expected delay becomes closer to the pusher cadence, while still showing stale if Apple does not deliver or run the app.

### 3. Keep stale UI honest

Goal: stale data must never look live.

Required behavior:

- iPhone, Watch App, and Watch complications continue showing last updated time.
- Data older than the freshness window shows stale.
- Sync failure does not clear the last good data.
- Stale copy should imply "last successful sync is old", not "server is down" unless diagnostics prove the server request failed.

User-facing outcome:

- The user can trust the surface even when it is not current.

## Acceptance Criteria

This delivery should not be considered complete just because it builds.

Minimum acceptance:

- Server mobile API returns fresh `generated_at` on request.
- iPhone App Group `last-mobile-summary.json` is readable on the physical iPhone and has `period=today`.
- iPhone diagnostic records cache write and Watch push status.
- Watch App Group `last-watch-summary.json` or `last-watch-cache-receipt.json` is readable on the physical Apple Watch, or the report clearly states the device-read blocker.
- APNs device registration is visible on the server without exposing secrets.
- A server-side accepted ingest can trigger a throttled APNs background push.
- After a push-triggered refresh, iPhone diagnostic and Watch receipt move forward to the same summary `generated_at`.
- If APNs does not wake the app, stale state remains visible and diagnostics show the last successful sync.

## Explicit Non-Goals

- Do not make Watch a direct server client in this delivery.
- Do not store server token, bearer token, or raw provider response in Watch.
- Do not promise realtime updates.
- Do not use APNs as a high-frequency polling substitute.
- Do not claim success from simulator-only evidence.

## Product Decision

This remains a staged initiative (see Scope and Timing). Stage 1 may proceed before Cloudflare cutover; Stage 2 must not start until the Cloudflare Worker Native migration is complete and VPN2 is cold backup.

Deliver it in two migration-sequenced stages rather than one combined drop:

Stage 1 — local freshness evidence and read-path (client-side iOS, migration-independent):

1. Evidence and cache reliability (iPhone and Watch write readable receipts/diagnostics).
2. Define and prove the verification read-path for physical-device App Group files.
3. Read-only fact-check update.

Stage 2 — APNs silent refresh trigger (built on the Cloudflare Worker Native backend, after cutover):

4. APNs device token registration and storage (tokens in D1/KV, keys as Worker secrets).
5. APNs background push trigger with throttling, on accepted Worker ingest.
6. Physical iPhone and Apple Watch verification, including the dev-vs-production APNs environment.

The internal order still matters because APNs failures are otherwise hard to distinguish from cache, WatchConnectivity, or Watch App Group failures: get the evidence/observability solid first, then layer APNs on top so each failure mode stays diagnosable.
