# TP-V2-071 Multi Platform Data And Design Verification

Version: V2
ID: TP-V2-071
Status: ready
Type: verification
Depends on: TP-V2-066, TP-V2-069, TP-V2-070, TP-V2-073, TP-V2-074, TP-V2-075, TP-V2-076, TP-V2-077, TP-V2-078, TP-V2-079, TP-V2-080
Parallel with: none

## Goal

Verify that Web, the accepted iOS TP-V2-073 to TP-V2-080 line, iOS Widget, and Watch show accurate data and match the accepted product direction.

## Context

The user requires data accuracy and design fidelity, not just builds passing. Anti Gravity via `agy` is available and should be used for testing/inspection.

## Scope

- Compare UI totals, period windows, trend buckets, source rows, and limits against API responses and SQLite where needed.
- Use `agy --model gemini-3.5-flash` for independent test/inspection.
- Capture screenshots for Web, iOS App, iOS Widget, and Watch.
- Verify light/dark where supported.

## Out of Scope

- Do not write production data.
- Do not expose tokens or local secrets in artifacts.

## Red Test

- Create a verification checklist that fails until each surface has screenshot evidence and API/data evidence.

## Implementation

1. Start local server or use authenticated production read-only endpoint only when safe.
2. Capture `/api/summary` and `/api/mobile/summary` for the same period.
3. Compare displayed values against API/DB facts.
4. Run `agy` review over screenshots/checklist.
5. Fix confirmed mismatches.

## Acceptance Criteria

- All surfaces show the same total for the same period.
- Period boundaries use service timezone.
- Official limits are not faked.
- Source failures remain visible.
- UI matches the design package closely enough for product acceptance.

## Verification

```bash
agy --model gemini-3.5-flash --print "Review the multi-platform verification checklist and screenshot evidence for data/design mismatches." --print-timeout 10m
PYTHONPATH=src python3 -m unittest -v
cd mobile/ios && swift test
cd clients/macos && swift test
git diff --check
```

## Handoff

- Attach screenshot paths.
- Attach data comparison summary.
- List any accepted residual visual differences.
