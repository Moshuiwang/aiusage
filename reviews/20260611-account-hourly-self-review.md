# Self Review: Account Hourly Usage Fixes

## Scope

Reviewed the post-AI-review fixes for account hourly usage, summary snapshot isolation, idempotency, and deployment docs.

## Checks

- Confirmed `/api/summary` and `/api/mobile/summary` now build request snapshots in unique temporary files instead of overwriting shared `latest.json`.
- Confirmed `_atomic_write` uses a unique temporary file name before `os.replace`.
- Confirmed `usage_hourly_facts` has a logical unique index for source, agent, client, window, account, confidence, and provenance.
- Confirmed logical-hour upsert replaces model breakdown rows for both previous and replacement `fact_id`.
- Confirmed `account_hourly.by_ai_account` exposes per-account `confidence_breakdown` and `attribution_confidence`.
- Confirmed account-hourly period filtering parses timestamps and compares dates in the configured timezone.
- Confirmed missing host no longer becomes the literal string `"None"`.
- Confirmed docs no longer advertise `facts_replaced` and mark `source_status_hourly` / `collector_cursors` as deferred.

## Verification

```bash
PYTHONPATH=src python3 -m pytest
```

Result: 199 passed.

## Remaining Risk

- Automatic Codex / Claude account discovery is still deferred.
- Dashboard / iPhone UI for `account_hourly` is still deferred.
- Production deployment still needs server smoke after restart.
