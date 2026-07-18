# AI Review Request

## Scope

- Target: diff
- Branch: `codex/github-usage-ledger-accuracy`
- Base ref: `origin/main`
- Scope: `origin/main...HEAD`
- Mode: local, read-only Codex subagent
- Depth: deep
- Rounds: 1 requested subagent review
- Head: `a695ddfe5ae25b1f326ae137ccb795d545f078f9`

## Repo State

- Working tree was clean before this request artifact was created.
- The branch is 5 commits ahead of GitHub `origin/main`.
- Diff: 38 files, about 2,456 insertions and 38 deletions.
- Main behavior change: Usage Ledger accuracy, cumulative Codex delta dedupe, full-scan retry idempotency, storage and Cloudflare parity, related contracts/tests, plus GitHub repository-entry documentation.
- Existing review evidence is under `reviews/`, including `reviews/20260718-095300-local-e041cb3-fnl001.md`.

## Review Instructions

Perform a read-only review of `origin/main...HEAD`. Report only actionable findings introduced or exposed by this diff. Focus on data double-counting, idempotency, incremental/full-scan boundaries, SQLite/Cloudflare parity, schema migration safety, API contract drift, and sensitive-data boundaries. For each finding include severity (P0-P3), file and line, evidence, and user-visible impact. If there are no actionable findings, say so and list residual test or deployment gaps.

Do not edit files. Do not read production account files, tokens, local source config, raw Claude/Codex logs, or generated usage data. Do not expand into unrelated historical issues.

## Target Content

Inspect the committed diff directly with:

```bash
git diff --stat origin/main...HEAD
git diff origin/main...HEAD
git log --oneline origin/main..HEAD
```

## Out Of Scope

- Production access or deployment.
- Reading raw usage logs or secret-bearing local configuration.
- Unrelated historical repository issues.
- Editing or fixing findings; return review findings only.
