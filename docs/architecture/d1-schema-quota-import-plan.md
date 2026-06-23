# D1 Schema, Quota, and SQLite Import Plan

Date: 2026-06-22
Status: M1 planning artifact. Do not execute production import steps in TP-V2-087.

## Scope

This document covers the D1 initial schema migration, SQLite-vs-D1 SQL differences, free-tier quota analysis, and a runnable historical SQLite-to-D1 import plan. It does not create Cloudflare resources, deploy Workers, or import real data.

Primary source of truth for schema: `src/ai_usage_widget/storage_sqlite.py`.

Migration SQL: `cloudflare/migrations/0001_initial_schema.sql`.

## SQLite-vs-D1 Incompatibilities

| Area | SQLite behavior today | D1 concern | Fix for D1 / M2 |
| --- | --- | --- | --- |
| `PRAGMA journal_mode=WAL` | `write_sqlite()` and `write_limit_windows()` set WAL on local SQLite files. | D1 is managed storage; Worker code cannot rely on local WAL semantics. | Remove WAL setup from D1 write path. Treat D1 writes as request-scoped operations and rely on D1 durability. Keep WAL only in local SQLite adapter. |
| `PRAGMA busy_timeout=5000` | Local SQLite waits for file locks. | D1 does not expose the same file-lock waiting model; overloaded/concurrent traffic returns platform errors. | Replace with bounded retry/backoff around D1 calls in the Worker, only for retryable errors. Surface non-retryable errors to `/api/health` and logs. |
| `_ensure_column()` self-migration | Local adapter checks `PRAGMA table_info` and runs `ALTER TABLE ... ADD COLUMN` if needed. | D1 production schema should be versioned migrations, not runtime self-mutation on every request. D1 also has stricter migration/runtime limits. | Move every column change into numbered SQL migrations. Worker startup/request path must not alter schema. |
| `_ensure_limit_windows_schema()` rebuild | Local adapter may rename `limit_windows`, create the new table, copy rows, then drop the old table. | Table rebuild is risky in D1 runtime and can hit query-duration / write-row limits on larger history. | Keep `limit_windows` final schema in `0001_initial_schema.sql`. If production ever needs rebuild, create a dedicated migration with chunked copy and a preflight backup, not runtime code. |
| `conn.executescript()` multi-statement setup | Local SQLite applies many statements in one Python call. | Worker Binding API uses prepared statements and `batch()`; migrations are SQL files applied by Wrangler. Runtime multi-statement strings should not be assumed. | Use `wrangler d1 migrations apply` for schema files. In Worker runtime, split writes into prepared statements and use `db.batch()` for grouped operations. |
| `ON CONFLICT ... DO UPDATE` upsert | Current SQLite code uses upserts for daily/hourly/block/facts/accounts/limits rows. | D1 supports SQLite upsert syntax, but every update counts as written rows and indexed writes add write cost. | Keep upsert SQL, but only upsert changed/bounded data. For high-churn hourly facts, batch prepared upserts and track `meta.rows_written` after M2. |
| `limit_windows` stale failure cleanup | `_upsert_limit_window()` deletes stale `provider_failed` rows before inserting a successful runtime row. | Delete + insert/update increases D1 write-row usage and can surprise free-tier budgets. | Keep behavior for UX correctness, but do it in the same D1 batch as the upsert and only for the affected `(source_id, provider)`. |
| `usage_hourly` Codex replacement delete | `_delete_replaced_codex_hourly_rows()` deletes old session-derived Codex hourly rows for affected source/day. | Day-level deletes can become expensive if run against broad history. | Require source/day-bounded deletes with the existing `source_id` and `substr(hour, 1, 10)` predicates. M2 should avoid sending repeated full-day replacement payloads after a day is settled. |

## Free-Tier D1 Quota Analysis

Official sources checked on 2026-06-22:

- D1 pricing: https://developers.cloudflare.com/d1/platform/pricing/
- D1 limits: https://developers.cloudflare.com/d1/platform/limits/
- D1 Wrangler commands: https://developers.cloudflare.com/d1/wrangler-commands/

Current official D1 Workers Free numbers:

| Limit | Free-tier number | Product impact |
| --- | ---: | --- |
| Rows read | 5,000,000 rows/day | Enough for cached personal dashboards if reads stay indexed and period-bounded. |
| Rows written | 100,000 rows/day | Main constraint for 30-minute push cadence and indexed hourly facts. |
| Storage per account | 5 GB total | Account-level budget across all D1 databases. |
| Max database size | 500 MB per database on Free | More important than 5 GB for this single database. |
| Databases per account | 10 on Free | One dev DB + one future prod DB is fine. |
| Queries per Worker invocation | 50 on Free | M2 API should keep each request to a small fixed query set. |
| Max columns per table | 100 | Current widest table, `usage_hourly_facts`, has 26 columns and is safe. |
| Max row / string / blob size | 2 MB | Keep `metadata_json`, `raw_json`, and evidence JSON compact. |
| Max SQL statement length | 100 KB | Avoid generated giant multi-row SQL statements; use prepared statements/batches. |
| Max bound parameters per query | 100 | Batch inserts must account for column count; many tables cannot batch many rows into one statement. |
| Max SQL query duration | 30 seconds | Historical imports and rebuilds need chunks. |
| Max file import size | 5 GB | Not the limiting factor for Free; 500 MB database size is. |

30-minute push envelope:

- README/scheduler baseline uses a 30-minute cadence, so one source can push up to 48 times/day.
- README lists four source IDs (`mac-local`, `linux-server-1`, `linux-server-2`, `windows-desktop`), so the baseline fleet is 192 usage pushes/day.
- Free write budget per push across four sources: `100,000 / 192 = 520` billable written rows per source push.
- `usage_hourly_facts` has six explicit indexes plus the table row. A conservative budget treats one changed fact as roughly seven billable written rows before any primary-key/index overhead Cloudflare reports separately.
- Under that conservative model, one source push has room for about `520 / 7 = 74` changed hourly fact rows.
- For non-secondary-index tables, a conservative 2x table-plus-key estimate gives about `520 / 2 = 260` logical changed rows per source push.

Recommended free-tier strategy:

1. Keep summary reads period-bounded: Today/Week/Month/All must use primary-key or explicit-index predicates, not full table scans.
2. Cache API summaries by period/filter for 60-300 seconds in Worker memory or KV. User experience should favor fresh-enough dashboard data over repeated full recomputation.
3. Batch writes per pusher request, but keep each prepared statement under 100 bound parameters.
4. Do not re-upsert unchanged historical rows on every 30-minute push. The pusher/ingest contract should prefer recent windows and changed rows only.
5. Track D1 `meta.rows_read` and `meta.rows_written` in M2 logs/health so the free-tier budget can be verified with real traffic.
6. Treat 500 MB per database as the first storage stop sign. If history approaches 400 MB, add retention/export policy before enabling broader ingest.

Quota conclusion: D1 Free is acceptable for M2 read-only API validation and a small personal fleet if M2 keeps reads cached and writes bounded. It is not safe to blindly replay full historical daily/hourly payloads every 30 minutes.

## Historical SQLite-to-D1 Import Plan

Do not run these steps in TP-V2-087. They are written for a future staged import after Cloudflare resource approval.

Assumptions:

- Source SQLite path is provided as `SOURCE_SQLITE`.
- Target D1 database name is provided as `D1_DATABASE`.
- The target is a staging or approved production D1 database with `0001_initial_schema.sql` already applied.
- Commands are run from the repository root.

### 1. Preflight row counts from SQLite

```bash
export SOURCE_SQLITE=/path/to/usage.sqlite
export D1_DATABASE=aiusage-prod-db

python3 - <<'PY' > /tmp/aiusage-sqlite-row-counts.tsv
import sqlite3
import os

tables = [
    "collection_runs",
    "source_reports",
    "usage_daily",
    "usage_daily_models",
    "usage_hourly",
    "usage_blocks",
    "source_identities",
    "machines",
    "os_identities",
    "ai_accounts",
    "usage_hourly_facts",
    "usage_hourly_models",
    "limit_windows",
]

with sqlite3.connect(os.environ["SOURCE_SQLITE"]) as conn:
    for table in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table}\t{count}")
PY
```

### 2. Export data-only SQL from SQLite

```bash
sqlite3 "$SOURCE_SQLITE" ".dump --data-only" > /tmp/aiusage-data-only.sql
```

Review `/tmp/aiusage-data-only.sql` before import. It must not contain tokens, raw credential files, or local usage log paths.

### 3. Import into D1

```bash
# Future step only. Do not run in TP-V2-087.
npx wrangler d1 execute "$D1_DATABASE" --remote --file /tmp/aiusage-data-only.sql --yes
```

### 4. Row-count check after import

```bash
npx wrangler d1 execute "$D1_DATABASE" --remote --json --command "
SELECT 'collection_runs' AS table_name, COUNT(*) AS rows FROM collection_runs UNION ALL
SELECT 'source_reports', COUNT(*) FROM source_reports UNION ALL
SELECT 'usage_daily', COUNT(*) FROM usage_daily UNION ALL
SELECT 'usage_daily_models', COUNT(*) FROM usage_daily_models UNION ALL
SELECT 'usage_hourly', COUNT(*) FROM usage_hourly UNION ALL
SELECT 'usage_blocks', COUNT(*) FROM usage_blocks UNION ALL
SELECT 'source_identities', COUNT(*) FROM source_identities UNION ALL
SELECT 'machines', COUNT(*) FROM machines UNION ALL
SELECT 'os_identities', COUNT(*) FROM os_identities UNION ALL
SELECT 'ai_accounts', COUNT(*) FROM ai_accounts UNION ALL
SELECT 'usage_hourly_facts', COUNT(*) FROM usage_hourly_facts UNION ALL
SELECT 'usage_hourly_models', COUNT(*) FROM usage_hourly_models UNION ALL
SELECT 'limit_windows', COUNT(*) FROM limit_windows
" > /tmp/aiusage-d1-row-counts.json
```

Pass condition: every D1 table row count exactly matches `/tmp/aiusage-sqlite-row-counts.tsv`.

### 5. Sampled field-level check

Generate deterministic SQLite samples from key user-facing fields:

```bash
python3 - <<'PY' > /tmp/aiusage-sqlite-samples.tsv
import sqlite3
import os

samples = {
    "usage_daily": ("source_id, date, agent", "source_id, date, agent, total_tokens, total_cost, last_seen_at"),
    "usage_daily_models": ("source_id, date, agent, model_name", "source_id, date, agent, model_name, total_tokens, cost"),
    "usage_hourly": ("source_id, hour, agent", "source_id, hour, agent, total_tokens, total_cost"),
    "usage_blocks": ("source_id, start_time, end_time, agent", "source_id, start_time, end_time, agent, total_tokens, total_cost"),
    "source_identities": ("source_id", "source_id, host, machine, os_user, platform"),
    "machines": ("machine_id", "machine_id, machine_name, host, platform"),
    "os_identities": ("machine_id, os_user", "machine_id, os_user, display_name"),
    "ai_accounts": ("provider, account_id", "provider, account_id, account_label, display_name, subscription"),
    "usage_hourly_facts": ("fact_id", "fact_id, source_id, machine_id, os_user, ai_provider, ai_account_id, total_tokens, event_count, session_count"),
    "usage_hourly_models": ("fact_id, model", "fact_id, model, total_tokens, total_cost"),
    "limit_windows": ("source_id, provider, source_type, window", "source_id, provider, source_type, window, used_percent, remaining_percent, reset_at, status"),
}

with sqlite3.connect(os.environ["SOURCE_SQLITE"]) as conn:
    for table, (order_by, fields) in samples.items():
        for row in conn.execute(f"SELECT {fields} FROM {table} ORDER BY {order_by} LIMIT 20"):
            print(table + "\t" + "\t".join("" if value is None else str(value) for value in row))
PY
```

Run matching D1 `SELECT ... ORDER BY ... LIMIT 20` commands for each sampled table and compare field-by-field against `/tmp/aiusage-sqlite-samples.tsv`. The check must include at least:

- identity fields (`source_id`, `machine_id`, `os_user`, `provider`, `account_id`);
- period/window fields (`date`, `hour`, `start_time`, `end_time`, `window_start`, `window_end`);
- user-facing totals (`total_tokens`, `total_cost`, `used_percent`, `remaining_percent`);
- freshness fields (`last_seen_at`, `reset_at`, `status`).

Pass condition: sampled rows match exactly after normalizing `NULL` and JSON text representation.

### 6. Post-import UX smoke

After row counts and samples pass, run read-only API smoke against the target Worker/API:

```bash
curl -fsS "https://<target-host>/api/mobile/summary?period=today" > /tmp/aiusage-mobile-today.json
curl -fsS "https://<target-host>/api/mobile/summary?period=week" > /tmp/aiusage-mobile-week.json
```

Pass condition: Today and Week show non-empty real data, no stale 0-only source list, and quota cards still show safe account labels.
