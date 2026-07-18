# AI Review Result: Usage Ledger Accuracy Docs R1

Run ID: 20260718-usage-ledger-accuracy-docs-r1
Reviewer: independent Codex reviewer (Claude preflight unavailable: not logged in)
Verdict: changes required before implementation

## Blocking Findings

1. TP-V2-105 did not define stable chronological ordering, a pre-window cumulative seed, or isolation for files without a session id. Implementing the original wording could still overcount or undercount.
2. TP-V2-107 only described upsert. If a formerly stored hour becomes empty after dedupe, the old server fact would remain forever without authoritative snapshot reconciliation.
3. TP-V2-106 did not define who may declare `verified`, where two-run evidence is stored, or how zero-usage sources carry accuracy metadata.
4. TP-V2-107 did not isolate the canary from the shared release, stop concurrent timer writes, or define a D1 rollback boundary.

## Resolution

The three task packages were updated before implementation to require chronological seeding, server-side reconciliation, a server-owned accuracy state machine, zero-usage source support, isolated canary execution, paused timers, and bounded D1 rollback evidence.

## R2 Gate

Implementation may start only after the updated wording is re-reviewed and no blocking finding remains.
