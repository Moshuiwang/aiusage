# AI Usage iOS High Fidelity Handoff

This package turns the approved high-fidelity HTML into an implementation brief for the iOS App redesign.

## Design Source

- Open the source design at `docs/prototypes/ios-high-fidelity/index.html`.
- Run locally with:

```bash
python3 -m http.server 8788 --bind 127.0.0.1 --directory docs/prototypes/ios-high-fidelity
```

- Reference files:
  - `index.html`: screen structure and navigation order.
  - `styles.css`: native glass visual language, spacing, cards, tab bar, quota gauges.
  - `app.js`: fixture data shape, period switching, bar chart behavior, drilldown behavior.
  - `smoke-test.mjs`: prototype sanity check.

The older wireframe remains in `docs/prototypes/ios-current-wireframe/`. Use it only to understand why the screen order exists; implement from this high-fidelity package.

## SwiftUI Implementation Target

Primary target:

- `mobile/ios/Sources/AIUsageMobileCore/AIUsageMobileRootView.swift`

Supporting targets:

- `mobile/ios/Sources/AIUsageMobileCore/MobileViewModel.swift`
- `mobile/ios/Sources/AIUsageMobileCore/MobileSummary.swift`
- `mobile/ios-xcode/Sources/AIUsageMobileApp/AIUsageMobileApp.swift`
- `tests/test_ios_xcode_integration.py`

Keep using the existing `MobileSummary` read-only model. Do not change the mobile summary API contract for this redesign.

## Screen Mapping

| HTML screen | iOS screen | Required outcome |
| --- | --- | --- |
| `data-view="home"` | `HomeView` | Home first screen with title, refresh, period selector, hero total, metrics, usage trend, refresh time summary. |
| `data-view="limits"` | `LimitsView` | Quota cards grouped by account/provider, weekly and 5h windows, reset reminder switch. |
| `data-view="breakdown"` | `BreakdownView` | Date / Machine / User / Model / Agent segmented dimensions and row drilldown. |
| `data-view="sources"` | `SourcesView` | Source health score and source list with agent icons, status, last observed/pushed copy. |
| `.tabbar` | `CustomGlassTabBar` | Native glass tab bar ordered Home / Limits / Breakdown / Sources. |

## Component Mapping

| HTML component | SwiftUI component |
| --- | --- |
| `.app-header` | `HomeHeader` plus refresh action in app container if live reload is available. |
| `.period-tabs` | `PeriodSelector` shared by Home and Breakdown. |
| `.hero-panel` | `HeroPanel`. |
| `.metric-grid article` | `MetricTile`; include Input, Output, Cache, cache hit rate when model supports it. |
| `.content-panel.trend-panel` | `MaterialCard` + `SectionHeader` + `UsageTrendChart`. |
| `#trendCanvas` | `BarTrendChart`; bar chart only, no line overlay. |
| `.refresh-card` | Home quota/refresh summary rows. |
| `.quota-card` / `.quota-stat` | `LimitWindowCard`; use native glass card and gauge/progress treatment. |
| `.dimension-tabs` | `BreakdownSegmentedControl`. |
| `.bar-row` | `BarRow`; supports tap to drilldown. |
| `.detail-sheet` | `BreakdownDrilldownView`. |
| `.source-card` | `SourceCard`. |
| `.brand-icon` | `BrandIcon`, `ClaudeCodeLogo`, `CodexLogo`; do not use placeholder letters. |

## Data Binding

Use existing view-state fields where possible:

- Hero total: `MobileHomeState.totalText`.
- Metrics: `inputText`, `outputText`, `cacheText`; add cache hit rate only if already available in `MobileSummary`.
- Trend: `MobileHomeState.trendPoints`.
- Limits: `MobileLimits.windows`.
- Sources: `[MobileSource]`.
- Breakdown: `MobileBreakdown`.
- Current period: shared `selectedPeriodID`, with `onPeriodSelected(period.id)` for live reload.

The HTML fixture numbers are only for visual reference. Native App numbers must come from `MobileSummary`.

## Interaction States

- Period changes update Home and Breakdown together.
- Refresh button shows a loading/refreshing state when live reload is running.
- Trend supports tap/drag tooltip with bucket label, input, output, cache, and cache ratio.
- Home `查看明细` routes to Breakdown with the current period preserved.
- Home refresh time / quota summary `查看明细` routes to Limits.
- Breakdown rows open drilldown and support return to the list.
- Limit reminder switch is local UI state only unless a real notification task package is created.

## Visual Acceptance

The final iOS App should feel like an iOS native glass app, not a web card port:

- Use native glass/material surfaces consistently.
- Keep cards at 8px-equivalent radius unless native control shape requires otherwise.
- Use system icons or existing brand icon components.
- The quota tab icon must be a gauge-style icon, not a bottle/drop shape.
- Trend is bar chart only; do not add a line to the bars.
- Keep tab bar glass/frosted, with clear selected tab state.
- Text must not overlap at iPhone 16 / iPhone 17 Pro simulator sizes.
- Preserve readable spacing and hierarchy from the high-fidelity HTML.

## Do Not

- no production token in git, docs, screenshots, logs, or committed config.
- Do not ship fixture values in the production App.
- Do not add or commit production token, token files, SSH config, or local `.xcconfig`.
- Do not change the mobile summary API contract.
- Do not reintroduce line chart overlays.
- Do not use placeholder `C` / `X` text as Claude/Codex icons.
- Do not install to a physical iPhone unless explicitly requested; if requested, use `mobile/ios-xcode/install_device_with_live_config.py`.

## Implementation Sequence

1. Add/adjust static tests in `tests/test_ios_xcode_integration.py` for the required SwiftUI components and anti-regressions.
2. Update `AIUsageMobileRootView.swift` screen structure to match the HTML screen mapping.
3. Update component styling to native glass/material while keeping current data bindings.
4. Verify period switching, trend tooltip, detail links, and drilldown.
5. Run simulator screenshots for Home, Limits, Breakdown, and Sources.

## Verification

Minimum verification:

```bash
node docs/prototypes/ios-high-fidelity/smoke-test.mjs
PYTHONPATH=src python3 -m unittest tests.test_mobile_prototype tests.test_ios_xcode_integration -v
cd mobile/ios && swift test
```

Simulator verification:

```bash
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj \
  -scheme AIUsageMobileApp \
  -destination 'id=70729294-180A-4862-B2EA-56939BBB6277' \
  -configuration Debug \
  EXCLUDED_SOURCE_FILE_NAMES='*.xcassets' \
  build
```

Capture screenshots after launch and compare against the high-fidelity HTML for screen order, glass treatment, tab bar, trend bars, quota cards, drilldown, and source list.
