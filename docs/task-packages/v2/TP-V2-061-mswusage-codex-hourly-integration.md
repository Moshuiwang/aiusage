# TP-V2-061 MSWusage Codex Hourly Integration

Version: V2
ID: TP-V2-061
Status: ready
Type: implementation
Depends on: TP-V2-060
Parallel with: mobile UI polish

## Goal

Integrate the tested `MSWusage` Codex parser contract into device push, ingest, storage, and snapshots so Codex hourly usage shown to users comes from `token_count.timestamp + last_token_usage`, not `ccusage session.lastActivity`.

## Context

TP-V2-060 creates the parser-only contract. This package wires that contract into the product.

Product decision: Codex hourly is a source replacement, not a dual-source merge. Once this package is implemented, Codex hourly rows should come from `mswusage_codex_token_count`. If MSWusage is unavailable, Codex hourly should be represented as unavailable in metadata instead of falling back to `ccusage session.lastActivity`.

This avoids two bad user experiences:

- hourly charts moving between two different Codex timing models;
- token-type breakdowns where categories add up to a different number than the headline total.

Claude hourly behavior remains based on de-duplicated `ccusage blocks`.

## Scope

- Add device push support for a new `mswusage_codex_hourly_report` payload key.
- Add ingest validation for the new report key.
- Normalize MSWusage hourly rows into Codex `UsageHourlyItem` rows with provenance.
- Stop deriving Codex hourly rows from `ccusage session.lastActivity`; keep non-Codex session behavior unchanged unless block rows already supersede it.
- Store provenance in `metadata_json` as `provenance: "mswusage_codex_token_count"`.
- Keep the existing `usage_hourly` primary key unchanged and use source replacement semantics: before writing MSWusage Codex hourly rows, remove old Codex hourly rows for the affected source/day so session-derived rows cannot remain beside the new rows.
- Add Codex-hourly-specific health metadata so MSWusage failure marks Codex hourly unavailable while `ccusage daily` push can still succeed and the source's daily health is not overwritten by the Codex hourly failure.
- Add drift reporting by comparing MSWusage Codex daily totals with `ccusage daily` Codex totals when both are available.
- Treat MSWusage as a write-time source replacement, not a snapshot read-time preference:
  - de-duplicated Claude blocks for Claude hourly;
  - MSWusage token-count rows written to `usage_hourly` for Codex hourly;
  - `ccusage daily` as the period summary baseline.

Allowed implementation files:

- `src/ai_usage_widget/pusher.py`
- `src/ai_usage_widget/ingest.py`
- `src/ai_usage_widget/models.py`
- `src/ai_usage_widget/normalize.py`
- `src/ai_usage_widget/storage_sqlite.py`
- `src/ai_usage_widget/snapshot_builder.py`
- tests and sanitized fixtures required by this task package

## Out of Scope

- Do not modify `ccusage`.
- Do not parse or print prompt text, response text, tool output, base instructions, shell output, credentials, or raw logs in reports.
- Do not read remote `~/.codex` directories from Mac or from the production server.
- Do not let `wang` read `/home/ubuntu`.
- Do not change official limits providers or present local token usage as official quota.
- Do not require production credentials on the server.
- Do not change dashboard, iPhone App, or iOS Widget UI.
- Do not add a provenance dimension to the `usage_hourly` primary key in this package.
- Do not reintroduce Codex hourly fallback from `ccusage session.lastActivity`.
- Do not write Codex hourly parser failures into `source_reports` in a way that can become the source's latest overall `source_status`.

## Push / Ingest Contract

The pusher should include this key only when the parser command succeeds:

```json
{
  "mswusage_codex_hourly_report": {
    "schema_version": 1,
    "source": "mswusage_codex",
    "timezone": "Asia/Shanghai",
    "generated_at": "...",
    "provenance": "mswusage_codex_token_count",
    "daily": [],
    "hourly": [],
    "sessions": [],
    "drift": {
      "status": "ok",
      "threshold_percent": 5
    }
  }
}
```

Rules:

- `hourly` rows from TP-V2-060 have `hour`, `agent`, `input_tokens`, `output_tokens`, `cache_creation_tokens`, `cache_read_tokens`, `reasoning_output_tokens`, `total_tokens`, `event_count`, `session_count`, and `provenance`.
- `hourly` rows become `UsageHourlyItem(agent="codex")`.
- `metadata_json` must include `provenance: "mswusage_codex_token_count"`, `reasoning_output_tokens`, `event_count`, and `session_count`.
- `reasoning_output_tokens` is a subset of `output_tokens`; do not add it again to `total_tokens`.
- Payload strings must not contain `.codex`, `.claude`, `~`, local paths, fixture filenames, prompt text, response text, command output, credentials, or raw JSONL lines.
- Codex `ccusage session` rows must not produce Codex hourly rows after this integration. This package intentionally prefers "unavailable" over wrong-hour fallback.
- If `mswusage_codex_hourly_report` is absent because the parser failed, ingest must still accept `ccusage_daily_report`.
- Drift belongs in `mswusage_codex_hourly_report.drift` and in non-UI snapshot metadata for follow-up UI work. It must not be silently hidden, but this package does not add visible UI.
- Codex-hourly unavailable status belongs in Codex-hourly-specific metadata, not the source's latest overall `source_status`.

## Red Test

- Add pusher tests after TP-V2-060 parser tests are green:
  - pusher includes `mswusage_codex_hourly_report` when parser command succeeds;
  - parser failure does not fail `ccusage daily` push;
  - parser failure records Codex hourly health as unavailable without changing the source's daily health to unavailable;
  - pusher never emits `.codex` paths, filenames, raw JSONL, prompt text, response text, or tool output.
- Add ingest contract tests:
  - `mswusage_codex_hourly_report` must be an object when present;
  - any `.codex` or `.claude` string inside the report is rejected by existing sensitive payload scanning;
  - valid report shape is accepted together with `ccusage_daily_report`.
- Add normalize/storage tests:
  - MSWusage hourly rows write Codex hourly rows with `metadata_json.provenance == "mswusage_codex_token_count"`;
  - `reasoning_output_tokens` is preserved in `metadata_json` and is not added to stored `total_tokens`;
  - Codex rows from `ccusage_session_report` no longer create Codex hourly rows;
  - Codex-like session rows whose agent contains `codex`, `gpt`, or `openai` no longer create hourly rows;
  - non-Codex session rows are not broken by the Codex source replacement;
  - existing `usage_hourly` primary key remains `(source_id, hour, agent)`.
  - old session-derived Codex hourly rows for the affected source/day are deleted before MSWusage Codex rows are inserted.
- Add snapshot tests:
  - Codex hourly trend uses MSWusage rows when present;
  - Codex hourly does not fall back to session `lastActivity` when MSWusage is absent;
  - daily period totals still come from `ccusage daily`;
  - token-type breakdown adds up to the same total shown to users.
  - drift beyond threshold does not create a fake current-hour spike through residual fill.
- Add drift tests:
  - `ok` when MSWusage and daily Codex totals are within threshold;
  - `drift_detected` when beyond threshold;
  - `comparison_unavailable` when daily baseline or MSWusage total is unavailable.
  - drift status is available in payload/snapshot metadata even though UI changes are out of scope.

## Implementation

1. Extend pusher to run the TP-V2-060 CLI and attach `mswusage_codex_hourly_report` only on success.
2. On parser failure, keep the normal daily push path alive and record Codex hourly health as unavailable in a Codex-hourly-specific metadata path. Do not write a `source_reports` row that can override the source's daily `source_status`.
3. Extend ingest request parsing to accept the new report key and preserve the existing sensitive value scanner.
4. Add a normalizer path for MSWusage hourly rows.
5. Set `metadata.provenance = "mswusage_codex_token_count"` on rows derived from the new report.
6. Preserve TP-V2-060 row fields in storage metadata when the model has no dedicated column, including `reasoning_output_tokens`, `event_count`, and `session_count`.
7. Update the existing session-to-hourly normalizer so Codex-like `ccusage session` rows are skipped. Use the same Codex-agent definition as snapshot code: agent strings containing `codex`, `gpt`, or `openai`. Do not use session `lastActivity` as a Codex hourly fallback.
8. Keep `usage_hourly` schema unchanged. Before inserting MSWusage Codex hourly rows for a source/day, delete existing Codex-like hourly rows for that same source/day so old session-derived rows cannot remain in hours the new source does not cover.
9. Add drift calculation against `ccusage daily` Codex totals when both inputs are available. Report drift; do not rewrite observed MSWusage event totals.
10. Update snapshot builder assumptions so Codex source replacement happens at normalize/storage write time. Snapshot should read the already-replaced `usage_hourly` rows and should not attempt provenance-based read-time selection.
11. Define residual-fill behavior for Codex hourly:
   - if MSWusage/daily drift is `ok`, residual fill may preserve the existing headline-to-trend consistency behavior;
   - if drift is `drift_detected` or `comparison_unavailable`, do not inject the Codex drift delta into the current hour as if it were real usage;
   - expose drift in snapshot metadata for follow-up UI work while keeping visible UI unchanged in this package.
12. Keep daily summary totals anchored to `ccusage daily`.

## Acceptance Criteria

- Codex hourly data shown to users no longer comes from `ccusage session.lastActivity`.
- Claude hourly behavior remains based on de-duplicated `ccusage blocks`.
- `ccusage daily` remains the daily baseline and is not replaced.
- If MSWusage fails, daily push can still succeed and Codex hourly is represented as unavailable in metadata rather than guessed from session data.
- MSWusage failure does not degrade the source's daily `source_status`.
- If hourly totals and daily Codex totals drift beyond the threshold, the payload reports drift instead of hiding it.
- Drift beyond threshold does not create a fake current-hour Codex spike through residual fill.
- Payload and stored metadata contain no message text, command output, prompts, responses, auth data, raw JSONL, `.codex` paths, `.claude` paths, local paths, or filenames.
- Snapshot token-type breakdown stays internally consistent with the headline totals users see.
- No production credentials, remote raw logs, `/home/ubuntu` reads by `wang`, official limits providers, or UI changes are introduced.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_pusher tests.test_ingest_contract tests.test_storage_sqlite tests.test_snapshot_builder -v
PYTHONPATH=src python3 -m unittest tests.test_mswusage_codex -v
```

Do not run launchd or production SSH checks as part of the default verification for this package.

Only if the user explicitly asks for local runtime deployment after tests pass:

```bash
launchctl kickstart -k gui/$(id -u)/com.chunbai.aiusage.pusher
launchctl print gui/$(id -u)/com.chunbai.aiusage.pusher
```

Only if the user explicitly asks for production smoke after a local push, run as the deployment user rather than local `wang`, and read only aggregate token rows, not raw usage logs:

```bash
ssh vpn2 'cd /home/ubuntu/ai-usage-widget && python3 - <<'"'"'PY'"'"'
import sqlite3
con = sqlite3.connect("data/usage.sqlite")
con.row_factory = sqlite3.Row
for row in con.execute("""
    SELECT source_id, hour, agent, total_tokens, metadata_json
    FROM usage_hourly
    WHERE source_id = 'mac-local'
      AND agent = 'codex'
    ORDER BY hour DESC
    LIMIT 10
"""):
    print(dict(row))
PY'
```

## Handoff

- Report whether Codex hourly now uses `mswusage_codex_token_count`.
- Report whether `ccusage session` Codex hourly fallback was removed.
- Report parser failure behavior and whether daily push still succeeds.
- Report drift status examples for `ok`, `drift_detected`, and `comparison_unavailable`.
- Report exact verification commands and results.
- If runtime deployment or production smoke was explicitly requested and performed, report launchd status, production DB smoke, and whether source health degraded.
