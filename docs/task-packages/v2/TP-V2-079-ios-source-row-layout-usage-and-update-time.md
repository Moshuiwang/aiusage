# TP-V2-079 iOS Source Row Layout Usage And Update Time

Version: V2
ID: TP-V2-079
Status: done
Type: implementation
Depends on: TP-V2-078
Parallel with: none

## Goal

Fix the iPhone `来源` card row layout so each source keeps the expected reading order without text overlap:

- First row: OS/user name on the left, usage on the right.
- Second row: machine name on the left, latest upload/update time on the right.

## Context

The iPhone `来源` card now shows source-level rows, but the second-row metadata can be visually crowded because machine names are often long. The user confirmed the desired information hierarchy:

- First row should remain the user identity, not the machine.
- Second row should remain the machine name.
- Usage must not disappear.
- Latest upload/update time should remain visible and should not be covered by a long machine name.
- If either user name or machine name is too long, truncate it instead of covering the right-side value.

Current target visual structure:

```text
wangzhipeng                                      74.2M
wangzhipengdeMacBook-Air.local              今天 09:42

wangDS                                           6.8M
ip-10-50-128-30.eu-west-1.compute.internal  06-19 18:30
```

## Scope

- Update the iOS `来源` row layout only.
- Keep source-level row count behavior from TP-V2-078 / source-level follow-up: Today may show 1 source, Week may show multiple source IDs, Month/All may show all non-zero source IDs.
- Keep first row left label as user name / OS account when available.
- Keep second row left label as machine name when available.
- Keep first row right value as usage.
- Keep second row right value as latest upload/update time.
- Add stable layout constraints so long text truncates instead of overlapping right-side values.
- Add Swift or static test coverage proving the row layout keeps usage and update time in separate right-aligned positions.

## Out of Scope

- Do not change source filtering, source aggregation, or source-level vs machine-level data semantics.
- Do not change quota cards, navigation, AppIcon, model card, or breakdown drilldown.
- Do not change `/api/mobile/summary` schema unless an existing field is missing; prefer using existing `source`, `row`, and timestamp fields.
- Do not delete source history or hide non-zero sources.
- Do not introduce a third line per source row unless the two-line layout is proven impossible on iPhone.

## Red Test

- Add a Swift/UI-adjacent or static test that fails if `PeriodSourceRow` no longer renders:
  - first row containing the display user and token usage;
  - second row containing machine name and update date/time.
- Add a test or static assertion that the row reserves right-side space for usage and update time, so long left labels are truncated rather than covering right labels.
- Keep or extend the existing source row tests so source rows remain unbounded by machine count.

## Implementation

1. Read `PeriodSourcesCard` and `PeriodSourceRow` in `mobile/ios/Sources/AIUsageMobileCore/AIUsageMobileRootView.swift`.
2. Adjust `PeriodSourceRow` to render two HStacks or equivalent stable layout:
   - row 1: status dot + user name, spacer, token usage;
   - row 2: machine name, spacer, update time.
3. Derive display user from `MobileSource.osUser` first, then a safe fallback.
4. Derive machine name from `MobileSource.machine` first, then display name/source id fallback.
5. Keep usage formatting from the existing row token value.
6. Keep update time formatting through `SourceUpdateDateText.format(...)`.
7. Use `.lineLimit(1)`, truncation, and explicit layout priority so right-side usage/time stay visible.
8. Run Swift tests and targeted iOS static tests.
9. Reinstall on the physical iPhone only when this task is executed, not while merely documenting it.

## Acceptance Criteria

- In every source row, first row left shows the user name and first row right shows usage.
- In every source row, second row left shows the machine name and second row right shows latest update/upload time.
- Long user names truncate before covering usage.
- Long machine names truncate before covering update time.
- Usage remains visible and does not disappear in the new layout.
- Update time remains visible and does not get covered by machine name.
- The `来源` card still shows all non-zero source-level rows for the selected period.
- The layout is readable on the physical iPhone.

## Verification

```bash
cd mobile/ios && swift test
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration.IOSXcodeIntegrationTests.test_ios_sources_card_uses_source_level_usage_rows -v
git diff --check
```

Physical iPhone check after implementation:

- Open Today, Week, Month, and All.
- Inspect `来源`.
- Confirm first row is `user + usage`.
- Confirm second row is `machine + update time`.
- Confirm long machine names truncate instead of covering update time.
- Confirm source counts still match source-level non-zero contributors.

## Handoff

- Report the changed Swift file and tests.
- Report source row behavior for a short user name and a long machine name.
- Report whether the physical iPhone install/check was completed.
- State whether any source data or API schema changed.

## Completion Notes

- Implemented on 2026-06-21.
- `PeriodSourceRow` now renders two stable rows: user + usage, then machine + update time.
- Long user and machine labels truncate before covering the right-side usage or update time.
- No mobile API schema, source aggregation, or quota behavior was changed for this task.
- Verified with targeted iOS static tests, Swift package tests, unsigned iPhoneOS build, and guarded physical iPhone install.
