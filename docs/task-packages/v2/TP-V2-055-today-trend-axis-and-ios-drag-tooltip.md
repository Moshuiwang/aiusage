# TP-V2-055 Today Trend Axis and iOS Drag Tooltip

Version: V2
ID: TP-V2-055
Status: done
Type: implementation
Depends on: TP-V2-054
Parallel with: none

## Goal

Fix incorrect today trend data and restore finger-slide chart tips in the iOS App.

## Context

Simulator validation showed `period=today` renders the correct total from production, but the trend chart details are wrong. Production `/api/mobile/summary?period=today` currently returns hourly buckets from the recent 24 hours, starting at the previous day 17:00, while the selected period is the calendar day. The iOS chart also only supports tapping individual dots, not dragging across the whole chart.

## Scope

- Change today hourly trend axis to calendar-day hours for the requested date.
- Keep hourly block spreading behavior inside the calendar-day axis.
- Add iOS chart default selection for the last non-zero point.
- Add drag gesture selection across the chart surface.
- Deploy the server fix to production after local verification.

## Out of Scope

- Do not change week/month/all semantics.
- Do not install to the physical iPhone.
- Do not change credential storage or public API auth.

## Red Test

- Python test: today trend axis starts at `YYYY-MM-DDT00:00:00+08:00` and ends at `YYYY-MM-DDT23:00:00+08:00`.
- Swift test: chart tip selection defaults to the last non-zero point and resolves the nearest point from a drag location.

## Implementation

- Replace recent-24-hour today axis construction with a date-based calendar-day axis.
- Add a small `TrendPointSelection` helper in mobile core and use it in `UsageTrendChart`.
- Attach `DragGesture(minimumDistance: 0)` to the chart area.

## Acceptance Criteria

- Production today API no longer includes previous-day hour buckets.
- Today chart tips default to the latest non-zero hourly bucket.
- Dragging across the chart updates tips to the nearest hourly/daily bucket.
- Simulator App is updated only on simulator and reads production data.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_snapshot_builder.TestSnapshotBuilder.test_today_period_uses_calendar_day_hourly_trend -v
cd mobile/ios && swift test
cd mobile/ios-xcode && xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'id=70729294-180A-4862-B2EA-56939BBB6277' build
```

## Handoff

- Report changed files, local verification, production API verification, and simulator screenshot.

## Completion Notes

- Fixed server today trend axis to use the selected calendar date from `00:00` to `23:00`.
- Added daily residual fill for today hourly trend when hourly/block facts are incomplete, so hourly point totals match the period total.
- Added `TrendPointSelection` for default last non-zero tips and nearest-point drag selection.
- Updated `UsageTrendChart` to handle `DragGesture(minimumDistance: 0)` across the whole chart area.
- Deployed server fix to production `vpn2` and restarted `ai-usage-server`.
- Production today verification:
  - `period_total`: `253355667`
  - `point_sum`: `253355667`
  - first bucket: `2026-06-03T00:00:00+08:00`
  - last bucket: `2026-06-03T23:00:00+08:00`
- Installed the updated App only on simulator `70729294-180A-4862-B2EA-56939BBB6277`; physical iPhone was not touched.
- Simulator screenshot: `tmp/ai-usage-simulator-today-fixed.png`.
