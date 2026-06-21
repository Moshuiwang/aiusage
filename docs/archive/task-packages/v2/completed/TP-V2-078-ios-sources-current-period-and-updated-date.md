# TP-V2-078 iOS Sources Current Period And Updated Date

Version: V2
ID: TP-V2-078
Status: done
Type: implementation
Depends on: TP-V2-043, TP-V2-052
Parallel with: TP-V2-076, TP-V2-077

## Goal

Make the iOS `来源` card reflect the selected period's real contributors across Today / Week / Month / All and make each source update time unambiguous.

## Context

The user observed two issues in the iPhone App period tabs:

- A stale old user/source such as `LIUDS` still appears in `来源` even though its usage is `0`.
- The source update time only shows clock time, so users cannot tell whether it means today, yesterday, or an older date.
- The same issue can appear in Today, Week, Month, and All, so the fix must apply to whichever period is selected.
- The source list must not behave like a fixed three-slot list. If there is one real source, show one. If there are ten real sources, show ten.

Current behavior boundary:

- `build_snapshot()` intentionally keeps source identities in `groups.by_machine` even when the selected period has zero usage. This is useful for historical identity awareness, but it makes the selected period look like an inactive old account is still contributing.
- `build_mobile_summary()` sends `source_status` and `breakdown.by_machine` to iOS.
- `PeriodSourcesCard` renders rows from `byMachine`; it does not filter zero-token rows.
- `MobileViewModel` has a separate `topSources = Array(summary.breakdown.byMachine.prefix(3))` for summary use. This must not become the source list rule.
- `PeriodSourceRow.sourceSub()` appends `shortTime(lastPushedAt/lastObservedAt)`.
- `shortTime()` only returns `HH:mm`, dropping the date.

Product rule:

- `来源` is a contribution list, not an operations inventory.
- For the selected period, sources with `0` tokens should not appear as source contributors.
- The rule applies to all period tabs: Today, Week, Month, and All.
- The source list should render all non-zero contributors for the selected period.
- Do not pad the list to three rows.
- Do not truncate the source card to three rows.
- This must not delete source identities, history, source health records, or old users from the database.
- If every source has `0` tokens in the selected period, show the existing empty state rather than listing old accounts.
- Source update time should include day context in a quiet style.
- The update time may live on the second line or as weak text on the first line, but it must not visually compete with the source name or token number.

Recommended display:

- Same local date as the selected Today date: `今天 09:42`
- Previous local date: `昨天 22:10`
- Older date in the current year: `06-19 18:30`
- Different year: `2025-12-31 18:30`
- If parsing fails, keep the raw value only as a fallback and do not crash.

## Scope

- Filter iOS source contribution rows so zero-token sources do not render in the `来源` card.
- Ensure the `来源` card shows all non-zero rows for the selected period, not just the top three.
- Keep the filter scoped to display/mobile summary output; do not purge canonical data.
- Add a date-aware source update time formatter.
- Keep the timestamp visually secondary.
- Add tests for zero-token source suppression, all-period behavior, unbounded source count, and date-aware formatting.

## Out of Scope

- Do not remove old users or source identities from SQLite.
- Do not change collector or pusher behavior.
- Do not change source health monitoring semantics.
- Do not hide non-zero stale/error sources; if a source contributed in the selected period, users should still see it.
- Do not change homepage summary cards unless needed to keep the source card from reusing `topSources`.
- Do not require iOS Widget source lists to show every source; this task targets the iPhone App source card.
- Do not redesign the whole Sources page.
- Do not change quota cards; TP-V2-075 to TP-V2-077 cover quota issues.

## Red Test

- Add a mobile summary or Swift view-model test with one non-zero source and one zero-token historical source. The zero-token source must not appear in the rendered source rows for Today, Week, Month, and All.
- Add a test proving the empty state appears when all period source rows are zero.
- Add a test with more than three non-zero sources, proving the `来源` card renders all of them.
- Add a test with only one non-zero source, proving the `来源` card renders exactly one row and does not pad with old or zero sources.
- Add Swift formatting tests:
  - same local day -> `今天 HH:mm`
  - previous local day -> `昨天 HH:mm`
  - older same-year day -> `MM-dd HH:mm`
  - different-year day -> `yyyy-MM-dd HH:mm`
- Add coverage that malformed timestamps do not crash the Sources card.

## Implementation

1. Decide the filter location:
   - Preferred: mobile summary or view-model display state should expose only source contribution rows with `tokens > 0`.
   - Acceptable: `PeriodSourcesCard` filters `byMachine` before rendering, if API compatibility should remain unchanged.
2. Preserve source matching for rows that remain visible, using existing `source_ids` before falling back to machine/display name matching.
3. Audit source-list call sites for accidental `prefix(3)` or fixed-slot behavior:
   - `PeriodSourcesCard` must receive/render all non-zero rows.
   - `topSources` may remain a homepage summary concept only if it does not drive the `来源` card.
4. Replace `shortTime()` usage in source subtitles with a date-aware helper for source update time.
5. Use `summary.timezone` or the server-provided timezone when comparing dates.
6. Keep timestamp styling secondary and single-line.
7. Confirm `LIUDS`-style zero rows no longer appear in any selected period while non-zero rows remain sorted by usage.

## Acceptance Criteria

- In Today, Week, Month, and All, old sources/users with `0` tokens are not shown in `来源`.
- Non-zero sources still appear with the same token totals and ordering.
- The `来源` card shows exactly the number of non-zero contributors for the selected period:
  - 1 contributor -> 1 row.
  - 3 contributors -> 3 rows.
  - 10 contributors -> 10 rows.
- If all sources are zero for the selected period, the card shows `暂无来源数据`.
- Source update time clearly includes day context, so users can tell today vs yesterday vs older dates.
- The date text is visually quiet and does not become the main emphasis.
- No source history, source health, or database identity data is deleted.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_mobile_summary tests.test_ios_xcode_integration -v
cd mobile/ios && swift test
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination '<iPhone simulator or physical iPhone destination>' build
git diff --check
```

Visual check:

- Open Today, Week, Month, and All in the iPhone App.
- Inspect `来源` in each period.
- Confirm `LIUDS` or any other zero-token old source is absent whenever it has no contribution in that selected period.
- Confirm all active non-zero sources show, with no artificial three-row cap or three-row padding.
- Confirm update time includes date context and remains de-emphasized.

## Handoff

- Report whether filtering was done in mobile summary, Swift view-model, or Swift view.
- Include direct observation or screenshots for Today plus at least one longer period such as Week or Month.
- State how timestamps render for today, yesterday, and older source updates.
- State the observed source row count and confirm it matches the number of non-zero contributors.
- Confirm no canonical source identity/history data was deleted.

## Completion Notes

- Implemented on 2026-06-21.
- Source filtering is done in the mobile summary and reinforced in the Swift view model.
- Source rows are no longer padded to three or capped at three; they display the non-zero current-period sources.
- Compact update text now includes day context such as today, yesterday, or calendar date.
- Production verification showed Today has 1 source, Week has 6 sources, and Month/All have 10 non-zero sources.
