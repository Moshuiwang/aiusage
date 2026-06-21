# AI Review Report

## Selection

```yaml
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
  scope: three new Watch/TestFlight planning docs plus integration references
  rounds_completed: 1
  reasons:
    - user requested Claude Code Ops high bar AI Review
    - multi-document product and implementation planning review benefits from artifact-backed context
    - docs touch TestFlight distribution, Watch install flow, and data-boundary promises
```

Request artifact: `reviews/20260621-193251-codex-watch-companion-testflight-request-929fa0d-wctf01.md`

Reviewer command:

```bash
claude --model opus --effort xhigh -p "Read reviews/20260621-193251-codex-watch-companion-testflight-request-929fa0d-wctf01.md and return only scoped review findings tied to its scope. Treat it as read-only review. Use Chinese. Findings first with severity, file/path, evidence, user impact, and suggested fix. If none, say no actionable findings and list residual verification gaps."
```

## Reviewer Output

Claude reported 5 scoped findings:

1. The Watch face complication implementation path is underspecified: current project has an iOS widget extension only; a watchOS widget extension embedded in the Watch app is needed.
2. The architecture doc says stale after 30 minutes, while current Watch code uses 2 hours.
3. The docs use Modular / Modular Duo wording but do not name WidgetKit accessory families, making the red test hard to implement.
4. The verification command can pass without proving the new companion install and complication/widget deliverables.
5. The docs do not clearly separate TP-V2-070 already-delivered WatchConnectivity work from this round's new companion/TestFlight/complication work.

Claude also confirmed the boundary direction is clean: no Watch-side token, no Watch-side collection, and no new server endpoint is being proposed.

## Triage

```yaml
findings:
  - id: R1
    reviewer_severity: P2
    confirmed_severity: P2
    file: docs/architecture/watch-companion-testflight.md
    source: introduced
    summary: Watch complication/widget target shape is underspecified.
    evidence: mobile/ios-xcode/project.yml currently defines AIUsageMobileWidgetExtension as iOS only and AIUsageWatchApp as watchOS; mobile/ios-xcode/Sources/AIUsageMobileWidgetExtension/AIUsageMobileWidget.swift supports only systemSmall/systemMedium/systemLarge.
    action: accepted_risk
  - id: R2
    reviewer_severity: P2
    confirmed_severity: P2
    file: docs/architecture/watch-companion-testflight.md
    source: introduced
    summary: Stale threshold conflicts with existing Watch implementation.
    evidence: the new architecture doc says generated_at over 30 minutes is stale; mobile/ios-xcode/Sources/AIUsageMobileWidgetExtension/AIUsageWatchApp.swift has maxAge = 2 * 60 * 60.
    action: accepted_risk
  - id: R3
    reviewer_severity: P2
    confirmed_severity: P2
    file: docs/product/watch-companion-testflight-prd.md
    source: introduced
    summary: Watch face family terminology is not TDD-actionable.
    evidence: the docs name Modular and Modular Duo but do not specify WidgetKit accessoryCircular/accessoryRectangular/accessoryInline/accessoryCorner family targets.
    action: accepted_risk
  - id: R4
    reviewer_severity: P3
    confirmed_severity: P2
    file: docs/task-packages/v2/TP-V2-083-watch-companion-testflight.md
    source: introduced
    summary: Verification can pass without proving the headline user experience.
    evidence: tests/test_ios_xcode_integration.py currently covers WatchConnectivity/cache/stale basics, but not the companion embed relationship, watchOS widget extension, or accessory families.
    action: accepted_risk
  - id: R5
    reviewer_severity: P3
    confirmed_severity: P3
    file: docs/architecture/watch-companion-testflight.md
    source: introduced
    summary: The docs blur existing TP-V2-070 sync work with this round's new work.
    evidence: current code already has WatchSummaryBridge.push, didReceiveApplicationContext, WatchSummaryStore, and decoded.period.id == "today"; the new docs present iPhone-to-Watch sync and a smaller DTO as if they may still need to be created.
    action: accepted_risk
```

## Fixes

No fixes were made in this review pass. The user asked for review only.

Recommended document fixes before implementation:

- Say explicitly that a new watchOS WidgetKit extension target must be embedded in `AIUsageWatchApp`, separate from the existing iOS widget extension.
- Replace or justify the 30-minute stale threshold; the existing product behavior is 2 hours.
- Use concrete WidgetKit accessory families in PRD, architecture, and red tests.
- Expand TP verification so green tests prove companion install structure and watch face component support, not only existing TP-V2-070 sync.
- Mark TP-V2-070 work as existing baseline, and narrow this task to companion/TestFlight/complication stability.

## Verification

Ran:

```bash
git diff --check
```

Result: passed.

No unit tests were run because this was a docs-only AI review and no code or document fixes were applied.

## Remaining Risk

The current three-doc package is directionally right, but not yet strong enough as an implementation gate. If implementation starts from these docs unchanged, the highest user-facing risk is shipping a Watch app that still cannot expose an `AI Usage` complication in the watch face editor, or changing stale behavior unexpectedly.
