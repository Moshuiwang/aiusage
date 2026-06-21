# AI Review Request

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
  rounds_completed: 0
  reasons:
    - Cloudflare Worker and deployment config touch production entrypoint behavior.
    - Existing local tests passed, but no prior scoped Cloudflare review exists.
```

## Scope

Review only the current Cloudflare entrypoint migration changes in this worktree.

Included files:

- `cloudflare/README.md`
- `cloudflare/aiusage-api-worker.js`
- `docs/task-packages/v2/TP-V2-083-cloudflare-entrypoint-migration.md`
- `docs/task-packages/v2/INDEX.md`
- `package.json`
- `tests/test_cloudflare_deployment.py`
- `wrangler.toml`

The product goal is to move `aiusage.chunbai.com` from a placeholder entrypoint to a deployable Cloudflare shape:

- Pages serves the existing real dashboard static directory.
- Worker handles `/api/*`, `/ingest`, and `/ingest-limits`.
- Worker proxies those business paths to the existing origin service at `https://vpn2.chunbai.com:8443`.
- This task does not migrate SQLite to D1 and does not rewrite ingest in Worker-native code.

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
?? tests/test_cloudflare_deployment.py
?? wrangler.toml
```

Relevant local verification already run:

```bash
PYTHONPATH=src python3 -m unittest tests.test_cloudflare_deployment tests.test_dashboard_static -v
```

Result:

```text
Ran 12 tests
OK
```

## Review Instructions

Read-only review. Do not edit files.

Return only actionable findings tied to the included Cloudflare scope. Prioritize user-visible and deployment-impacting issues:

- route behavior for `aiusage.chunbai.com`
- whether the dashboard can actually be served by Pages
- whether Worker proxy behavior is safe and compatible with current origin behavior
- cache behavior for authenticated API and ingest paths
- secret/token safety
- deployability through `wrangler`
- whether tests meaningfully cover the migration contract

For every finding, include severity, file/path, evidence, and user impact. If no actionable findings exist, say so and list residual test or live-verification gaps.

## Out Of Scope

- Apple Watch / iOS / TestFlight implementation.
- Historical repository issues outside the listed files.
- D1 data migration design.
- Cloudflare Tunnel setup.
- Any production credential, token, `.env`, local config, SQLite DB, `.claude`, or `.codex` content.
- Style-only suggestions and broad refactors.
