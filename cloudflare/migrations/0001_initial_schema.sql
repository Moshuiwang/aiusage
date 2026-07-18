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

CREATE TABLE IF NOT EXISTS usage_blocks (
  source_id TEXT NOT NULL,
  start_time TEXT NOT NULL,
  end_time TEXT NOT NULL,
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
  PRIMARY KEY(source_id, start_time, end_time, agent)
);

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
  PRIMARY KEY(source_id, provider, source_type, window)
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

CREATE INDEX IF NOT EXISTS idx_source_accuracy_status
  ON source_accuracy(accuracy_status, source_id, agent);

CREATE UNIQUE INDEX IF NOT EXISTS idx_usage_hourly_facts_unique_hour
  ON usage_hourly_facts(
    source_id, agent, client, window_start, window_end,
    ai_provider, ai_account_id, attribution_confidence, provenance
  );
