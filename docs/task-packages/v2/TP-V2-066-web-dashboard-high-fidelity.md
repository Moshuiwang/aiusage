# TP-V2-066 Web Dashboard High Fidelity

Version: V2
ID: TP-V2-066
Status: ready
Type: implementation
Depends on: TP-V2-065
Parallel with: TP-V2-067, TP-V2-068, TP-V2-069

## Goal

Align the Web Dashboard with the latest `web-dashboard.html` design while preserving accurate `/api/summary` data.

## Context

Web remains the full viewing entry. It must show global period totals, trend, official observed limits, and source contribution without changing collection behavior.

## Scope

- Update `src/ai_usage_widget/static/index.html`.
- Update `src/ai_usage_widget/static/dashboard.css`.
- Update `src/ai_usage_widget/static/dashboard.js`.
- Add or update Web static tests and screenshot smoke checks.

## Out of Scope

- Do not change `/ingest` or collection.
- Do not make Web calculate official quota from usage history.
- Do not require new API fields unless a failing test proves existing data cannot support the design.

## Red Test

- Add a failing test asserting Web has the new icon, four-period segmented control, hero total, bar trend chart, quota section, and source cards.
- Add a failing test or fixture check proving period changes fetch the matching `period` and do not apply machine/account filters to the main total.

## Implementation

1. Map current `/api/summary` fields to the high-fidelity layout.
2. Implement dual-ring quota cards from official observed limits only.
3. Implement bar chart with data-derived ceiling.
4. Preserve stale/failure source states.
5. Run local browser screenshot checks.

## Acceptance Criteria

- Web visually matches the design package at desktop and mobile widths.
- Totals, trend, source contribution, and limits match `/api/summary`.
- Missing limits degrade clearly.
- Dashboard remains usable in light and dark modes.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_web_server tests.test_mobile_prototype -v
python3 -m http.server 8788 --bind 127.0.0.1 --directory src/ai_usage_widget/static
git diff --check
```

## Handoff

- Report changed Web files.
- Attach desktop/mobile screenshots.
- State any API field gaps found.
