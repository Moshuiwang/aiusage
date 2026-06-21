# TP-V2-060 MSWusage Codex Parser Contract

Version: V2
ID: TP-V2-060
Status: done
Type: implementation
Depends on: none
Parallel with: mobile UI polish

## Goal

Add an independent local `MSWusage` Codex usage parser and CLI contract that derives Codex hourly usage from Codex `token_count` events instead of relying on `ccusage session.lastActivity`.

## Context

Production validation showed that `ccusage session` is not a reliable Codex hourly source. It is a session-level aggregate: `lastActivity` tells when a session last changed, not when every token in that session was consumed.

Claude has `ccusage blocks` for hourly distribution. Codex does not expose equivalent `ccusage blocks`, but the local Codex JSONL records under `~/.codex/sessions/**/*.jsonl` contain finer-grained usage events:

```json
{
  "timestamp": "2026-06-04T08:38:19.099Z",
  "type": "event_msg",
  "payload": {
    "type": "token_count",
    "info": {
      "last_token_usage": {
        "input_tokens": 38030,
        "cached_input_tokens": 30592,
        "output_tokens": 360,
        "reasoning_output_tokens": 34,
        "total_tokens": 38390
      },
      "total_token_usage": {
        "input_tokens": 68961,
        "cached_input_tokens": 36608,
        "output_tokens": 766,
        "reasoning_output_tokens": 159,
        "total_tokens": 69727
      }
    }
  }
}
```

This means Codex hourly statistics should be based on `token_count.timestamp` plus `last_token_usage`, not `ccusage session.lastActivity`.

## Scope

- Add a local-only Codex raw JSONL parser for the current OS user's data.
- Add a CLI entrypoint, initially as an internal command such as:

```bash
PYTHONPATH=src python3 -m ai_usage_widget.cli mswusage-codex --json --timezone Asia/Shanghai
```

- Parse only `payload.type == "token_count"` rows.
- Use row `timestamp` converted to the requested IANA timezone as the hourly bucket.
- Use `info.last_token_usage` as the event increment.
- Produce a stable JSON contract with fully specified `daily`, `hourly`, and `sessions` row shapes.
- Add fixture-based tests that use sanitized Codex JSONL samples.
- Include parser provenance in the local contract as `provenance: "mswusage_codex_token_count"`.
- Keep the parser output safe for future HTTP push by guaranteeing it emits no `.codex` path, file path, filename, prompt, response, tool output, command output, credentials, or raw JSONL line.
- Define Codex cache display math so token-type breakdowns can later add up to the same total users see at the top of the app.

Allowed implementation files:

- `src/ai_usage_widget/cli.py`
- new `src/ai_usage_widget/mswusage_codex.py`
- tests and sanitized fixtures required by this task package

## Out of Scope

- Do not modify `ccusage`.
- Do not parse or print prompt text, response text, tool output, base instructions, shell output, credentials, or raw logs in reports.
- Do not read remote `~/.codex` directories from Mac or from the production server.
- Do not let `wang` read `/home/ubuntu`.
- Do not change official limits providers or present local token usage as official quota.
- Do not require production credentials on the server.
- Do not integrate with pusher, ingest, storage, snapshot builder, Web dashboard, iPhone App, or iOS Widget in this parser-only package.
- Do not calculate or publish drift versus `ccusage daily`; drift belongs to the follow-up integration task.
- Do not run launchd, SSH to production, or query production SQLite.

## Red Test

- Add parser fixture tests with sanitized JSONL lines:
  - one `session_meta`;
  - multiple `token_count` events in the same session;
  - events crossing two hours;
  - events crossing a date boundary in `Asia/Shanghai`;
  - malformed rows and non-usage rows.
- The first failing tests should assert:
  - only `token_count` rows are counted;
  - prompt/response/tool fields are ignored and never emitted;
  - `last_token_usage` is accumulated by event timestamp;
  - hourly buckets use the requested timezone;
  - daily totals are derived from the same event increments;
  - session summary uses the Codex session id but does not depend on `lastActivity`.
- Add parser contract tests that assert:
  - emitted session ids and metadata strings never contain path markers such as `.codex`, `.claude`, `.jsonl`, `/Users/`, `/home/`, `~`, fixture filenames, or raw JSONL lines;
  - the no-path assertion does not reject the `timezone` field, including IANA values such as `Asia/Shanghai`;
  - fallback session ids are generated safe ids such as `fallback:<hash>`, not file paths or filenames;
  - Codex `cached_input_tokens` is treated as a subset of `input_tokens`;
  - `input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens == total_tokens` for the normalized output rows;
  - `reasoning_output_tokens` is emitted as an explicit numeric field, is treated as a subset of `output_tokens`, and is not added again to the total.

## Implementation

1. Implement `mswusage_codex.py` with a pure testable boundary such as `build_report(jsonl_lines, timezone, now=...) -> dict`.
2. Keep the CLI as a thin wrapper that reads the current user's `~/.codex/sessions/**/*.jsonl` and passes sanitized line content into the parser boundary.
3. Extract these non-sensitive fields only:
   - session id from `session_meta.payload.id`;
   - fallback session id generated as `fallback:<stable_hash>` when `session_meta.payload.id` is unavailable;
   - event `timestamp`;
   - `last_token_usage`;
   - optional model/provider metadata if present without reading message content.
4. Normalize usage fields into the existing naming style:
   - `input_tokens` is non-cached input, computed as `max(input_tokens - cached_input_tokens, 0)`;
   - `output_tokens`;
   - `cache_read_tokens` from `cached_input_tokens`;
   - `cache_creation_tokens` as `0` unless Codex later exposes a separate creation field;
   - `reasoning_output_tokens` as an explicit numeric field that is a subset of `output_tokens` and does not participate in the row total sum;
   - `total_tokens`.
5. Preserve the Codex raw input relationship only as safe metadata, for example `codex_input_tokens_includes_cached: true`; do not emit raw file paths, raw filenames, raw JSONL, prompt text, response text, or tool output.
6. In fixture tests, inject a fixed `now` value so `generated_at` is deterministic.
7. Build this top-level output envelope:

```json
{
  "schema_version": 1,
  "source": "mswusage_codex",
  "timezone": "Asia/Shanghai",
  "generated_at": "...",
  "provenance": "mswusage_codex_token_count",
  "daily": [],
  "hourly": [],
  "sessions": []
}
```

8. Build `hourly` rows with this exact shape:

```json
{
  "hour": "2026-06-04T16:00:00+08:00",
  "agent": "codex",
  "input_tokens": 7438,
  "output_tokens": 360,
  "cache_creation_tokens": 0,
  "cache_read_tokens": 30592,
  "reasoning_output_tokens": 34,
  "total_tokens": 38390,
  "event_count": 1,
  "session_count": 1,
  "provenance": "mswusage_codex_token_count"
}
```

Rules:

- `hour` is the start of the local hour in the requested IANA timezone, serialized as ISO 8601 with offset.
- `input_tokens + output_tokens + cache_creation_tokens + cache_read_tokens == total_tokens`.
- `reasoning_output_tokens` is already included in `output_tokens`; do not add it again.

9. Build `daily` rows with this exact shape:

```json
{
  "date": "2026-06-04",
  "agent": "codex",
  "input_tokens": 7438,
  "output_tokens": 360,
  "cache_creation_tokens": 0,
  "cache_read_tokens": 30592,
  "reasoning_output_tokens": 34,
  "total_tokens": 38390,
  "event_count": 1,
  "session_count": 1,
  "provenance": "mswusage_codex_token_count"
}
```

10. Build `sessions` rows with this exact shape:

```json
{
  "session_id": "019e91f1-739a-79b1-99ca-60cc89982c35",
  "agent": "codex",
  "first_event_at": "2026-06-04T16:38:19+08:00",
  "last_event_at": "2026-06-04T16:38:19+08:00",
  "input_tokens": 7438,
  "output_tokens": 360,
  "cache_creation_tokens": 0,
  "cache_read_tokens": 30592,
  "reasoning_output_tokens": 34,
  "total_tokens": 38390,
  "event_count": 1,
  "provenance": "mswusage_codex_token_count"
}
```

11. Keep parser output deterministic for fixture tests by sorting `daily`, `hourly`, and `sessions` consistently.
12. Leave push, ingest, storage, source health, drift, production verification, and snapshot source preference to TP-V2-061.

## Acceptance Criteria

- Parser output is ready to replace `ccusage session.lastActivity` as the Codex hourly source in a follow-up task.
- `MSWusage` output contains no message text, command output, prompts, responses, auth data, or raw JSONL lines.
- `MSWusage` output contains no `.codex` path, `.claude` path, local filesystem path, fixture filename, or raw log path.
- Hourly Codex buckets are derived from `token_count.timestamp`.
- Hourly Codex token counts are derived from `last_token_usage`.
- Token-type breakdown is internally consistent: normalized input plus output plus cache equals the row total users would see later.
- `reasoning_output_tokens` has one explicit contract location and is not double counted.
- Fixture tests exercise the pure parser boundary without reading real `~/.codex`.
- CLI verification may read only the current OS user's local Codex logs and must not emit paths or raw log content.
- No pusher, server, storage, snapshot, launchd, SSH, production, dashboard, iPhone App, or iOS Widget behavior changes are included in this package.

## Verification

```bash
PYTHONPATH=src python3 -m unittest tests.test_mswusage_codex -v
PYTHONPATH=src python3 -m ai_usage_widget.cli mswusage-codex --json --timezone Asia/Shanghai
```

Do not run launchd, production SSH, production SQLite checks, or pusher/server tests for this parser-only task.

## Handoff

- Report the sanitized fixture shape used for tests.
- Report local parser totals for Codex daily/hourly.
- Report whether the output passed the no-path/no-raw-log safety assertions.
- Report the token-type math used for cached input.
- State that pusher/server/snapshot/drift integration is intentionally left for TP-V2-061.
- Report exact verification commands and results.
- Confirm production, launchd, server files, and app UI were not touched.
