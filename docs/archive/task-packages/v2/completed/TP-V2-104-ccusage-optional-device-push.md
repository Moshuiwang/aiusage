# TP-V2-104 CC Usage Optional Device Push

Version: V2
ID: TP-V2-104
Status: done
Type: implementation
Depends on: TP-V2-103
Parallel with: none

## Goal

Allow device push to keep user-visible Codex / Claude usage ledger data flowing when `ccusage` is not installed.

## Context

Current device push treats `ccusage daily` as the first hard dependency. If that command is missing or fails, the pusher reports the whole source as failed and returns before collecting `mswusage-codex` / `mswusage-claude` hourly facts.

That blocks uninstalling CC Usage even though the current product surface already prefers usage ledger hourly facts for visible totals and official limits use separate providers.

## Scope

- Change `DevicePusher.push()` behavior only.
- If `ccusage daily` fails, continue to collect and upload usage ledger hourly facts.
- Report missing or failed `ccusage` as optional daily-baseline metadata, not as whole-source failure, when ledger facts are available.
- Keep existing `ccusage daily`, `ccusage session`, and `ccusage blocks` payloads when the command is available.
- EC2 Linux pushers use the same `DevicePusher` code path; deploy verification covers configured systemd pusher units without adding EC2-only behavior.

## Out of Scope

- Do not remove CC Usage support.
- Do not change official limits providers.
- Do not read raw remote `~/.claude` or `~/.codex` directories.
- Do not change iPhone, Watch, or macOS menu UI.
- Do not change production account files.

## Red Test

- Add a pusher test where `ccusage daily` returns `missing_tool`, `mswusage-codex` and `mswusage-claude` return valid hourly facts, and the resulting payload is accepted with `collection_status: ok`.
- The payload must include `usage_hourly_facts` and a non-fatal `ccusage_daily_status`.
- The payload must not include `ccusage_session_report` or `ccusage_blocks_report` when `ccusage daily` is unavailable.
- Add an ingest/snapshot or server-service test proving a successful payload with optional `ccusage_daily_status` keeps source health `ok`.

## Implementation

- Do not return immediately on `ccusage daily` failure.
- Skip `ccusage session` and `ccusage blocks` when `ccusage daily` is unavailable.
- Use an empty daily baseline for drift comparison when `ccusage daily` is unavailable, so drift becomes `comparison_unavailable`.
- Set source-level failure only when no usage facts can be uploaded.
- Add optional top-level payload metadata accepted by `ingest.py`:

```json
{
  "collection_status": "ok",
  "ccusage_daily_status": {
    "status": "missing_tool",
    "error_type": "missing_tool",
    "error_message": "ccusage not found"
  },
  "usage_daily": [],
  "usage_hourly_facts": []
}
```

## Acceptance Criteria

- Uninstalling `ccusage` no longer makes `mac-local` source health fail as long as usage ledger facts are collected.
- User-visible daily/period totals can still be populated from `usage_hourly_facts`.
- Diagnostics still make it clear that CC Usage daily baseline is unavailable.
- Existing successful CC Usage behavior remains unchanged.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_pusher.TestDevicePusherFakeHTTP -v
PYTHONPATH=src python3 -m unittest tests.test_ingest_contract tests.test_normalize_ingest tests.test_snapshot_builder tests.test_server_services -v
```

## Handoff

- Report whether local `ccusage` was uninstalled.
- Report local LaunchAgent push result after uninstall.
- Report EC2 deployed users or systemd units verified.
- Report PR timing recommendation and any remaining risk.
