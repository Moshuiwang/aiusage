# AI Review Request

## Scope

review_selection:
  selection_mode: user
  risk_score: 6
  selected_target: files:docs/product/watch-companion-testflight-prd.md,docs/architecture/watch-companion-testflight.md,docs/task-packages/v2/TP-V2-083-watch-companion-testflight.md
  selected_mode: local
  input_form: request_artifact
  selected_model_policy: highest
  selected_depth: standard
  selected_rounds: 1
  branch_gate:
    current_branch: codex/watch-companion-testflight
    default_branch: main
    allowed: true
    reason: local read-only review on non-default branch
  actual_reviewer: claude
  actual_model: opus
  model_resolution:
    kind: local-claude-default
    value: opus
  depth_resolution:
    kind: cli_args
    value: ["--effort", "xhigh"]
    confidence: exact
  scope: re-review revised Watch/TestFlight planning docs plus minimal integration references
  rounds_completed: 0
  reasons:
    - user requested another Claude Review after fixes
    - verify previous findings are actually closed before implementation starts
    - docs define TestFlight install, Watch companion, watch face WidgetKit accessory, and data-boundary promises

Review these revised docs:

- `docs/product/watch-companion-testflight-prd.md`
- `docs/architecture/watch-companion-testflight.md`
- `docs/task-packages/v2/TP-V2-083-watch-companion-testflight.md`

Also inspect these integration references only for link/status consistency:

- `docs/product-brief.md`
- `docs/architecture/architecture.md`
- `docs/task-packages/v2/INDEX.md`

## Repo State

Current branch: `codex/watch-companion-testflight`
Default branch: `origin/main`
HEAD: `929fa0d`

Dirty state:

```text
## codex/watch-companion-testflight...origin/main
 M docs/architecture/architecture.md
 M docs/product-brief.md
 M docs/task-packages/v2/INDEX.md
?? docs/architecture/watch-companion-testflight.md
?? docs/product/
?? docs/task-packages/v2/TP-V2-083-watch-companion-testflight.md
?? reviews/
```

Previous review report:

- `reviews/20260621-193251-codex-watch-companion-testflight-local-929fa0d-wctf01.md`

Previous confirmed findings that should now be checked for closure:

1. Watch face implementation path was underspecified; docs needed an embedded watchOS WidgetKit extension, not only the existing iOS widget extension.
2. Stale threshold conflicted with current Watch code: docs said 30 minutes while current implementation uses 2 hours.
3. Watch face family language was not TDD-actionable; docs needed concrete WidgetKit accessory families.
4. Verification could pass without proving the headline user experience: companion install shape and watch face accessory.
5. Docs blurred TP-V2-070 already-delivered MobileSummary sync with this round's new work.

Local prechecks already run after edits:

```text
rg -n "Modular|complication/widget|ClockKit|watch-supported" <target docs>
# no matches

test -f docs/product/watch-companion-testflight-prd.md
test -f docs/architecture/watch-companion-testflight.md
test -f docs/task-packages/v2/TP-V2-083-watch-companion-testflight.md
# all passed

git diff --check
# passed
```

## Review Instructions

Treat this as read-only review. Do not modify files.

Use a high bar. Report only findings tied to this re-review scope. Include severity, file/path, evidence, user impact, and suggested fix.

First answer whether the five previous findings are closed, partially closed, or still open. Then report any new actionable findings.

Prioritize user-facing risks:

- The owner still may not get a manageable Watch companion through TestFlight.
- The watch face editor still may not expose `AI Usage` as a WidgetKit accessory.
- The docs still may suggest two parallel iPhone-to-Watch data contracts.
- The task package still may not be TDD-actionable for the next implementation agent.
- The docs may still create a false freshness expectation.
- The docs may still violate project boundaries: no Watch-side token, no Watch-side collection, no new server endpoint unless separately approved.

Ignore unrelated historical repo issues. Do not read or output secrets, `.env`, tokens, SSH keys, production config, raw `.claude`, or raw `.codex` logs.

If there are no actionable findings, say no actionable findings and list residual manual verification gaps.

## Target Content

Read the target files directly from the working tree:

```text
docs/product/watch-companion-testflight-prd.md
docs/architecture/watch-companion-testflight.md
docs/task-packages/v2/TP-V2-083-watch-companion-testflight.md
docs/product-brief.md
docs/architecture/architecture.md
docs/task-packages/v2/INDEX.md
```

Key intended corrections to verify:

- PRD now says the watch face surface is a watchOS WidgetKit extension embedded in the Watch App.
- PRD and task package list `.accessoryRectangular`, `.accessoryCircular`, and `.accessoryInline`.
- Architecture says TP-V2-070 MobileSummary sync is baseline and avoids a second long-lived iPhone-to-Watch data contract.
- Architecture keeps stale threshold at 2 hours unless a future task explicitly changes it.
- Task package red tests now require companion relationship, watchOS WidgetKit extension, accessory families, watch-local cache, and no Watch-side server/token/collector/provider behavior.

## Out Of Scope

- Full repo architecture review.
- Existing code implementation review beyond checking whether docs conflict with known target shapes.
- Production deploy, Cloudflare migration, or server endpoint changes.
- Secrets, credentials, `.env`, raw usage logs, raw `.claude`, raw `.codex`, SSH keys, or production account files.
