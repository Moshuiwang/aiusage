# Usage Ledger Accuracy Code Review R2

Result: changes_requested

- P0: a cumulative state seen-set spanning resets could drop a legitimate event when a new epoch returned to an older state.
- P0: explicit coverage constrained digest/reconciliation but did not constrain fact upserts.
- P1: consecutive full scans did not bind provenance, so different provenance values could combine into a verified pair.
- P1: Python escaped non-ASCII canonical JSON while TypeScript hashed UTF-8 JSON directly.

The coverage, provenance and UTF-8 findings were fixed and have passing Python and Native Worker tests. The parser was changed to use reset epochs; final review remains open while validating current Codex cumulative semantics against real data.
