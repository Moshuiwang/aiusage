-- Initial D1 schema for ai-usage-widget.
-- Mirrors src/ai_usage_widget/storage_sqlite.py::_ensure_schema.

CREATE TABLE IF NOT EXISTS collection_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  collected_at TEXT NOT NULL,
  timezone TEXT NOT NULL,
  collector_version TEXT,
  status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  source_id TEXT NOT NULL,
  report_type TEXT NOT NULL,
  command TEXT NOT NULL,
  status TEXT NOT NULL,
  ccusage_version TEXT,
  first_period TEXT,
  last_period TEXT,
  error_type TEXT,
  error_message TEXT,
  FOREIGN KEY(run_id) REFERENCES collection_runs(id)
);

-- Backfilled from 0005: the scheduled audit-retention job must stay proportional
-- to expired rows on a freshly created database too, not only on one that walked
-- the migration chain.
CREATE INDEX IF NOT EXISTS idx_collection_runs_collected_at
  ON collection_runs(collected_at);

CREATE INDEX IF NOT EXISTS idx_source_reports_run_id
  ON source_reports(run_id);

-- Read model for ingest-time source-report decisions. Keeping the latest
-- report per source here avoids re-sorting the full audit history on every
-- accepted ingest request.
CREATE TABLE IF NOT EXISTS source_report_states (
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
  -- Collector version of the last payload the server successfully accepted for
  -- this source -- not the version the device is currently running: payloads
  -- with an incompatible version are rejected before any write.
  -- Must stay last: 0007 adds this column to already-deployed databases, and
  -- SQLite can only append columns, so any other position would fork the
  -- column order between fresh installs and migrated databases.
  collector_version TEXT
);

-- Backfilled from 0009: authenticated requests rejected before the normal write
-- model can still be identified during a staged collector rollout.
CREATE TABLE IF NOT EXISTS rejected_ingest_attempts (
  source_id_claimed TEXT NOT NULL,
  error_type TEXT NOT NULL,
  path TEXT NOT NULL,
  day TEXT NOT NULL, -- AIUSAGE_TIMEZONE product day, UTC only if the timezone binding is invalid.
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  count INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(source_id_claimed, error_type, day)
);

CREATE INDEX IF NOT EXISTS idx_rejected_ingest_attempts_last_seen
  ON rejected_ingest_attempts(last_seen_at);

CREATE TABLE IF NOT EXISTS usage_daily (
  source_id TEXT NOT NULL,
  date TEXT NOT NULL,
  agent TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  total_cost REAL,
  metadata_json TEXT,
  raw_json TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY(source_id, date, agent)
);

CREATE TABLE IF NOT EXISTS usage_daily_models (
  source_id TEXT NOT NULL,
  date TEXT NOT NULL,
  agent TEXT NOT NULL,
  model_name TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  cost REAL,
  raw_json TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY(source_id, date, agent, model_name)
);

CREATE TABLE IF NOT EXISTS usage_hourly (
  source_id TEXT NOT NULL,
  hour TEXT NOT NULL,
  agent TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  total_cost REAL,
  metadata_json TEXT,
  raw_json TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY(source_id, hour, agent)
);

-- usage_blocks 已随 #74 删除：#91 停采 `ccusage blocks` 后该表零写入零读取，
-- 部署库由 0008_drop_usage_blocks.sql 收敛到同一形状。

CREATE TABLE IF NOT EXISTS source_identities (
  source_id TEXT PRIMARY KEY,
  host TEXT,
  machine TEXT,
  os_user TEXT,
  platform TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS machines (
  machine_id TEXT PRIMARY KEY,
  machine_name TEXT NOT NULL,
  host TEXT,
  platform TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS os_identities (
  machine_id TEXT NOT NULL,
  os_user TEXT NOT NULL,
  display_name TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY(machine_id, os_user)
);

CREATE TABLE IF NOT EXISTS ai_accounts (
  provider TEXT NOT NULL,
  account_id TEXT NOT NULL,
  account_label TEXT NOT NULL,
  display_name TEXT,
  subscription TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY(provider, account_id)
);

CREATE TABLE IF NOT EXISTS usage_hourly_facts (
  fact_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  machine_id TEXT NOT NULL,
  os_user TEXT NOT NULL,
  ai_provider TEXT NOT NULL,
  ai_account_id TEXT NOT NULL,
  agent TEXT NOT NULL,
  client TEXT,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  timezone TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  total_cost REAL,
  event_count INTEGER NOT NULL DEFAULT 0,
  session_count INTEGER NOT NULL DEFAULT 0,
  attribution_confidence TEXT NOT NULL,
  provenance TEXT NOT NULL,
  account_evidence_json TEXT,
  metadata_json TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_hourly_models (
  fact_id TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_output_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,
  total_cost REAL,
  metadata_json TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY(fact_id, model)
);

CREATE TABLE IF NOT EXISTS source_accuracy (
  source_id TEXT NOT NULL,
  agent TEXT NOT NULL,
  provenance TEXT NOT NULL,
  collector_version TEXT,
  parser_schema_version INTEGER,
  mode TEXT NOT NULL,
  lookback_hours REAL,
  coverage_start TEXT,
  coverage_end TEXT,
  report_digest TEXT,
  facts_digest TEXT,
  scan_complete INTEGER NOT NULL DEFAULT 0,
  read_errors INTEGER NOT NULL DEFAULT 0,
  unresolved_mismatch INTEGER NOT NULL DEFAULT 0,
  matching_full_scans INTEGER NOT NULL DEFAULT 0,
  accuracy_status TEXT NOT NULL,
  verified_at TEXT,
  metadata_json TEXT,
  observed_at TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY(source_id, agent)
);

CREATE TABLE IF NOT EXISTS limit_windows (
  source_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  window TEXT NOT NULL,
  used_percent REAL NOT NULL,
  remaining_percent REAL NOT NULL,
  reset_at TEXT NOT NULL,
  window_duration_minutes INTEGER NOT NULL,
  source_type TEXT NOT NULL,
  confidence TEXT NOT NULL,
  status TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY(source_id, provider, window)
);

CREATE INDEX IF NOT EXISTS idx_usage_hourly_facts_window
  ON usage_hourly_facts(window_start, window_end);

CREATE INDEX IF NOT EXISTS idx_usage_hourly_facts_account
  ON usage_hourly_facts(ai_provider, ai_account_id, window_start);

CREATE INDEX IF NOT EXISTS idx_usage_hourly_facts_machine_user
  ON usage_hourly_facts(machine_id, os_user, window_start);

CREATE INDEX IF NOT EXISTS idx_usage_hourly_facts_agent
  ON usage_hourly_facts(agent, window_start);

CREATE INDEX IF NOT EXISTS idx_usage_hourly_facts_source
  ON usage_hourly_facts(source_id, window_start);

-- Read models for the user-facing summary. Hourly rows are retained for the
-- recent window; daily rows retain the longer history.
CREATE TABLE IF NOT EXISTS usage_hourly_rollups (
  bucket_start TEXT NOT NULL,
  bucket_end TEXT NOT NULL,
  source_id TEXT NOT NULL,
  machine_id TEXT NOT NULL,
  os_user TEXT NOT NULL,
  ai_provider TEXT NOT NULL,
  ai_account_id TEXT NOT NULL,
  agent TEXT NOT NULL,
  client TEXT NOT NULL,
  attribution_confidence TEXT NOT NULL,
  provenance TEXT NOT NULL,
  input_tokens INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  cache_creation_tokens INTEGER NOT NULL,
  cache_read_tokens INTEGER NOT NULL,
  reasoning_output_tokens INTEGER NOT NULL,
  total_tokens INTEGER NOT NULL,
  event_count INTEGER NOT NULL,
  session_count INTEGER NOT NULL,
  fact_count INTEGER NOT NULL,
  PRIMARY KEY (bucket_start, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance)
);

CREATE TABLE IF NOT EXISTS usage_daily_rollups (
  date TEXT NOT NULL,
  bucket_start TEXT NOT NULL,
  bucket_end TEXT NOT NULL,
  source_id TEXT NOT NULL,
  machine_id TEXT NOT NULL,
  os_user TEXT NOT NULL,
  ai_provider TEXT NOT NULL,
  ai_account_id TEXT NOT NULL,
  agent TEXT NOT NULL,
  client TEXT NOT NULL,
  attribution_confidence TEXT NOT NULL,
  provenance TEXT NOT NULL,
  input_tokens INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  cache_creation_tokens INTEGER NOT NULL,
  cache_read_tokens INTEGER NOT NULL,
  reasoning_output_tokens INTEGER NOT NULL,
  total_tokens INTEGER NOT NULL,
  event_count INTEGER NOT NULL,
  session_count INTEGER NOT NULL,
  fact_count INTEGER NOT NULL,
  PRIMARY KEY (date, source_id, machine_id, os_user, ai_provider, ai_account_id, agent, client, attribution_confidence, provenance)
);

CREATE INDEX IF NOT EXISTS idx_usage_hourly_rollups_bucket
  ON usage_hourly_rollups(bucket_start);

CREATE INDEX IF NOT EXISTS idx_usage_daily_rollups_date
  ON usage_daily_rollups(date);

CREATE INDEX IF NOT EXISTS idx_source_accuracy_status
  ON source_accuracy(accuracy_status, source_id, agent);

CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_hourly_facts_unique_hour
  ON usage_hourly_facts(
    source_id, agent, client, window_start, window_end,
    ai_provider, ai_account_id, attribution_confidence, provenance
  );
