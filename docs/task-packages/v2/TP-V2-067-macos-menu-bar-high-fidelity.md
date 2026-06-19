# TP-V2-067 macOS Menu Bar High Fidelity

Version: V2
ID: TP-V2-067
Status: ready
Type: implementation
Depends on: TP-V2-064, TP-V2-065
Parallel with: TP-V2-066, TP-V2-068, TP-V2-069

## Goal

Upgrade the existing TP-V2-064 macOS menu bar app to match `macos-popover.html` for data, icon, quota rings, trend bars, and source rows.

## Context

The project already has `clients/macos` as the supported macOS light entry. This task must improve that app, not revive the legacy macOS Widget route.

## Scope

- Update `clients/macos/Sources/AIUsageMenuBarApp/MenuBarPopoverView.swift`.
- Update `clients/macos/Sources/AIUsageMenuBarCore/MenuBarViewModel.swift` only for view-state mapping.
- Update macOS menu bar tests.
- Keep reading `/api/mobile/summary`.

## Out of Scope

- Do not read SQLite directly.
- Do not execute `ccusage`.
- Do not use `machine` / `account` filters for main-screen totals.
- Do not modify legacy `widget/macos` except if tests need explicit non-regression docs.

## Red Test

- Add failing Swift tests for source token contribution rows, official-only quota ring grouping, and bar chart ratios.
- Add static test preventing SF Symbol placeholder icon in the popover header.

## Implementation

1. Replace header icon with the shared dual-ring mark.
2. Align popover width, segmented period picker, hero card, trend bars, quota rings, and source rows.
3. Preserve refresh and open Dashboard actions.
4. Preserve stale/error display.

## Acceptance Criteria

- Popover visually matches the design package in light and dark appearances.
- Period changes reload the selected period.
- Total is global for the selected period.
- Source rows show machine/user freshness and token contribution when available.

## Verification

```bash
cd clients/macos && swift test
PYTHONPATH=src python3 -m unittest clients.macos.Tests.test_install_menu_bar_app -v
swift run --package-path clients/macos AIUsageMenuBar
git diff --check
```

## Handoff

- Report screenshots or screen recordings of the popover.
- State whether local install/run was completed.
