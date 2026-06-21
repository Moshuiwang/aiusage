# TP-V2-082 Test Baseline Backlog Reconcile

Version: V2
ID: TP-V2-082
Status: done
Type: governance
Depends on: Round 9 approval
Parallel with: none

## Goal

Make the Python unittest baseline green and make the V2 backlog reflect the accepted product direction.

## Context

Round 9 reconciles two sources of drift:

- ready backlog entries whose code and tests were already delivered;
- static tests that still guarded cancelled high-fidelity directions.

The user confirmed that the current macOS menu bar UI is accepted, the old iOS high-fidelity direction is replaced by TP-V2-073 to TP-V2-080, and stale tests should be deleted rather than skipped.

## Scope

- Mark TP-V2-060, TP-V2-061, TP-V2-065, TP-V2-066, TP-V2-069, and TP-V2-070 done.
- Cancel and archive TP-V2-067 and TP-V2-068.
- Remove dependency edges pointing to TP-V2-062, TP-V2-067, or TP-V2-068.
- Keep TP-V2-071 and TP-V2-072 as real backlog, with TP-V2-071 scoped to Web, the accepted iOS 073 to 080 line, iOS Widget, and watchOS.
- Delete stale tests tied only to cancelled product directions.

## Out of Scope

- Do not implement new product features.
- Do not change SQLite schema, APIs, or physical client directories.
- Do not commit automatically.

## Tests Removed

- `tests/test_mobile_prototype.py`
  - removed `test_ios_high_fidelity_handoff_package_is_developer_ready`, which hard-coded TP-V2-062 as a ready package.
- `tests/test_dashboard_static.py`
  - removed macOS menu bar high-fidelity static assertions for the old popover brand component and handoff layout.
- `tests/test_ios_xcode_integration.py`
  - removed the macOS entry from `test_brand_surfaces_do_not_use_placeholder_chart_icon`.
  - removed `test_ios_home_uses_multi_platform_design_dashboard_components`.
  - removed `test_swiftui_surface_matches_approved_mobile_prototype_shape`.

## Acceptance Criteria

- `PYTHONPATH=src python3 -m unittest discover -s tests` has no failures.
- `cd mobile/ios && swift test` passes.
- V2 backlog has no active dependency on TP-V2-062, TP-V2-067, or TP-V2-068.
- No product code, API contract, SQLite schema, or client directory move is included.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_mobile_prototype -q
PYTHONPATH=src python3 -m unittest tests.test_dashboard_static -q
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration.IOSXcodeIntegrationTests.test_brand_surfaces_do_not_use_placeholder_chart_icon -q
PYTHONPATH=src python3 -m unittest tests.test_ios_xcode_integration -q
git diff --check
PYTHONPATH=src python3 -m unittest discover -s tests -q
cd mobile/ios && swift test
```

## Handoff

- Backlog is now aligned with the accepted product direction.
- TP-V2-071 and TP-V2-072 remain as the next real ready packages.
- watchOS real-device validation remains a manual follow-up and does not block TP-V2-070 done.
