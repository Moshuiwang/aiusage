# AI Usage Mobile iOS

This Swift Package is the first native iPhone App implementation slice.

## Scope

- Decodes the read-only `/api/mobile/summary` contract.
- Builds display state for Home, Sources, Breakdown, and Limits.
- Provides a SwiftUI `AIUsageMobileRootView` with four system tabs.
- Provides small and medium widget content views backed by `WidgetSummaryBuilder`.
- Uses system SwiftUI controls and system appearance; light/dark mode follows iOS.

## Run Tests

```bash
cd mobile/ios
swift test
```

## Boundary

- No production credentials.
- No collector, SSH, `ccusage`, or official provider execution in the App.
- No generated Xcode WidgetKit extension yet; the package only provides reusable content views and summary state.
