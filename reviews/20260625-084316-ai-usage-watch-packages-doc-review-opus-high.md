# AI Usage Watch Task Packages Docs Review

Date: 2026-06-25
Reviewer: Claude Code local
Model/depth: `opus`, `high`
Request: `reviews/20260625-084316-ai-usage-watch-packages-doc-review-request.md`
Mode: read-only docs/task-package review

## Result

Claude review completed successfully after `fable` was unavailable. The failure was model-specific:

```text
Claude Fable 5 is currently unavailable.
```

Claude Code itself passed an `opus --effort high` smoke check and completed the review.

## Findings Triaged For This Delivery

### Confirmed

- `docs/product/iphone-watch-refresh-reliability-plan.md` conflicts with TP-V2-085/100 because it still says not to start until migration is complete. The implementation should be framed as pulling forward Stage 1 only; APNs Stage 2 remains post-migration.
- TP-V2-101 and `docs/product/watch-circular-complication-reset-at-ui.md` do not define a stale-state signal for circular complications, even though the broader Watch architecture says stale data must not look live.
- TP-V2-101 does not define degraded ring behavior when the 5h window is missing, untrusted, or not official/observed/ok.
- `docs/architecture/watch-companion-testflight.md` still describes circular accessory as a single compact value, while TP-V2-101 changes it to Reset At double-ring.
- TP-V2-085 acceptance says background refresh can update Watch without opening the iPhone app every time. This is too deterministic for BGAppRefresh. The testable claim should be: when the system runs the background task, it fetches today, writes cache, and pushes Watch; stale remains honest otherwise.
- TP-V2-100 assumes `devicectl ... appGroupDataContainer` read access. The task should explicitly treat unreadable device containers as a reported verification blocker or provide an app-visible diagnostic fallback.
- The design doc references canonical assets under ignored `tmp/design/...`; tracked docs should not depend on ignored files as the only source of truth.

### Non-Blocking Notes

- The current code baseline must decide whether BGAppRefresh already exists or is newly implemented.
- Bundled delivery must sequence TP-V2-085 before TP-V2-100 diagnostics because 100 observes the refresh/push path.

## Safety Boundary

No safety-boundary findings. The reviewed docs consistently keep Watch as a non-credential-bearing companion and prohibit Watch-side token, raw logs, direct server networking, provider runtime, SQLite, and SSH.

## Residual Validation Gaps

- Physical-device `devicectl` App Group readability cannot be proven from docs alone.
- Simulator/build and real-device Watch complication visibility remain implementation-phase checks.
