# TP-V2-045 iOS Widget Summary

Version: V2
ID: TP-V2-045
Status: done
Type: implementation
Depends on: TP-V2-044
Parallel with: none

## Goal

Add the first iOS Widget summary surface backed by the mobile summary contract or an App-prepared snapshot.

## Context

iOS Widget is not part of the in-app Home screen. It belongs to the system widget surface and should only show glanceable data. The approved App prototype intentionally removed in-app widget previews.

## Scope

- Add small and medium SwiftUI widget content views that can be hosted by a WidgetKit extension.
- Reuse App DTO/view-model output; do not call collectors or official providers.
- Show today total or current observed window, last updated, and source health status.
- Add fixture-driven Swift tests where practical.

## Out of Scope

- No macOS Widget redesign.
- No large widget in the first pass.
- No network collection from the widget extension.
- No secret storage changes.

## Red Test

- Add tests that the widget summary model chooses observed limits when available and falls back to daily/source health when limits are missing.

## Implementation

- Keep WidgetKit data read-only and bounded.
- Use system typography, colors, and dark/light appearance.
- Keep density high enough for glanceable use; no drilldown.

## Acceptance Criteria

- Small and medium widget content views render from fixture state.
- Missing limits do not display fake quota.
- Build/test does not require production credentials.

## Verification

```bash
cd mobile/ios
swift test
```

## Handoff

- Report widget families, fixture behavior, and remaining Xcode extension/signing/manual preview steps.
