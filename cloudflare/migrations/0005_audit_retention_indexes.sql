-- Keep the scheduled audit-retention job proportional to expired rows.
CREATE INDEX IF NOT EXISTS idx_collection_runs_collected_at
  ON collection_runs(collected_at);

CREATE INDEX IF NOT EXISTS idx_source_reports_run_id
  ON source_reports(run_id);
