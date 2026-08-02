-- Add source_report_states.collector_version.
--
-- Semantics: the collector version of the LAST payload the server successfully
-- accepted for this source. It is NOT "the version the device is running now":
-- payloads whose version is incompatible are rejected in
-- cloudflare/native-worker/src/write-model.ts before any write happens, so a
-- device that upgraded to a rejected version never updates this column.
--
-- Why a table rebuild instead of `ALTER TABLE ... ADD COLUMN`:
-- `wrangler d1 migrations apply` replays 0001..0007 on a brand-new D1, and
-- 0001 already creates the column, so a bare ADD COLUMN would abort the whole
-- fresh-install path with "duplicate column name: collector_version".
-- The rebuild works on both paths: it appends the column to a database already
-- migrated to 0006, and is an equivalent recreate on a fresh one.
--
-- !! DO NOT RUN THIS FILE BY HAND ON A DATABASE THAT ALREADY HAS THE COLUMN !!
-- This migration is only STRUCTURALLY repeatable, it is NOT value-preserving.
-- The INSERT below lists the 10 legacy columns, so re-running it on an
-- already-migrated table copies those 10 across and leaves collector_version
-- NULL again -- silently discarding every version already recorded.
-- `wrangler d1 migrations apply` never replays an applied migration, so this
-- only bites someone executing the file manually. Locked in by
-- tests/test_d1_schema_migration.py so the property cannot drift unnoticed.
--
-- Why not the safer-looking `INSERT INTO ..._v2 SELECT *, NULL`, which would
-- abort a re-run instead of wiping data: it breaks the fresh-install path.
-- 0001 already creates the 11-column table, so replaying 0001..0007 on a brand
-- new D1 would feed 12 values into 11 columns and fail the whole deploy.
-- Supporting both real paths (fresh install, and 0006 upgrade) requires the
-- explicit 10-column list; the manual re-run hazard is the price.
--
-- The column must stay LAST. SQLite's ADD COLUMN can only append, so any other
-- position would make the fresh-install layout and the incremental layout
-- disagree on column order.
--
-- source_report_states carries no explicit index, trigger, view or foreign key
-- (verified via sqlite_master over the full migration chain); the only index is
-- the PRIMARY KEY auto-index, which the recreated table below reproduces.

CREATE TABLE source_report_states_v2 (
  source_id TEXT PRIMARY KEY,
  collected_at TEXT NOT NULL,
  report_type TEXT NOT NULL,
  command TEXT NOT NULL,
  status TEXT NOT NULL,
  ccusage_version TEXT,
  first_period TEXT,
  last_period TEXT,
  error_type TEXT,
  error_message TEXT,
  collector_version TEXT
);

INSERT INTO source_report_states_v2 (
  source_id, collected_at, report_type, command, status, ccusage_version,
  first_period, last_period, error_type, error_message
)
SELECT source_id, collected_at, report_type, command, status, ccusage_version,
       first_period, last_period, error_type, error_message
FROM source_report_states;

DROP TABLE source_report_states;
ALTER TABLE source_report_states_v2 RENAME TO source_report_states;
