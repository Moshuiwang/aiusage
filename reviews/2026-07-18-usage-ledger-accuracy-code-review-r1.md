# Usage Ledger Accuracy Code Review R1

Result: changes_requested

- P0: report digest was not cryptographically bound to the submitted hourly facts.
- P1: an explicit zero-fact coverage could verify without reconciling stale facts.
- P1: sessionless active/archive copies could escape cross-file exact dedupe.
- P1: a legacy collector push could retain an earlier verified state.
- P1: the Python SQLite path did not implement the accuracy/reconciliation contract.

All five findings were addressed before R2.
