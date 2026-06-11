# AI Review Report

## Selection

```yaml
review_selection:
  selection_mode: auto
  risk_score: 8
  selected_target: diff/files:account-hourly implementation and docs
  selected_mode: local
  input_form: request_artifact
  selected_model_policy: highest
  selected_depth: standard
  selected_rounds: 1
  branch_gate:
    current_branch: codex/ui
    default_branch: main
    allowed: true
    reason: local read-only review with explicit scope
  actual_reviewer: claude
  actual_model: opus
  model_resolution:
    kind: local-claude-default
    value: opus
  depth_resolution:
    kind: cli_args
    value: ["--effort", "xhigh"]
    confidence: exact
  scope: targeted dirty files plus account-hourly docs
  request_artifact: reviews/20260611-141256-codex-ui-dirty-account-hourly-request.md
  rounds_completed: 1
  reasons:
    - database schema and API contract change
    - production deployment docs included
    - full local pytest passed before review
```

## Reviewer Output

Claude reviewed the request artifact and returned scoped findings. Raw output was not copied verbatim in full; findings below are triaged against the current working tree.

## Triage

### R1

```yaml
id: R1
reviewer_severity: P2
confirmed_severity: P2
file: src/ai_usage_widget/snapshot_builder.py
line: 760
source: introduced
summary: account_hourly.by_ai_account mixes attribution confidence levels without per-account confidence detail.
evidence: _account_hourly_summary aggregates all rows into by_ai_account and only exposes confidence_breakdown globally. A UI cannot tell whether one account row is observed, inferred, unknown, or mixed.
action: accepted_for_followup
```

Impact: this can make inferred account attribution look stronger than it is. This directly conflicts with the product rule that uncertain attribution must not be shown as a strong conclusion.

### R2

```yaml
id: R2
reviewer_severity: P3
confirmed_severity: P2
file: src/ai_usage_widget/storage_sqlite.py
line: 206
source: introduced
summary: usage_hourly_facts lacks the documented logical-hour unique constraint.
evidence: table only has fact_id primary key and non-unique indexes; _upsert_hourly_fact uses ON CONFLICT(fact_id). If two collectors produce different fact_id strings for the same logical hour/account tuple, account_hourly can double-count.
action: accepted_for_followup
```

Impact: this is more than cosmetic because the product depends on hourly facts being idempotent across machines and future collectors.

### R3

```yaml
id: R3
reviewer_severity: P3
confirmed_severity: P3
file: src/ai_usage_widget/snapshot_builder.py
line: 722
source: introduced
summary: account-hourly date filtering compares timestamp strings with offsets lexicographically.
evidence: _fetch_account_hourly_rows builds bare local date bounds like 2026-06-11T00:00:00 and compares them to window_start values such as 2026-06-11T13:00:00+08:00.
action: accepted_for_followup
```

Impact: fine for the current same-timezone personal deployment, risky when different machines/users report different offsets.

### R4

```yaml
id: R4
reviewer_severity: P3
confirmed_severity: P3
file: src/ai_usage_widget/normalize.py
line: 308
source: introduced
summary: missing host can persist as literal string "None".
evidence: normalize_ingest_hourly_facts uses str(row_device.get("host") or device["host"]); if host is absent this becomes "None".
action: accepted_for_followup
```

Impact: low, but creates sticky bad machine metadata.

### R5

```yaml
id: R5
reviewer_severity: P2
confirmed_severity: P3
file: src/ai_usage_widget/server.py
line: 321
source: exposed
summary: mobile/summary and summary rebuild filtered snapshots into shared latest_path; _atomic_write uses a fixed tmp file.
evidence: handle_get_mobile_summary and handle_get_summary both call build_snapshot with output_path=self.server.latest_path. _atomic_write uses out_path.with_suffix(".tmp"). Filtered reads can overwrite canonical latest.json; concurrent writes can collide.
action: accepted_for_followup
```

Impact: valid issue, but not caused by the new account_hourly code path itself. It is an existing snapshot-serving pattern exposed by the review scope. Should be fixed before relying on heavier mobile/dashboard polling.

### R6

```yaml
id: R6
reviewer_severity: P3
confirmed_severity: P3
file: docs/account-hourly-usage-interface.md
line: 0
source: introduced
summary: interface doc still mentions facts_replaced but response only implements facts_accepted.
evidence: IngestResponse.to_dict returns facts_accepted but no facts_replaced.
action: accepted_for_followup
```

Impact: doc/contract mismatch for deployment smoke and client implementers.

### R7

```yaml
id: R7
reviewer_severity: P3
confirmed_severity: P3
file: docs/account-hourly-usage-database.md
line: 0
source: introduced
summary: DB design describes FK/source_status_hourly/collector_cursors that are not implemented in this first slice.
evidence: implementation creates machines, os_identities, ai_accounts, usage_hourly_facts, usage_hourly_models only.
action: accepted_for_followup
```

Impact: acceptable if explicitly documented as deferred; otherwise deployment readers may assume operational status/cursor support exists.

## Fixes

No fixes were applied in this review run. User requested review only.

## Verification

Pre-review verification already run:

```bash
PYTHONPATH=src python3 -m pytest
```

Result: 195 passed.

No tests were run after review because no code changes were made.

## Remaining Risk

Highest priority follow-up before production deployment:

1. Add per-account confidence detail or split strong/inferred account ranking.
2. Add logical-hour idempotency constraint/upsert behavior for usage_hourly_facts.
3. Update docs to mark deferred DB/status/cursor pieces and remove or implement facts_replaced.
4. Fix shared latest_path snapshot writes before heavier mobile/dashboard polling.
