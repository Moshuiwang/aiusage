# TP-V2-043 Mobile Summary API Contract

Version: V2
ID: TP-V2-043
Status: done
Type: implementation
Depends on: TP-V2-010, TP-V2-020, mobile app prototype approval
Parallel with: none

## Goal

Add a read-only mobile summary API contract that maps the canonical snapshot into the iPhone App surfaces: Home, Sources, Breakdown, and Limits.

## Context

The Web prototype under `docs/prototypes/mobile-app/` is approved as the first mobile information architecture. The native App should not decode the full Web dashboard snapshot directly. It needs a smaller stable contract that preserves source provenance, rolling period semantics, trend tooltip data, source health, drilldown groups, and observed/missing limits.

## Scope

- Add a pure transformer from existing snapshot JSON to a mobile summary DTO.
- Add authenticated `GET /api/mobile/summary` with the same `date`, `period`, `machine`, and `account` filters as `/api/summary`.
- Reuse `build_snapshot`; do not read SQLite directly from the transformer.
- Add unit tests for auth, period semantics, sections, trend tooltip fields, source health, breakdown, and limits.
- Allowed files:
  - `src/ai_usage_widget/server.py`
  - `src/ai_usage_widget/mobile_summary.py`
  - `tests/test_web_server.py`
  - this task package and V2 index.

## Out of Scope

- No SwiftUI or WidgetKit code.
- No new write endpoint.
- No production token or local config changes.
- No new official limits provider behavior.
- No mobile device authentication redesign beyond existing bearer/cookie auth.

## Red Test

- Add a web server test that requests `/api/mobile/summary?date=2026-06-02&period=week` after fixture ingest and asserts:
  - unauthenticated access is rejected.
  - payload has `schema_version: 1` and `client: "ios"`.
  - `period.id == "week"` and the start/end dates match rolling 7 days.
  - trend points expose input/output/cache/cache_ratio for tooltip use.
  - source health rows include machine and OS user labels.
  - breakdown includes machine, OS user, agent, and date lists.
  - limits include observed and missing confidence without estimating quota.

## Implementation

- Implement `build_mobile_summary(snapshot: dict) -> dict`.
- Add `handle_get_mobile_summary` in `server.py`.
- Route `/api/mobile/summary` through existing auth and snapshot rebuild path.
- Keep the DTO deterministic and JSON-serializable with `ensure_ascii=False`.

## Acceptance Criteria

- Mobile summary is read-only and derived from canonical snapshot/API fields.
- Missing limits remain explicit and are not converted to observed quota.
- Trend points include token type detail needed by mobile tooltip.
- Existing `/api/summary` behavior remains unchanged.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_web_server -v
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Handoff

- Report changed files and test commands.
- If done, mark this task package `done` and leave TP-V2-044 as the next implementation task.
