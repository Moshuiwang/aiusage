# AI Review Request

## Scope

Review only the Cloudflare migration fix after `cf001`.

Included files:

- `cloudflare/README.md`
- `cloudflare/OPERATIONS_HANDOFF.md`
- `cloudflare/aiusage-api-worker.js`
- `docs/task-packages/v2/TP-V2-083-cloudflare-entrypoint-migration.md`
- `docs/task-packages/v2/INDEX.md`
- `package.json`
- `tests/test_cloudflare_deployment.py`
- `wrangler.toml`

Do not review Apple Watch, iOS, historical dashboard styling, or unrelated repo code except when needed to verify current origin route compatibility.

## Repo State

Current branch:

```text
codex/cloudflare-aiusage-migration
```

Base:

```text
origin/main at 0f94445 实现 Apple Watch companion TestFlight 支持
```

Current status:

```text
 M docs/task-packages/v2/INDEX.md
?? cloudflare/
?? docs/task-packages/v2/TP-V2-083-cloudflare-entrypoint-migration.md
?? package.json
?? reviews/20260621-214554-codex-cloudflare-aiusage-migration-local-0f94445-cf001.md
?? reviews/20260621-214554-codex-cloudflare-aiusage-migration-request-0f94445-cf001.md
?? tests/test_cloudflare_deployment.py
?? wrangler.toml
```

Relevant local verification:

```bash
PYTHONPATH=src python3 -m unittest tests.test_cloudflare_deployment tests.test_dashboard_static -v
```

Result:

```text
Ran 13 tests
OK
```

Whitespace check:

```bash
git diff --check
```

Result: OK.

## What Changed Since cf001

The first review found that Pages static hosting would break the dashboard and login. The implementation was changed to a safer short-term strategy:

- Worker route now covers `aiusage.chunbai.com/*`.
- Worker proxies `/`, `/dashboard`, `/login`, `/static/*`, `/api/*`, `/ingest`, and `/ingest-limits` to the existing Python origin.
- Worker reads non-GET/HEAD request bodies with `await request.arrayBuffer()` before proxying.
- Task package and README now state that Pages staticization is a later task, not this round's success path.
- `cloudflare/OPERATIONS_HANDOFF.md` points real Cloudflare deployment to the sibling `/Users/wangzhipeng/Documents/cloud-flare` Codex CLI entrypoint and forbids leaking `.env` or tokens.

## Review Instructions

Read-only review. Do not edit files.

Return only actionable findings tied to the included Cloudflare scope. Re-check the cf001 issues specifically:

- Web dashboard should not break because of Pages asset path mismatch.
- `/login` should be handled by Worker/origin and remain usable.
- `/static/dashboard.css` and `/static/dashboard.js` should be reachable under `aiusage.chunbai.com`.
- `/api/*`, `/ingest`, and `/ingest-limits` should remain protected from cache leakage.
- POST body forwarding should be compatible with the current Python origin as much as possible before live verification.
- The handoff to `/Users/wangzhipeng/Documents/cloud-flare` should not leak secrets and should be operationally clear.

For every finding, include severity, file/path, evidence, and user impact. If there are no actionable findings, say so and list residual live-verification gaps.

## Out Of Scope

- Reading or outputting `.env`, Cloudflare tokens, ingest tokens, SQLite DB, local configs, `.claude`, `.codex`, or raw usage logs.
- Actually deploying Cloudflare resources.
- Cloudflare Tunnel setup.
- D1 migration or Worker-native ingest rewrite.
- Broad style refactors.
