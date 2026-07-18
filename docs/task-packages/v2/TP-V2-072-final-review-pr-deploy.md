# TP-V2-072 Final Review PR Deploy

Version: V2
ID: TP-V2-072
Status: ready
Type: release
Depends on: TP-V2-071
Parallel with: none

## Goal

Run final AI review, commit, push, open PR, and deploy any affected runtime surfaces.

## Context

After implementation and verification, the user wants AI Review, commit, push, PR, and deployment where needed.

## Scope

- Run 1-2 rounds of AI Review over the full diff.
- Prefer Claude Code when session/quota allows; fallback to Codex subagent if Claude is unavailable.
- Commit relevant files only.
- Push branch and create Ready PR.
- Deploy Web/server changes if static/API changes affect production.
- Install/update local macOS/iOS artifacts only when explicitly safe and secrets are guarded.

## Out of Scope

- Do not commit `.codex/config.toml`.
- Do not commit production tokens, local xcconfig, generated logs, screenshots with secrets, or raw usage logs.
- Do not deploy if tests fail without user approval.

## Red Test

- Final review must fail the release if P0/P1 confirmed findings remain unfixed.
- Deployment checklist must fail if server static assets changed but production deployment was skipped without explanation.

## Implementation

1. Create final review artifact from `origin/main...HEAD`.
2. Run AI Review and triage findings.
3. Run final tests and smoke checks.
4. Commit in Chinese with scoped message.
5. Push branch.
6. Open Ready PR.
7. Deploy affected server/local runtime surfaces.

## Acceptance Criteria

- Final AI Review has no unresolved P0/P1 confirmed findings.
- Tests and builds are documented.
- PR includes change summary, validation, risk, and deployment notes.
- Deployment status is verified if deployment was needed.

## Verification

```bash
git status --short
git diff --check
gh auth status
gh pr view
```

## Handoff

- Report commit SHA, GitHub PR URL, test evidence, deployment evidence, and any user action still required.
