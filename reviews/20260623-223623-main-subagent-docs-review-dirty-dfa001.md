# AI Review Report

## Selection

```yaml
review_selection:
  selection_mode: user
  selected_target: files:
    - docs/product/data-freshness-accuracy-prd.md
    - docs/architecture/data-freshness-accuracy.md
    - docs/architecture/data-freshness-accuracy-database.md
    - docs/architecture/data-freshness-accuracy-interfaces.md
    - docs/task-packages/v2/TP-V2-097-data-freshness-accuracy-contract.md
    - docs/architecture/database.md
    - docs/architecture/interfaces.md
    - docs/task-packages/v2/INDEX.md
  selected_mode: local_subagent
  selected_model_policy: exact:gpt-5.5
  selected_depth: exact:xhigh
  service_tier: priority
  rounds_completed: 1
  branch_gate:
    current_branch: main
    default_branch: main
    allowed: true
    reason: read-only local subagent review of explicit document files
  actual_reviewer: multi_agent reviewer subagent
  actual_model: gpt-5.5
  depth_resolution:
    kind: tool_args
    value: ["reasoning_effort=xhigh", "service_tier=priority"]
    confidence: exact
```

## Reviewer Output

The subagent reported four findings:

1. P1: The broader working tree is not docs-only because existing Cloudflare/native code and dependency changes are present.
2. P1: Generated/dependency files such as `node_modules/`, `pnpm-lock.yaml`, and `pnpm-workspace.yaml` are untracked and could pollute a docs-only commit.
3. P1: Watch cache acceptance wording was too weak because it could allow context-only evidence to pass.
4. P2: `INDEX.md` includes existing TP-V2-086 through TP-V2-096 entries; this may be broader than the data-accuracy docs-only scope if committed together without the corresponding Cloudflare migration context.

## Triage

- Confirmed P1: Watch cache acceptance wording was too weak.
  Action: fixed in `docs/product/data-freshness-accuracy-prd.md` and `docs/task-packages/v2/TP-V2-097-data-freshness-accuracy-contract.md`.

- Confirmed P1/P2: The current working tree contains unrelated Cloudflare/native and dependency changes.
  Action: not modified. These were pre-existing/unrelated to this docs pass and should be kept out of any docs-only commit.

- Confirmed P2: `INDEX.md` already carries TP-V2-086 through TP-V2-096 additions in the dirty tree.
  Action: noted. This pass only appended TP-V2-097; any commit should stage intentionally.

## Fixes

- Strengthened Watch evidence wording so Watch acceptance requires a decodable Watch App Group `last-watch-summary.json`, or a receipt that explicitly proves the same `generated_at` summary was written to Watch cache.
- Clarified that iPhone cache or WatchConnectivity context cannot substitute for Watch local cache evidence.

## Verification

```bash
rg -n '至少两层证据|Watch cache 或 Watch receipt|不能用 iPhone cache|receipt 必须明确|Watch App Group' docs/product/data-freshness-accuracy-prd.md docs/task-packages/v2/TP-V2-097-data-freshness-accuracy-contract.md
git diff --check -- docs/product/data-freshness-accuracy-prd.md docs/task-packages/v2/TP-V2-097-data-freshness-accuracy-contract.md docs/architecture/database.md docs/architecture/interfaces.md docs/task-packages/v2/INDEX.md
```

Both checks passed after the wording fix.

## Remaining Risk

- Do not treat the whole current working tree as a docs-only change. Stage only the intended documentation files when committing.
- The Cloudflare/native task rows in `INDEX.md` need to remain tied to their corresponding migration work if they are committed.
