# TP-V2-069 iOS Widget High Fidelity

Version: V2
ID: TP-V2-069
Status: ready
Type: implementation
Depends on: TP-V2-045, TP-V2-046, TP-V2-065
Parallel with: TP-V2-066, TP-V2-067, TP-V2-068

## Goal

Implement iOS Widget Small, Medium, and Large designs from `ios-widget.html`.

## Context

Current Widget extension supports Small and Medium only. The latest design includes Small, Medium, and Large with the new icon, trend bars, quota rings, and source rows.

## Scope

- Update `mobile/ios-xcode/Sources/AIUsageMobileWidgetExtension/AIUsageMobileWidget.swift`.
- Update reusable widget content in `mobile/ios/Sources/AIUsageMobileCore/WidgetSummary.swift`.
- Update Widget tests.
- Keep using summary/cache data, not collection logic.

## Out of Scope

- Do not add Widget-side collection.
- Do not store production token in the extension.
- Do not make Widget calculate period boundaries independently.

## Red Test

- Add tests failing until `.systemLarge` is supported.
- Add tests failing until Small, Medium, and Large expose the design-required fields without placeholder icon symbols.

## Implementation

1. Add Large Widget support.
2. Align Small headline, Medium mini trend, and Large trend/quota/source layout.
3. Use shared icon mark.
4. Preserve fixture fallback for previews while production reads real summary cache when available.

## Acceptance Criteria

- Small shows icon, app name, total, delta or neutral state.
- Medium shows total, breakdown, and mini bar chart.
- Large shows total, trend, quota rings, and top sources.
- Missing limits and empty sources degrade clearly.

## Verification

```bash
cd mobile/ios && swift test
xcodebuild -project mobile/ios-xcode/AIUsageMobile.xcodeproj -scheme AIUsageMobileWidgetExtension -configuration Debug -destination 'id=70729294-180A-4862-B2EA-56939BBB6277' build
git diff --check
```

## Handoff

- Attach Widget preview or simulator screenshots for Small, Medium, and Large.
