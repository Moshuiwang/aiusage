# AI Review Request

## Scope

Review the multi-platform design planning documents for AI Usage Widget before implementation begins.

Target documents:

- `docs/multi-platform-design-prd.md`
- `docs/multi-platform-design-architecture.md`
- `docs/multi-platform-design-database.md`
- `docs/multi-platform-design-interface.md`

Supporting context:

- `docs/status.md`
- `docs/task-packages/README.md`
- `docs/task-packages/RULES.md`
- `docs/task-packages/v2/INDEX.md`
- `docs/architecture/client-platforms.md`
- `docs/prototypes/ios-high-fidelity/HANDOFF.md`

## Selection

```yaml
review_selection:
  selection_mode: user
  risk_score: 7
  selected_target: plan:docs/multi-platform-design-prd.md,docs/multi-platform-design-architecture.md,docs/multi-platform-design-database.md,docs/multi-platform-design-interface.md
  selected_mode: local
  input_form: request_artifact
  selected_model_policy: highest
  selected_depth: standard
  selected_rounds: 2
  branch_gate:
    current_branch: codex/multi-platform-ai-usage
    default_branch: main
    allowed: true
    reason: artifact-backed local read-only review on a feature branch
  actual_reviewer: claude
  actual_model: opus
  model_resolution:
    kind: local-claude-default
    value: opus
  depth_resolution:
    kind: cli_args
    value: ["--effort", "xhigh"]
    confidence: exact
  scope: document set before implementation
  rounds_completed: 0
  reasons:
    - user requested AI Review before coding
    - multi-client UX, API, database, and deployment implications
    - review must stay read-only and avoid secrets
```

## Repo State

Current branch: `codex/multi-platform-ai-usage`

Dirty state at request creation:

```text
 M README.md
?? .codex/config.toml
?? docs/multi-platform-design-architecture.md
?? docs/multi-platform-design-database.md
?? docs/multi-platform-design-interface.md
?? docs/multi-platform-design-prd.md
```

Notes:

- `.codex/config.toml` is unrelated local state. Do not read, review, or mention its contents.
- The design source is the user-provided zip at `/Users/wangzhipeng/Downloads/AI Usage Widget.zip`, previously summarized into the target documents. Do not unzip or modify it during review unless strictly necessary.
- No code implementation has started for this task.

## Review Instructions

Read-only review. Report only findings tied to the target documents and the stated implementation goal:

- Complete Web Dashboard, macOS popover, iOS App, iOS Widget, and Apple Watch code against the latest design package.
- Data must be accurate across totals, periods, trends, sources, and limits.
- UI must match the new design package, including icon assets.
- Future implementation must preserve project boundaries: clients are read-only, no SSH, no direct raw `.claude` / `.codex` log reads by presentation clients, no production secrets in repo.

Return findings first. For each finding include:

- Severity: P0 / P1 / P2 / P3.
- Document path and section.
- Evidence from the document.
- User impact.
- Concrete recommended fix.

If there are no actionable findings, say so and list remaining test or rollout gaps.

## Out Of Scope

- Do not review unrelated code.
- Do not inspect secrets, `.env`, token files, `.codex/config.toml`, or production credentials.
- Do not propose implementation code in this review.
- Do not widen this into a full repository architecture audit.
