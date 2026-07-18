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

CREATE INDEX IF NOT EXISTS idx_source_accuracy_status
  ON source_accuracy(accuracy_status, source_id, agent);
