# TP-V2-062 iOS High Fidelity App Redesign

Version: V2
ID: TP-V2-062
Status: cancelled
Type: implementation
Depends on: none
Parallel with: none

## Goal

Implement the approved high-fidelity iOS App interface from `docs/prototypes/ios-high-fidelity/` in the SwiftUI App.

## Context

The current high-fidelity HTML is the design source for the App redesign. It was generated from the earlier wireframe and keeps the product information architecture: Home, Limits, Breakdown, Sources. The handoff package is `docs/prototypes/ios-high-fidelity/HANDOFF.md`.

The SwiftUI App already has the live `MobileSummary` pipeline, period switching, glass UI pieces, bar trend chart, drilldown, and physical-device install workflow. This task is a visual and interaction alignment pass, not a data-contract change.

Round 9 cancellation note: this old high-fidelity handoff route is superseded by TP-V2-073 to TP-V2-080 and is kept only as historical context.

## Scope

- Use `docs/prototypes/ios-high-fidelity/HANDOFF.md` as the implementation contract.
- Update `mobile/ios/Sources/AIUsageMobileCore/AIUsageMobileRootView.swift`.
- Update `mobile/ios/Sources/AIUsageMobileCore/MobileViewModel.swift` only if a displayed field already exists in `MobileSummary` but is not exposed to the view state.
- Update `tests.test_ios_xcode_integration` static assertions for component and anti-regression coverage.
- Keep the App read-only against `/api/mobile/summary`.

## Out of Scope

- Do not change the mobile summary API contract.
- Do not add production token, token files, SSH config, or local `.xcconfig`.
- Do not change signing, bundle IDs, Widget behavior, server deployment, or pusher logic.
- Do not implement real notification scheduling for quota reminders.
- Do not install to a physical iPhone unless explicitly requested by the user.

## Red Test

- Extend `tests/test_ios_xcode_integration.py` to assert:
  - Home / Limits / Breakdown / Sources still exist in SwiftUI.
  - `CustomGlassTabBar`, `GlassSurface`, `HeroPanel`, `MetricTile`, `BarTrendChart`, `LimitWindowCard`, `BreakdownDrilldownView`, and `SourceCard` are present.
  - Trend remains bar chart only.
  - Claude/Codex use real brand icon components, not placeholder text.
  - The quota tab uses a gauge-style system image, not a bottle/drop style.

## Implementation

1. Read `docs/prototypes/ios-high-fidelity/HANDOFF.md`.
2. Align SwiftUI screen order with the handoff: Home, Limits, Breakdown, Sources.
3. Align Home modules: header, shared period selector, hero, metric tiles, usage trend, refresh/quota summary.
4. Align Limits cards: account/provider grouping, weekly and 5h windows, gauge/progress treatment, reminder switch state.
5. Align Breakdown: dimensions Date / Machine / User / Model / Agent and row drilldown.
6. Align Sources: health score, source cards, agent icons, status text.
7. Preserve live reload and fail-closed production behavior from TP-V2-059.

## Acceptance Criteria

- Simulator Home visually matches the high-fidelity HTML structure and native glass direction.
- Limits no longer resembles the old bottle/drop design.
- Trend chart is bars only with no line overlay.
- Tab bar is glass/frosted and ordered Home / Limits / Breakdown / Sources.
- Period switching and Home-to-Breakdown routing still work.
- Source and Breakdown screens remain usable and do not regress into placeholder lists.
- No production token or generated local secret file is committed.

## Verification

```bash
node docs/prototypes/ios-high-fidelity/smoke-test.mjs
PYTHONPATH=src python3 -m unittest tests.test_mobile_prototype tests.test_ios_xcode_integration -v
cd mobile/ios && swift test
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj \
  -scheme AIUsageMobileApp \
  -destination 'id=70729294-180A-4862-B2EA-56939BBB6277' \
  -configuration Debug \
  EXCLUDED_SOURCE_FILE_NAMES='*.xcassets' \
  build
git diff --check
```

## Handoff

- Report changed SwiftUI files and tests.
- Attach simulator screenshots for Home, Limits, Breakdown, and Sources.
- State whether physical iPhone install was skipped or explicitly requested.
- If a physical iPhone install is requested, use `mobile/ios-xcode/install_device_with_live_config.py` so the production token and URL checks are enforced.
