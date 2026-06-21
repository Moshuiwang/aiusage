# AI Review Report

## Selection

```yaml
review_selection:
  selection_mode: auto
  risk_score: 8
  selected_target: files:cloudflare/README.md,cloudflare/aiusage-api-worker.js,docs/task-packages/v2/TP-V2-083-cloudflare-entrypoint-migration.md,docs/task-packages/v2/INDEX.md,package.json,tests/test_cloudflare_deployment.py,wrangler.toml
  selected_mode: local
  input_form: request_artifact
  selected_model_policy: highest
  selected_depth: standard
  selected_rounds: 1
  branch_gate:
    current_branch: codex/cloudflare-aiusage-migration
    default_branch: main
    allowed: true
    reason: local read-only review on feature branch with explicit scoped target
  actual_reviewer: claude
  actual_model: opus
  model_resolution:
    kind: local-claude-default
    value: opus
  depth_resolution:
    kind: cli_args
    value: ["--effort", "xhigh"]
    confidence: exact
  scope: origin/main plus current uncommitted Cloudflare files
  rounds_completed: 1
```

## Reviewer Output

Request artifact:

- `reviews/20260621-214554-codex-cloudflare-aiusage-migration-request-0f94445-cf001.md`

Claude reported seven scoped findings:

- HIGH: Pages-served dashboard would load without CSS/JS because deployed static root does not match `/static/...` asset URLs.
- HIGH: Web dashboard login is not reachable because `/login` remains a server-side flow, while Pages is static and Worker only routes `/api/*`, `/ingest`, and `/ingest-limits`.
- MEDIUM: `/ingest` POST body may fail through Worker if Cloudflare changes transfer/body framing and the Python origin expects `Content-Length`.
- MEDIUM: `https://vpn2.chunbai.com:8443` TLS trust must be live-verified from Cloudflare Worker.
- MEDIUM: tests mostly assert file strings and do not catch the dashboard serving/login breakage.
- LOW: production hostname is tied to development-named Cloudflare resources and no staging/rollback split.
- LOW: static dashboard shell becomes publicly visible and bare `/api` probe branch is likely dead.

## Triage

Confirmed:

```yaml
findings:
  - id: R1
    reviewer_severity: HIGH
    confirmed_severity: P1
    file: package.json
    source: introduced
    summary: Pages deploy command publishes static files at root while index.html references /static assets.
    evidence: The deploy script publishes src/ai_usage_widget/static, but dashboard HTML uses /static/dashboard.css and /static/dashboard.js.
    action: pending_fix
  - id: R2
    reviewer_severity: HIGH
    confirmed_severity: P1
    file: wrangler.toml
    source: introduced
    summary: Web login flow is not handled by Pages or current Worker routes.
    evidence: /login is a server-side POST/session endpoint, while current Worker routes only /api/*, /ingest, and /ingest-limits.
    action: pending_fix
  - id: R3
    reviewer_severity: MEDIUM
    confirmed_severity: P2
    file: cloudflare/aiusage-api-worker.js
    source: exposed
    summary: Ingest POST body behavior needs explicit Worker/origin verification.
    evidence: Origin reads Content-Length, while Worker stream forwarding may not preserve the same body framing.
    action: pending_fix_or_live_verification
  - id: R4
    reviewer_severity: MEDIUM
    confirmed_severity: P2
    file: wrangler.toml
    source: exposed
    summary: Origin TLS trust on vpn2.chunbai.com:8443 is an unverified cutover dependency.
    evidence: Worker subrequests require Cloudflare-trusted TLS; this cannot be proven from static repo files.
    action: live_verification_required
  - id: R5
    reviewer_severity: MEDIUM
    confirmed_severity: P2
    file: tests/test_cloudflare_deployment.py
    source: introduced
    summary: Current tests do not catch the main Web Dashboard serving and login gaps.
    evidence: Tests check string presence and file existence, not served asset paths, login routing, or proxy execution.
    action: pending_fix
```

Accepted lower-risk observations:

```yaml
findings:
  - id: R6
    reviewer_severity: LOW
    confirmed_severity: P3
    file: wrangler.toml
    source: introduced
    summary: Development-named Cloudflare resources are bound to production hostname routes.
    evidence: This matches the current dev/aggressive-cutover task context, but should remain explicit.
    action: accepted_risk_for_dev_cutover
  - id: R7
    reviewer_severity: LOW
    confirmed_severity: P3
    file: cloudflare/aiusage-api-worker.js
    source: introduced
    summary: Bare /api probe branch is likely dead under the current route pattern.
    evidence: Route is /api/*, which may not match slash-less /api.
    action: defer_or_cleanup
```

## Fixes

No fixes were made in this review step.

## Verification

Previously run before review:

```bash
PYTHONPATH=src python3 -m unittest tests.test_cloudflare_deployment tests.test_dashboard_static -v
```

Result:

```text
Ran 12 tests
OK
```

No additional tests were run after this report because no code fix was applied yet.

## Remaining Risk

The current Cloudflare implementation is not ready for user-facing cutover. It is a useful first implementation, but the Web Dashboard path needs design correction before deployment:

- either proxy web root/login/static paths to the origin through Worker for now,
- or add a real Cloudflare Pages/Functions-compatible login and static asset layout,
- then strengthen tests to catch the selected behavior.

Mobile API proxy behavior appears closer to usable, but write-path ingest and TLS must still be verified live.
