# TP-V2-056 iOS Breakdown Drilldown

Version: V2
ID: TP-V2-056
Status: done
Type: implementation
Depends on: TP-V2-055
Parallel with: none

## Goal

Make the iOS Breakdown second-level view show meaningful drilldown data instead of repeating the tapped row.

## Context

In the current iOS App, tapping a machine row only shows a detail card with the same machine label and total. The mobile API also omits source provenance from several breakdown rows, so the App cannot compute sub-breakdowns constrained to the tapped machine/source.

## Scope

- Add `source_ids` and per-source `contributions` provenance to mobile breakdown rows for machine, OS user, agent, model, and date.
- Add Swift drilldown sections that re-aggregate related rows by the selected row's source contributions.
- Replace the repeated detail card with a second-level drilldown view and a back action.

## Out of Scope

- Do not add write actions.
- Do not change period semantics.
- Do not install to the physical iPhone.

## Red Test

- Python web server test asserts mobile breakdown rows include source IDs and contribution rows for machine, OS user, agent, model, and date.
- Swift test asserts tapping a machine produces account / agent / model / date drilldown rows with selected-machine token values rather than global row values.

## Implementation

- Update `build_mobile_summary` breakdown builders to retain source IDs and per-source contribution tokens.
- Add a small `BreakdownDrilldown` helper in mobile core that scopes child rows by contribution tokens.
- Update `BreakdownView` to show a drilldown screen when a row is selected.

## Acceptance Criteria

- Machine rows carry source IDs.
- Model and date rows carry per-source contribution rows.
- Tapping a machine shows second-level account, agent, model, and date sections scoped to that machine's sources.
- The UI has a clear back affordance to return to the main breakdown list.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_web_server.TestWebServerSummary.test_mobile_summary_requires_auth_and_returns_app_contract -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
cd mobile/ios && swift test
cd mobile/ios-xcode && xcodebuild -project AIUsageMobile.xcodeproj -scheme AIUsageMobileApp -configuration Debug -destination 'id=70729294-180A-4862-B2EA-56939BBB6277' build
```

Production API deployed and verified on `vpn2`; simulator App installed only to device `70729294-180A-4862-B2EA-56939BBB6277`.

Simulator evidence:

- `tmp/ai-usage-simulator-breakdown-main-fixed.png`
- `tmp/ai-usage-simulator-breakdown-drilldown-fixed.png`

## Handoff

- Report changed files, verification, and simulator-only screenshot if run.
