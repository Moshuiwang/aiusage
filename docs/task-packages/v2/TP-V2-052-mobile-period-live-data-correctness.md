# TP-V2-052 Mobile Period Live Data Correctness

Version: V2
ID: TP-V2-052
Status: done
Type: implementation
Depends on: TP-V2-043, TP-V2-051
Parallel with: none

## Goal

Make the iOS simulator show correct live data for `today`, `week`, `month`, and `all`.

## Context

TP-V2-051 proved that the simulator can load live `/api/mobile/summary` data, but the App still keeps one loaded summary while the period selector only changes local UI state. That can make today/week/month/all appear as the same data with different labels.

The accepted product wording is:

- `today`: the selected/current day, with hourly trend detail where available.
- `week`: 7 days ending at the selected/current day.
- `month`: 30 days ending at the selected/current day.
- `all`: all historical data up to the selected/current day.

## Scope

- Add tests proving `/api/mobile/summary` returns distinct, correctly bounded summaries for all four period values.
- Add tests proving the iOS App requests a fresh summary when the period selection changes.
- Update the SwiftUI shell so period changes reload live data with the selected `period`.
- Preserve fixture fallback for offline previews and missing config.

## Out of Scope

- Do not install to the physical iPhone without explicit user instruction.
- Do not add production server/token settings UI in this task.
- Do not change the historical ingest schema or ccusage normalization.
- Do not change official quota semantics.

## Red Test

- Add a server/API test that inserts usage on dates inside and outside today/week/month windows, then asserts mobile summary totals and date ranges for `today`, `week`, `month`, and `all`.
- Add an iOS integration/static test that fails unless `PeriodSelector` calls an external period-change loader and live requests use the selected period instead of a fixed environment default.

## Implementation

- Keep backend period bounds aligned with the product wording above.
- Add live period loading state in the App entrypoint.
- Pass an `onPeriodSelected` callback from the App container through `AIUsageMobileRootView` to `PeriodSelector`.
- When live config exists, reload `/api/mobile/summary?period=<selected>` after the user taps a period.

## Acceptance Criteria

- Simulator period tabs do not just change labels; each tab is backed by a matching live API request.
- `today`, `week`, `month`, and `all` return correct period ids, date ranges, totals, and trend granularity.
- Missing config still renders fixture data and allows local period selection without a network request.
- Tests and simulator build pass.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_web_server tests.test_ios_xcode_integration -v
cd mobile/ios && swift test
cd mobile/ios-xcode && xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'id=70729294-180A-4862-B2EA-56939BBB6277' build
```

## Handoff

- Added API coverage proving mobile `today`, `week`, `month`, and `all` return distinct ids, date ranges, totals, and trend granularities.
- Fixed the iOS App period flow so period taps call back to the live container and reload `/api/mobile/summary?period=<selected>`.
- Fixed the RootView period selector state so it syncs after fixture data is replaced by live data. This prevents stale UI such as `week` highlighted while month data is displayed.
- Added simulator-persistent runtime config through `UserDefaults` keys so manual simulator launches can still load live data:
  - `AIUsageAPIBaseURL`
  - `AIUsageAPIToken`
  - `AIUsagePeriod`
- Verified current local live API facts from `data/usage.sqlite`:
  - `today`: 2026-06-03 to 2026-06-03, 0 tokens, hourly trend.
  - `week`: 2026-05-28 to 2026-06-03, 0 tokens, daily trend.
  - `month`: 2026-05-05 to 2026-06-03, 1586.2M tokens, daily trend.
  - `all`: all data through 2026-06-03, 1632.7M tokens, daily trend.
- Verified latest simulator build with screenshots:
  - `tmp/ai-usage-simulator-today-live-v5.png`
  - `tmp/ai-usage-simulator-week-live-v5.png`
  - `tmp/ai-usage-simulator-month-live-v5.png`
  - `tmp/ai-usage-simulator-all-live-v5.png`
- Physical iPhone was not updated or reinstalled in this task.
